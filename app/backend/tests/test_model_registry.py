import json
import stat
from pathlib import Path

import pytest

from app.models.model_config import (
    ConnectionDraft,
    ModelEntryDraft,
    ModelRole,
    RoleBindings,
)
from app.services.model_registry import (
    ModelRegistryConflict,
    ModelRegistryService,
)


def make_registry(tmp_path: Path) -> ModelRegistryService:
    return ModelRegistryService(data_dir=tmp_path / "model-config")


def test_default_registry_path_lives_under_app_data():
    service = ModelRegistryService.__new__(ModelRegistryService)
    default_dir = Path(__file__).resolve().parents[2] / "data" / "model-config"

    ModelRegistryService.__init__(service, data_dir=default_dir)

    assert service.data_dir == default_dir


def test_registry_initializes_with_redacted_empty_state(tmp_path):
    service = make_registry(tmp_path)

    result = service.get_redacted_registry()

    assert result["revision"] == 0
    assert result["connections"] == []
    assert result["models"] == []
    assert result["presets"] == []
    assert (tmp_path / "model-config" / "registry.json").exists()


def test_connection_secret_is_versioned_and_never_returned(tmp_path):
    service = make_registry(tmp_path)

    saved = service.save_connection(
        ConnectionDraft(
            name="DeepSeek 主账号",
            endpoint="https://api.deepseek.com/v1",
            api_key="sk-very-secret-value",
        ),
        expected_revision=0,
    )

    public = service.get_redacted_registry()
    connection = public["connections"][0]
    assert connection["id"] == saved["connection"]["id"]
    assert connection["has_secret"] is True
    assert connection["secret_suffix"] == "alue"
    assert "api_key" not in connection
    assert "secret_revision_id" not in connection
    assert "sk-very-secret-value" not in json.dumps(public)

    registry_text = (tmp_path / "model-config" / "registry.json").read_text()
    assert "sk-very-secret-value" not in registry_text

    secret_path = tmp_path / "model-config" / "secrets.json"
    assert "sk-very-secret-value" in secret_path.read_text()
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(secret_path.stat().st_mode) & 0o077 == 0


def test_stale_revision_cannot_overwrite_registry(tmp_path):
    service = make_registry(tmp_path)
    service.save_connection(
        ConnectionDraft(name="Local", endpoint="http://localhost:11434"),
        expected_revision=0,
    )

    with pytest.raises(ModelRegistryConflict) as exc_info:
        service.save_connection(
            ConnectionDraft(name="Stale", endpoint="https://example.com/v1"),
            expected_revision=0,
        )

    assert exc_info.value.current_revision == 1
    assert service.get_redacted_registry()["revision"] == 1


def test_updating_unknown_connection_is_rejected(tmp_path):
    service = make_registry(tmp_path)

    with pytest.raises(ValueError, match="连接不存在"):
        service.save_connection(
            ConnectionDraft(name="Missing", endpoint="https://example.com/v1"),
            connection_id="conn_missing",
            expected_revision=0,
        )


def test_snapshot_keeps_original_secret_revision_after_key_replacement(tmp_path):
    service = make_registry(tmp_path)
    first = service.save_connection(
        ConnectionDraft(
            name="Cloud",
            endpoint="https://example.com/v1",
            api_key="first-secret",
        ),
        expected_revision=0,
    )
    connection_id = first["connection"]["id"]

    model_result = service.save_model_entry(
        ModelEntryDraft(
            name="Chat model",
            connection_id=connection_id,
            model_id="test-chat",
            capabilities=["chat"],
            verified=True,
        ),
        expected_revision=1,
    )
    model_entry_id = model_result["model"]["id"]
    snapshot = service.create_snapshot(
        owner_type="simulation",
        owner_id="sim_before_rotation",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: model_entry_id}),
        expected_revision=2,
    )

    service.save_connection(
        ConnectionDraft(
            name="Cloud",
            endpoint="https://example.com/v1",
            api_key="second-secret",
        ),
        connection_id=connection_id,
        secret_action="replace",
        expected_revision=3,
    )

    assert service.resolve_snapshot_secret(snapshot["id"], ModelRole.PRIMARY) == "first-secret"
    assert service.resolve_connection_secret(connection_id) == "second-secret"


def test_unverified_model_cannot_be_bound_to_snapshot(tmp_path):
    service = make_registry(tmp_path)
    connection = service.save_connection(
        ConnectionDraft(name="Local", endpoint="http://localhost:1234/v1"),
        expected_revision=0,
    )
    model = service.save_model_entry(
        ModelEntryDraft(
            name="Unknown",
            connection_id=connection["connection"]["id"],
            model_id="unknown-model",
            capabilities=["chat"],
            verified=False,
        ),
        expected_revision=1,
    )

    with pytest.raises(ValueError, match="尚未通过能力测试"):
        service.create_snapshot(
            owner_type="simulation",
            owner_id="sim_unverified",
            bindings=RoleBindings(
                roles={ModelRole.PRIMARY: model["model"]["id"]}
            ),
            expected_revision=2,
        )


def test_project_bindings_are_replaced_atomically(tmp_path):
    service = make_registry(tmp_path)
    connection = service.save_connection(
        ConnectionDraft(name="Local", endpoint="http://localhost:11434"),
        expected_revision=0,
    )
    first = service.save_model_entry(
        ModelEntryDraft(
            name="First",
            connection_id=connection["connection"]["id"],
            model_id="first",
            verified=True,
        ),
        expected_revision=1,
    )
    second = service.save_model_entry(
        ModelEntryDraft(
            name="Second",
            connection_id=connection["connection"]["id"],
            model_id="second",
            verified=True,
        ),
        expected_revision=2,
    )
    service.save_project_bindings(
        project_id="proj_one",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: first["model"]["id"]}),
        expected_revision=3,
    )
    service.save_project_bindings(
        project_id="proj_one",
        bindings=RoleBindings(roles={ModelRole.PRIMARY: second["model"]["id"]}),
        expected_revision=4,
    )

    bindings = service.get_project_bindings("proj_one")
    assert bindings.to_dict() == {"primary": second["model"]["id"]}
    assert len(service.get_redacted_registry()["project_bindings"]) == 1
