"""
向量模型提供方偏好（embedding preference）测试：

1. get/set 偏好：默认 auto；写 cloud/local/auto 生效；非法值 ValueError。
2. world_bible._get_embedder 按偏好：
   - local：不解析云端（即使注册表有云端模型）
   - cloud：只用云端，云端不可用 → None（不落回本地）
   - auto：云端优先
3. API GET/PUT /api/models/embedding-preference。
"""
import pytest

from app import create_app
from app.services import embedding_resolver
from app.services import world_bible


@pytest.fixture(autouse=True)
def _isolate_pref(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_resolver, "_PREF_PATH", tmp_path / "embedding_preference.json")
    monkeypatch.delenv("EMBEDDING_PREFERENCE", raising=False)
    yield
    world_bible.WorldBibleService._reset_embedder_cache()


# ---------------------------------------------------------------------------
# 偏好读写
# ---------------------------------------------------------------------------
def test_preference_default_auto():
    assert embedding_resolver.get_embedding_preference() == "auto"


def test_preference_set_and_get():
    for pref in ("cloud", "local", "auto"):
        assert embedding_resolver.set_embedding_preference(pref) == pref
        assert embedding_resolver.get_embedding_preference() == pref


def test_preference_invalid_raises():
    with pytest.raises(ValueError):
        embedding_resolver.set_embedding_preference("banana")


def test_preference_env_overrides_file(tmp_path, monkeypatch):
    embedding_resolver.set_embedding_preference("local")
    monkeypatch.setenv("EMBEDDING_PREFERENCE", "cloud")
    assert embedding_resolver.get_embedding_preference() == "cloud"


# ---------------------------------------------------------------------------
# world_bible 按偏好选择
# ---------------------------------------------------------------------------
class _FakeRegistryCloud:
    def __init__(self, cloud_available=True):
        self._cloud = cloud_available

    def get_redacted_registry(self):
        models = []
        if self._cloud:
            models.append({
                "id": "m1", "name": "BAAI/bge-m3", "connection_id": "c1",
                "model_id": "BAAI/bge-m3", "capabilities": ["embedding"],
                "verified": True, "local_path": None, "metadata": {"dimension": 1024},
            })
        return {"models": models}

    def resolve_connection_secret(self, cid):
        return "sk-fake"

    def get_connection(self, cid):
        return {"endpoint": "https://api.siliconflow.cn/v1"}


def test_world_bible_local_pref_skips_cloud(monkeypatch):
    from app.services.model_registry import ModelRegistryService
    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": []})  # 云端存在但 local 偏好应跳过
    embedding_resolver.set_embedding_preference("local")

    # 云端解析函数应不被调用（local 模式直接跳过）→ 返回 None（无本地模型）
    calls = []
    monkeypatch.setattr(embedding_resolver, "resolve_registry_cloud_embedder",
                        lambda: calls.append(1) or _FakeCloud())
    emb = world_bible.WorldBibleService._get_embedder()
    assert emb is None
    assert calls == []  # local 模式没有尝试云端


class _FakeCloud:
    endpoint = "https://api.siliconflow.cn/v1"
    model = "BAAI/bge-m3"


def test_world_bible_cloud_pref_no_local_fallback(monkeypatch):
    from app.services.model_registry import ModelRegistryService
    embedding_resolver.set_embedding_preference("cloud")
    # 云端不可用（注册表无模型）→ None，不落回本地
    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": []})
    emb = world_bible.WorldBibleService._get_embedder()
    assert emb is None


def test_world_bible_auto_cloud_first(monkeypatch):
    from app.services.model_registry import ModelRegistryService
    embedding_resolver.set_embedding_preference("auto")
    monkeypatch.setattr(ModelRegistryService, "__init__", lambda self, data_dir=None: None)
    monkeypatch.setattr(ModelRegistryService, "get_redacted_registry",
                        lambda self: {"models": [{
                            "id": "m1", "name": "BAAI/bge-m3", "connection_id": "c1",
                            "model_id": "BAAI/bge-m3", "capabilities": ["embedding"],
                            "verified": True, "local_path": None,
                        }]})
    monkeypatch.setattr(ModelRegistryService, "resolve_connection_secret",
                        lambda self, cid: "sk-fake")
    monkeypatch.setattr(ModelRegistryService, "get_connection",
                        lambda self, cid: {"endpoint": "https://api.siliconflow.cn/v1"})
    emb = world_bible.WorldBibleService._get_embedder()
    assert emb is not None
    assert emb.model == "BAAI/bge-m3"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_preference_api(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_resolver, "_PREF_PATH", tmp_path / "pref.json")
    monkeypatch.delenv("EMBEDDING_PREFERENCE", raising=False)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/models/embedding-preference")
        assert r.status_code == 200
        assert r.get_json()["data"]["preference"] == "auto"
        r2 = c.put("/api/models/embedding-preference", json={"preference": "cloud"})
        assert r2.status_code == 200
        assert r2.get_json()["data"]["preference"] == "cloud"
        r3 = c.put("/api/models/embedding-preference", json={"preference": "bad"})
        assert r3.status_code == 400


def test_preference_api_resets_embedder_cache(tmp_path, monkeypatch):
    """切换偏好后，进程内 world_bible 的懒加载 embedder 缓存应立即失效。"""
    monkeypatch.setattr(embedding_resolver, "_PREF_PATH", tmp_path / "pref.json")
    monkeypatch.delenv("EMBEDDING_PREFERENCE", raising=False)
    monkeypatch.setattr(
        world_bible.WorldBibleService, "_embedder_cache", object(), raising=False
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.put("/api/models/embedding-preference", json={"preference": "local"})
        assert r.status_code == 200
    assert world_bible.WorldBibleService._embedder_cache is None
