"""本地向量模型模块测试。"""
import json
from pathlib import Path

import pytest

from app import create_app
from app.api import models as models_api
from app.services import local_embedding
from app.services.embedding_fingerprint import compute_embedding_fingerprint
from app.services.local_embedding import (
    LOCAL_MODELS_ROOT,
    LocalModelNotFoundError,
    LocalRuntimeMissingError,
    compute_local_fingerprint,
    inspect_local_model,
    safe_model_dir,
    scan_local_models,
)
from app.services.model_registry import ModelRegistryService
from app.services.model_resolver import ModelResolver


@pytest.fixture
def fake_models_root(tmp_path, monkeypatch):
    """把扫描根目录指向临时目录，并构造一个标准 HF 布局的假模型。"""
    root = tmp_path / "embeddings"
    root.mkdir()
    monkeypatch.setattr(local_embedding, "LOCAL_MODELS_ROOT", root)
    model_dir = root / "bge-small-zh"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps(
            {
                "hidden_size": 512,
                "max_position_embeddings": 512,
                "model_type": "bert",
                "architectures": ["BertModel"],
            }
        ),
        encoding="utf-8",
    )
    (model_dir / "model.safetensors").write_bytes(b"fake-weights")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    return root


def test_scan_local_models_recognizes_hf_layout(fake_models_root):
    results = scan_local_models()
    assert len(results) == 1
    item = results[0]
    assert item["name"] == "bge-small-zh"
    assert item["dimension"] == 512
    assert item["max_length"] == 512
    assert item["model_type"] == "bert"
    assert item["has_config"] is True
    assert item["has_weights"] is True


def test_scan_ignores_non_model_directories(fake_models_root):
    (fake_models_root / ".cache").mkdir()
    (fake_models_root / "notes.txt").write_text("x", encoding="utf-8")
    results = scan_local_models()
    assert all(item["name"] != ".cache" for item in results)
    assert all(item["name"] != "notes.txt" for item in results)


def test_scan_reports_missing_weights(fake_models_root):
    (fake_models_root / "bge-small-zh" / "model.safetensors").unlink()
    results = scan_local_models()
    assert len(results) == 1
    assert results[0]["has_weights"] is False
    assert results[0]["ready"] is False


def test_safe_model_dir_rejects_path_traversal(fake_models_root):
    with pytest.raises(LocalModelNotFoundError):
        safe_model_dir("..")
    with pytest.raises(LocalModelNotFoundError):
        safe_model_dir("../secret")
    with pytest.raises(LocalModelNotFoundError):
        safe_model_dir("a/b")
    with pytest.raises(LocalModelNotFoundError):
        safe_model_dir("不存在")


def test_safe_model_dir_rejects_symlink_escape(fake_models_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.json").write_text("{}", encoding="utf-8")
    link = fake_models_root / "evil-link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LocalModelNotFoundError):
        safe_model_dir("evil-link")


def test_inspect_local_model_reads_metadata(fake_models_root):
    info = inspect_local_model("bge-small-zh")
    assert info["dimension"] == 512
    assert info["max_length"] == 512
    assert info["model_type"] == "bert"


def test_probe_raises_readable_error_when_runtime_missing(fake_models_root, monkeypatch):
    monkeypatch.setattr(local_embedding, "_runtime_available", lambda: False)
    with pytest.raises(LocalRuntimeMissingError, match="sentence-transformers"):
        local_embedding.probe_local_model("bge-small-zh")


def test_local_fingerprint_stable_and_dimension_sensitive():
    fp1 = compute_local_fingerprint(
        name="bge-small-zh", dimension=512, max_length=512, model_type="bert"
    )
    fp2 = compute_local_fingerprint(
        name="bge-small-zh", dimension=512, max_length=512, model_type="bert"
    )
    fp3 = compute_local_fingerprint(
        name="bge-small-zh", dimension=768, max_length=512, model_type="bert"
    )
    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64


def test_embedding_fingerprint_includes_prefix_policy():
    a = compute_embedding_fingerprint(
        provider="local", model_id="m", query_prefix="查询："
    )
    b = compute_embedding_fingerprint(
        provider="local", model_id="m", query_prefix=""
    )
    assert a != b


# ==================== API 层 ====================


@pytest.fixture
def api_client(tmp_path, monkeypatch, fake_models_root):
    registry = ModelRegistryService(tmp_path / "model-config")
    monkeypatch.setattr(models_api, "registry_service", registry)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), registry


def test_api_scan_local_models(api_client, fake_models_root):
    http, _ = api_client
    response = http.get("/api/models/local/scan")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    names = [item["name"] for item in payload["data"]["models"]]
    assert "bge-small-zh" in names
    item = next(i for i in payload["data"]["models"] if i["name"] == "bge-small-zh")
    assert item["dimension"] == 512


def test_api_register_local_model_and_resolve_embedding(api_client, fake_models_root):
    http, registry = api_client

    response = http.post("/api/models/local/bge-small-zh/register", json={"revision": 0})
    assert response.status_code == 201
    payload = response.get_json()["data"]
    model = payload["model"]
    assert model["connection_id"] is None
    assert model["local_path"] == "bge-small-zh"
    assert model["capabilities"] == ["embedding"]
    assert model["verified"] is True
    assert "fingerprint" in model["metadata"]
    assert model["metadata"]["dimension"] == 512

    # 绑定到 embedding 角色并创建快照，然后通过解析器取回本地路径
    model_id = model["id"]
    binding = http.put(
        "/api/models/projects/proj_local/bindings",
        json={"revision": 1, "roles": {"graphiti_embedding": model_id}},
    )
    assert binding.status_code == 200

    snapshot = http.post(
        "/api/models/tasks/graph/graph_1/snapshot",
        json={
            "revision": 2,
            "roles": {"graphiti_embedding": model_id},
        },
    )
    assert snapshot.status_code == 201
    snapshot_id = snapshot.get_json()["data"]["id"]

    resolved = ModelResolver(registry).resolve_embedding(snapshot_id)
    assert resolved.local_path == "bge-small-zh"
    assert resolved.dimension == 512
    assert resolved.connection_id is None


def test_api_register_missing_local_model_returns_404(api_client):
    http, _ = api_client
    response = http.post("/api/models/local/不存在模型/register", json={"revision": 0})
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "LOCAL_MODEL_NOT_FOUND"


# ==================== Graphiti 集成 ====================


class _FakeRegistry:
    def __init__(self, models):
        self._models = models

    def get_redacted_registry(self):
        return {"models": self._models}


def _make_entry(**overrides):
    entry = {
        "id": "model_local_1",
        "verified": True,
        "capabilities": ["embedding"],
        "local_path": "bge-small-zh",
        "metadata": {"dimension": 512},
    }
    entry.update(overrides)
    return entry


def test_graphiti_prefers_registered_local_embedder(fake_models_root, monkeypatch):
    from app.services import zep_graphiti_impl

    fake = _FakeRegistry([_make_entry()])
    monkeypatch.setattr("app.services.model_registry.ModelRegistryService", lambda: fake)
    monkeypatch.setattr(local_embedding, "LOCAL_MODELS_ROOT", fake_models_root)

    embedder = zep_graphiti_impl.GraphitiClient._try_build_local_embedder()
    assert embedder is not None
    assert embedder.dimension == 512
    assert str(embedder.model_dir).endswith("bge-small-zh")


def test_graphiti_falls_back_when_no_local_embedding(fake_models_root, monkeypatch):
    from app.services import zep_graphiti_impl

    cloud_entry = {
        "id": "model_cloud_1",
        "verified": True,
        "capabilities": ["embedding"],
        "local_path": None,
        "metadata": {},
    }
    fake = _FakeRegistry([cloud_entry])
    monkeypatch.setattr("app.services.model_registry.ModelRegistryService", lambda: fake)
    monkeypatch.setattr(local_embedding, "LOCAL_MODELS_ROOT", fake_models_root)

    assert zep_graphiti_impl.GraphitiClient._try_build_local_embedder() is None


def test_graphiti_skips_local_model_with_missing_directory(fake_models_root, monkeypatch):
    from app.services import zep_graphiti_impl

    fake = _FakeRegistry([_make_entry(local_path="不存在的目录")])
    monkeypatch.setattr("app.services.model_registry.ModelRegistryService", lambda: fake)
    monkeypatch.setattr(local_embedding, "LOCAL_MODELS_ROOT", fake_models_root)

    assert zep_graphiti_impl.GraphitiClient._try_build_local_embedder() is None
