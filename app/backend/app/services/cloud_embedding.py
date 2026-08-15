"""
云端向量模型（OpenAI 兼容 /embeddings，如 SiliconFlow / DashScope / OpenAI）

- 提供与 LocalSentenceTransformerEmbedder 相同的接口面：
    async create(input_data) -> list[float]
    async create_batch(list[str]) -> list[list[float]]
    同步 _encode(list[str]) -> list[list[float]]（供事件循环内兜底 / 测试）
- 自动按 batch_size 切分请求；按 dimension 截断输出维度，
  避免与已有图谱向量维度不一致污染数据。
- 直连 httpx（trust_env=False），避免 macOS 系统代理偶发断连。
"""
import asyncio
import threading
from typing import Any, List, Optional

import httpx


class CloudEmbeddingError(RuntimeError):
    """云端向量服务调用失败。"""


class CloudOpenAIEmbedder:
    """OpenAI 兼容 /embeddings 客户端（异步 + 同步 _encode 双通道）。"""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        dimension: Optional[int] = None,
        batch_size: int = 32,
        timeout: float = 120.0,
    ):
        self.endpoint = str(endpoint or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self._dimension = dimension
        self.batch_size = max(1, int(batch_size or 32))
        self.timeout = timeout
        self._headers = {"Authorization": f"Bearer {self.api_key}"}
        self._sync_client: Optional[httpx.Client] = None
        self._lock = threading.Lock()

    @property
    def dimension(self) -> Optional[int]:
        return self._dimension

    def _url(self) -> str:
        return f"{self.endpoint}/embeddings"

    def _request(self, batch: List[str]) -> List[List[float]]:
        if not batch:
            return []
        if not self.api_key or not self.endpoint:
            raise CloudEmbeddingError("云端向量模型未配置 endpoint/api_key")
        try:
            resp = httpx.post(
                self._url(),
                headers=self._headers,
                json={"model": self.model, "input": batch},
                timeout=self.timeout,
                trust_env=False,
            )
        except Exception as exc:  # 网络层错误
            raise CloudEmbeddingError(f"云端向量服务请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise CloudEmbeddingError(
                f"云端向量服务返回 {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
            items = data.get("data") or []
            vectors = [item["embedding"] for item in items if "embedding" in item]
        except Exception as exc:
            raise CloudEmbeddingError(f"云端向量响应解析失败: {exc}") from exc
        if len(vectors) != len(batch):
            raise CloudEmbeddingError(
                f"云端向量返回数量不匹配（期望 {len(batch)}，得到 {len(vectors)}）"
            )
        return self._trim(vectors)

    def _trim(self, vectors: List[List[float]]) -> List[List[float]]:
        dim = self._dimension
        if not dim:
            return [[float(x) for x in v] for v in vectors]
        return [[float(x) for x in v[:dim]] for v in vectors]

    # ---------------- 异步通道 ----------------
    async def _arequest(self, batch: List[str]) -> List[List[float]]:
        if not batch:
            return []
        if not self.api_key or not self.endpoint:
            raise CloudEmbeddingError("云端向量模型未配置 endpoint/api_key")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.post(
                    self._url(),
                    headers=self._headers,
                    json={"model": self.model, "input": batch},
                )
        except Exception as exc:
            raise CloudEmbeddingError(f"云端向量服务请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise CloudEmbeddingError(
                f"云端向量服务返回 {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
            items = data.get("data") or []
            vectors = [item["embedding"] for item in items if "embedding" in item]
        except Exception as exc:
            raise CloudEmbeddingError(f"云端向量响应解析失败: {exc}") from exc
        if len(vectors) != len(batch):
            raise CloudEmbeddingError(
                f"云端向量返回数量不匹配（期望 {len(batch)}，得到 {len(vectors)}）"
            )
        return self._trim(vectors)

    async def create(self, input_data: str | list[str] | Any) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        return (await self._arequest(texts))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        texts = list(input_data_list)
        out: List[List[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(await self._arequest(texts[i:i + self.batch_size]))
        return out

    # ---------------- 同步通道（事件循环内兜底） ----------------
    def _encode(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._request(texts[i:i + self.batch_size]))
        return out
