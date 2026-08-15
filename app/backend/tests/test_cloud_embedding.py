"""
云端向量模型（CloudOpenAIEmbedder）+ 云端优先解析测试：

1. CloudOpenAIEmbedder：mock httpx → create/create_batch/_encode 返回向量、
   维度截断、批次切分、错误传播（非 2xx / 数量不匹配 / 未配置）。
2. zep_graphiti_impl._build_default_embedder：注册表云端模型优先于本地模型。
3. world_bible._get_embedder：云端优先 → 本地 → 关键词降级。
"""
import asyncio
import json

import pytest

from app.services import cloud_embedding
from app.services.cloud_embedding import CloudOpenAIEmbedder, CloudEmbeddingError


def _resp_body(n, dim=1024):
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": [float(i + 1)] * dim}
            for i in range(n)
        ],
        "model": "BAAI/bge-m3",
    }


# ---------------------------------------------------------------------------
# CloudOpenAIEmbedder
# ---------------------------------------------------------------------------
class _FakeSyncResp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text or json.dumps(body) if body else text

    def json(self):
        return self._body


def test_cloud_encode_and_trim(monkeypatch):
    """create/_encode 返回向量并按 dimension 截断。"""
    calls = {}

    def fake_post(url, headers, json, timeout, trust_env):
        calls["url"] = url
        calls["model"] = json["model"]
        calls["input"] = json["input"]
        return _FakeSyncResp(200, _resp_body(len(json["input"]), dim=1024))

    monkeypatch.setattr(httpx_marker := cloud_embedding.httpx, "post", fake_post)

    emb = CloudOpenAIEmbedder(
        endpoint="https://api.siliconflow.cn/v1", api_key="sk-test", model="BAAI/bge-m3",
        dimension=1024,
    )
    v = emb._encode(["文本一", "文本二"])
    assert len(v) == 2 and len(v[0]) == 1024
    assert calls["url"] == "https://api.siliconflow.cn/v1/embeddings"
    assert calls["model"] == "BAAI/bge-m3"
    assert calls["input"] == ["文本一", "文本二"]

    # 维度截断：dimension=16
    emb16 = CloudOpenAIEmbedder(
        endpoint="https://api.siliconflow.cn/v1", api_key="sk-test", model="BAAI/bge-m3",
        dimension=16,
    )
    v16 = emb16._encode(["文本"])
    assert len(v16[0]) == 16


def test_cloud_batch_split_and_async(monkeypatch):
    """批次切分 + async create/create_batch。"""
    seen = []

    class FakeAsyncResp:
        status_code = 200

        def json(self):
            return _resp_body(len(seen[-1]["json"]["input"]))

    def make_fake_client(fake_post):
        class _Client:
            def __init__(self, timeout=None, trust_env=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers, json, timeout=None):
                return await fake_post(url, headers, json, timeout)

        return _Client

    async def fake_apost(url, headers, json, timeout=None):
        seen.append({"url": url, "json": json})
        return FakeAsyncResp()

    monkeypatch.setattr(cloud_embedding.httpx, "AsyncClient", make_fake_client(fake_apost))
    monkeypatch.setattr(cloud_embedding.httpx, "post", lambda **kw: _FakeSyncResp(200, _resp_body(1)))

    emb = CloudOpenAIEmbedder(
        endpoint="https://api.siliconflow.cn/v1", api_key="sk-test", model="BAAI/bge-m3",
        batch_size=2,
    )
    vs = asyncio.run(emb.create_batch(["a", "b", "c", "d", "e"]))
    assert len(vs) == 5
    # 5 条 / 每批 2 → 3 次请求
    assert len(seen) == 3
    assert [len(s["json"]["input"]) for s in seen] == [2, 2, 1]

    single = asyncio.run(emb.create("单条"))
    assert len(single) == 1024


def test_cloud_error_propagation(monkeypatch):
    """401 / 数量不匹配 / 未配置 → CloudEmbeddingError。"""
    emb = CloudOpenAIEmbedder(endpoint="", api_key="", model="x")
    with pytest.raises(CloudEmbeddingError):
        emb._encode(["x"])

    def fake_401(url, headers, json, timeout, trust_env):
        return _FakeSyncResp(401, None, '{"message":"Token is invalid."}')

    monkeypatch.setattr(cloud_embedding.httpx, "post", fake_401)
    emb2 = CloudOpenAIEmbedder(endpoint="https://x/v1", api_key="bad", model="m")
    with pytest.raises(CloudEmbeddingError) as ei:
        emb2._encode(["x"])
    assert "401" in str(ei.value)

    def fake_short(url, headers, json, timeout, trust_env):
        return _FakeSyncResp(200, _resp_body(0))  # 0 条 vs 期望 1

    monkeypatch.setattr(cloud_embedding.httpx, "post", fake_short)
    with pytest.raises(CloudEmbeddingError):
        emb2._encode(["x"])


# ---------------------------------------------------------------------------
# 云端优先解析
# ---------------------------------------------------------------------------
class _FakeRegistry:
    def __init__(self, models):
        self._models = models

    def get_redacted_registry(self):
        return {"models": self._models}

    def resolve_connection_secret(self, cid):
        return "sk-fake" if cid == "conn_cloud" else None

    def get_connection(self, cid):
        if cid == "conn_cloud":
            return {"endpoint": "https://api.siliconflow.cn/v1"}
        return None


def _cloud_entry(model_id="BAAI/bge-m3"):
    return {
        "id": "m_cloud", "name": model_id, "connection_id": "conn_cloud",
        "model_id": model_id, "capabilities": ["embedding"],
        "verified": True, "local_path": None, "metadata": {"dimension": 1024},
    }


def _local_entry():
    return {
        "id": "m_local", "name": "bge-m3", "connection_id": None,
        "model_id": "bge-m3", "capabilities": ["embedding"],
        "verified": True, "local_path": "bge-m3", "metadata": {"dimension": 1024},
    }


def test_graphiti_build_embedder_cloud_first(monkeypatch):
    """注册表云端 + 本地并存 → _build_default_embedder 返回云端。"""
    from app.services import zep_graphiti_impl
    from app.services.model_registry import ModelRegistryService

    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": [_cloud_entry(), _local_entry()]})
    monkeypatch.setattr(ModelRegistryService, "resolve_connection_secret",
                        lambda self, cid: "sk-fake")
    monkeypatch.setattr(ModelRegistryService, "get_connection",
                        lambda self, cid: {"endpoint": "https://api.siliconflow.cn/v1"})

    svc = zep_graphiti_impl.GraphitiClient("proj_test", "neo4j", "pw")
    embedder = svc._build_default_embedder()
    assert embedder is not None
    # 云端路径：包装器内部是 CloudOpenAIEmbedder
    inner = getattr(embedder, "_inner", None)
    assert inner is not None
    assert isinstance(inner, CloudOpenAIEmbedder)
    assert "siliconflow" in inner.endpoint


def test_graphiti_build_embedder_local_only_fallback(monkeypatch):
    """仅本地模型时回退本地路径。"""
    from app.services import zep_graphiti_impl
    from app.services.model_registry import ModelRegistryService

    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": [_local_entry()]})

    svc = zep_graphiti_impl.GraphitiClient("proj_test", "neo4j", "pw")
    embedder = svc._build_default_embedder()
    # 本地模型目录不存在时 → 继续回退到 env OpenAI embedder（可能为 None 由调用方处理）
    assert embedder is not None  # 环境变量回退存在


def test_world_bible_get_embedder_cloud_first(monkeypatch):
    """world_bible._get_embedder 云端优先。"""
    from app.services import world_bible
    from app.services.model_registry import ModelRegistryService

    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": [_cloud_entry(), _local_entry()]})
    monkeypatch.setattr(ModelRegistryService, "resolve_connection_secret",
                        lambda self, cid: "sk-fake")
    monkeypatch.setattr(ModelRegistryService, "get_connection",
                        lambda self, cid: {"endpoint": "https://api.siliconflow.cn/v1"})

    world_bible.WorldBibleService._reset_embedder_cache()
    emb = world_bible.WorldBibleService._get_embedder()
    assert emb is not None
    assert isinstance(emb, CloudOpenAIEmbedder)
    assert "siliconflow" in emb.endpoint
    world_bible.WorldBibleService._reset_embedder_cache()
