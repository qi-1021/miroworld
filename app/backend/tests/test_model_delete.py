"""模型配置删除功能测试：连接、模型条目、预设（含引用保护与级联）。"""

import json

import pytest

from app import create_app
from app.api import models as models_api
from app.models.model_config import ConnectionDraft, ModelEntryDraft, RoleBindings, ModelRole
from app.services.model_registry import ModelRegistryConflict, ModelRegistryService
from scripts.mirofish_models import main


@pytest.fixture
def registry(tmp_path):
    return ModelRegistryService(tmp_path / "model-config")


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    service = ModelRegistryService(tmp_path / "model-config")
    monkeypatch.setattr(models_api, "registry_service", service)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), service


def _seed_connection_and_model(registry, *, with_secret=True, verified=True):
    """创建一条连接和一个模型条目，返回 (connection_id, model_id)。"""
    connection = registry.save_connection(
        ConnectionDraft(
            name="Cloud",
            endpoint="https://models.example.com/v1",
            api_key="top-secret" if with_secret else None,
        ),
        expected_revision=None,
    )
    connection_id = connection["connection"]["id"]
    model = registry.save_model_entry(
        ModelEntryDraft(
            name="Alpha Chat",
            connection_id=connection_id,
            model_id="alpha-chat",
            capabilities=["chat"],
            verified=verified,
        ),
        expected_revision=None,
    )
    return connection_id, model["model"]["id"]


# ==================== 注册表层 ====================


def test_delete_model_entry_success(registry):
    connection_id, model_id = _seed_connection_and_model(registry)

    result = registry.delete_model_entry(model_entry_id=model_id, expected_revision=None)

    state = registry.get_redacted_registry()
    assert result["deleted"] == model_id
    assert all(item["id"] != model_id for item in state["models"])
    assert len(state["connections"]) == 1  # 连接保留


def test_delete_model_entry_blocked_when_bound_to_project(registry):
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_project_bindings(
        project_id="proj_x",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    with pytest.raises(ValueError, match="正被引用"):
        registry.delete_model_entry(model_entry_id=model_id, expected_revision=None)


def test_delete_model_entry_blocked_when_bound_to_snapshot(registry):
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.create_snapshot(
        owner_type="simulation",
        owner_id="sim_x",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    with pytest.raises(ValueError, match="正被引用"):
        registry.delete_model_entry(model_entry_id=model_id, expected_revision=None)


def test_delete_connection_cascades_models_and_secret(registry):
    connection_id, model_id = _seed_connection_and_model(registry, with_secret=True)

    result = registry.delete_connection(connection_id=connection_id, expected_revision=None)

    assert result["removed_models"] == 1
    state = registry.get_redacted_registry()
    assert all(item["id"] != connection_id for item in state["connections"])
    assert all(item["id"] != model_id for item in state["models"])
    # 密钥应被一并清除
    assert registry.resolve_connection_secret(connection_id) is None


def test_delete_connection_blocked_when_models_bound(registry):
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_project_bindings(
        project_id="proj_x",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    with pytest.raises(ValueError, match="正被引用"):
        registry.delete_connection(connection_id=connection_id, expected_revision=None)
    # 连接应原样保留
    assert registry.get_connection(connection_id) is not None


def test_delete_connection_missing_raises(registry):
    with pytest.raises(ValueError, match="连接不存在"):
        registry.delete_connection(connection_id="conn_missing", expected_revision=None)


def test_delete_requires_current_revision(registry):
    connection_id, model_id = _seed_connection_and_model(registry)
    current = registry.get_redacted_registry()["revision"]

    with pytest.raises(ModelRegistryConflict):
        registry.delete_model_entry(model_entry_id=model_id, expected_revision=current - 1)


def test_delete_preset_success(registry):
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_preset(
        preset_id="preset_fast",
        name="快速预设",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    result = registry.delete_preset(preset_id="preset_fast", expected_revision=None)

    assert result["deleted"] == "preset_fast"
    state = registry.get_redacted_registry()
    assert all(item["id"] != "preset_fast" for item in state["presets"])


# ==================== API 层 ====================


def test_api_delete_connection(api_client):
    http, registry = api_client
    connection_id, _ = _seed_connection_and_model(registry)

    response = http.delete(
        f"/api/models/connections/{connection_id}",
        query_string={"revision": registry.get_redacted_registry()["revision"]},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["removed_models"] == 1
    assert registry.get_redacted_registry()["revision"] == payload["data"]["revision"]


def test_api_delete_model_blocked_returns_400(api_client):
    http, registry = api_client
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_project_bindings(
        project_id="proj_x",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    response = http.delete(
        f"/api/models/entries/{model_id}",
        query_string={"revision": registry.get_redacted_registry()["revision"]},
    )

    assert response.status_code == 400
    assert "正被引用" in response.get_json()["error"]["message"]


def test_api_delete_stale_revision_returns_409(api_client):
    http, registry = api_client
    connection_id, model_id = _seed_connection_and_model(registry)

    response = http.delete(
        f"/api/models/entries/{model_id}", query_string={"revision": 0}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "REGISTRY_CONFLICT"


# ==================== CLI 层 ====================


def test_cli_remove_connection(tmp_path, capsys):
    registry = ModelRegistryService(tmp_path / "model-config")
    connection_id, _ = _seed_connection_and_model(registry)

    exit_code = main(
        ["--json", "connections", "remove", connection_id], registry=registry
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["deleted"] == connection_id
    assert registry.get_redacted_registry()["connections"] == []


def test_cli_remove_model_blocked_prints_error(tmp_path, capsys):
    registry = ModelRegistryService(tmp_path / "model-config")
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_project_bindings(
        project_id="proj_x",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    exit_code = main(["--json", "models", "remove", model_id], registry=registry)

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().err)
    assert "正被引用" in payload["error"]["message"]


def test_cli_presets_list_and_remove(tmp_path, capsys):
    registry = ModelRegistryService(tmp_path / "model-config")
    connection_id, model_id = _seed_connection_and_model(registry)
    registry.save_preset(
        preset_id="preset_fast",
        name="快速预设",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_id}),
        expected_revision=None,
    )

    assert main(["--json", "presets", "list"], registry=registry) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["data"]["presets"]) == 1

    assert (
        main(["--json", "presets", "remove", "preset_fast"], registry=registry) == 0
    )
    removed = json.loads(capsys.readouterr().out)
    assert removed["data"]["deleted"] == "preset_fast"
