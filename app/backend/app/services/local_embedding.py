"""本地向量模型接入。

用户把标准 Hugging Face / Sentence Transformers 模型目录放到
app/models/embeddings/<模型目录>/ 下，本模块负责：
1. 扫描并识别模型（读取 config.json 推断维度、最大长度等）；
2. 真实探测（需要可选运行时 sentence-transformers）；
3. 提供与 graphiti-core EmbedderClient 兼容的本地 Embedder。

运行时说明：sentence-transformers 体积较大，作为可选依赖安装：
    uv pip install sentence-transformers
未安装时扫描仍可用，但探测/注册会返回明确提示。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.local_embedding")

# app/backend/app/services/local_embedding.py -> app/models/embeddings
LOCAL_MODELS_ROOT = Path(__file__).resolve().parents[3] / "models" / "embeddings"

# 常见权重文件名，用于判断目录是否为完整可加载模型
WEIGHT_MARKERS = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.bin",
    "onnx/model.onnx",
)


class LocalModelError(RuntimeError):
    pass


class LocalModelNotFoundError(LocalModelError):
    pass


class LocalRuntimeMissingError(LocalModelError):
    """缺少 sentence-transformers 运行时。"""

    INSTALL_HINT = "未安装本地向量推理组件，请运行: uv pip install sentence-transformers"

    def __init__(self, message: str = INSTALL_HINT):
        super().__init__(message)


def _models_root() -> Path:
    LOCAL_MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    return LOCAL_MODELS_ROOT


def safe_model_dir(name: str) -> Path:
    """校验模型目录名并防止路径逃逸。"""
    if not name or name.strip() in ("", ".", ".."):
        raise LocalModelNotFoundError(f"无效的模型目录名: {name!r}")
    if "/" in name or "\\" in name or "\x00" in name:
        raise LocalModelNotFoundError(f"无效的模型目录名: {name!r}")
    root = _models_root().resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise LocalModelNotFoundError("模型目录超出允许范围")
    if not target.is_dir():
        raise LocalModelNotFoundError(f"模型目录不存在: {name}")
    return target


def _read_model_config(model_dir: Path) -> Dict[str, Any]:
    config_path = model_dir / "config.json"
    if not config_path.is_file():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 %s 失败: %s", config_path, exc)
        return {}


def _weight_size_mb(model_dir: Path) -> float:
    total = 0
    for pattern in ("*.safetensors", "*.bin"):
        for path in model_dir.glob(pattern):
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 1)


def _runtime_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def scan_local_models() -> List[Dict[str, Any]]:
    """扫描 app/models/embeddings/ 的直接子目录，识别本地向量模型。"""
    root = _models_root()
    results: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            target = child.resolve()
            if not target.is_relative_to(root.resolve()):
                logger.warning("忽略越界目录: %s", child)
                continue
        except OSError:
            continue
        config = _read_model_config(child)
        has_config = bool(config)
        has_weights = any(
            path
            for pattern in ("*.safetensors", "*.bin")
            for path in child.glob(pattern)
        )
        dimension = config.get("hidden_size")
        max_length = config.get("max_position_embeddings")
        results.append(
            {
                "name": child.name,
                "path": str(child),
                "dimension": int(dimension) if isinstance(dimension, int) else None,
                "max_length": int(max_length) if isinstance(max_length, int) else None,
                "model_type": config.get("model_type"),
                "has_config": has_config,
                "has_weights": has_weights,
                "size_mb": _weight_size_mb(child),
                "runtime_available": _runtime_available(),
                "ready": has_config and has_weights and _runtime_available(),
            }
        )
    return results


def inspect_local_model(name: str) -> Dict[str, Any]:
    """读取单个本地模型的元数据。"""
    model_dir = safe_model_dir(name)
    config = _read_model_config(model_dir)
    dimension = config.get("hidden_size")
    return {
        "name": name,
        "path": str(model_dir),
        "dimension": int(dimension) if isinstance(dimension, int) else None,
        "max_length": config.get("max_position_embeddings"),
        "model_type": config.get("model_type"),
        "architecture": config.get("architectures"),
        "runtime_available": _runtime_available(),
    }


class LocalSentenceTransformerEmbedder:
    """graphiti-core EmbedderClient 兼容的本地向量模型封装。

    懒加载模型，CPU 默认；输出维度按配置截断，避免维度不一致污染图谱。
    """

    def __init__(self, model_dir: str, dimension: Optional[int] = None, batch_size: int = 32):
        self.model_dir = model_dir
        self._dimension = dimension
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    @property
    def dimension(self) -> Optional[int]:
        return self._dimension

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise LocalRuntimeMissingError() from exc
            self._model = SentenceTransformer(self.model_dir)
            # 若未显式指定维度，从模型输出推断
            if self._dimension is None:
                sample = self._model.encode(["维度探测"])
                self._dimension = len(sample[0])
        return self._model

    def _encode(self, texts: List[str]) -> List[List[float]]:
        model = self._load()
        vectors = model.encode(texts, batch_size=self.batch_size, show_progress_bar=False)
        dim = self._dimension
        # numpy float32 无法 JSON 序列化，统一转为 Python float
        return [
            [float(x) for x in (v[:dim] if dim else v)]
            for v in vectors
        ]

    async def create(
        self, input_data: str | list[str] | Any
    ) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        return self._encode(texts)[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return self._encode(list(input_data_list))


def probe_local_model(name: str, sample_texts: Optional[List[str]] = None) -> Dict[str, Any]:
    """真实加载模型并执行一次向量计算，验证可用性。"""
    model_dir = safe_model_dir(name)
    if not _runtime_available():
        raise LocalRuntimeMissingError()
    texts = sample_texts or ["Miroworld 本地向量模型测试", "The quick brown fox jumps over the lazy dog"]
    embedder = LocalSentenceTransformerEmbedder(str(model_dir))
    t0 = time.time()
    vectors = embedder._encode(texts)
    elapsed = round(time.time() - t0, 2)
    dims = {len(v) for v in vectors}
    if len(dims) != 1:
        raise LocalModelError(f"向量维度不一致: {dims}")
    dimension = dims.pop()
    sample = vectors[0][:8]
    return {
        "name": name,
        "dimension": dimension,
        "elapsed_seconds": elapsed,
        "sample_prefix": sample,
        "texts": len(texts),
        "runtime": "sentence-transformers",
    }


def compute_local_fingerprint(*, name: str, dimension: Optional[int], max_length: Optional[int], model_type: Optional[str]) -> str:
    """计算本地模型指纹：用于图谱向量一致性校验。"""
    from .embedding_fingerprint import compute_embedding_fingerprint

    return compute_embedding_fingerprint(
        provider="local",
        model_id=name,
        dimension=dimension,
        max_length=max_length,
        model_type=model_type,
        local_path=name,
    )
