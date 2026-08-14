from pathlib import Path

from app.models.model_config import (
    ConnectionDraft,
    ModelEntryDraft,
    ModelRole,
    RoleBindings,
)
from app.services.model_migration import import_legacy_env_once
from app.services.model_registry import ModelRegistryService
from app.services.model_resolver import ModelResolver


def configured_registry(tmp_path: Path):
    service = ModelRegistryService(tmp_path / "model-config")
    connection = service.save_connection(
        ConnectionDraft(
            name="Cloud",
            endpoint="https://models.example.com/v1",
            api_key="first-key",
        ),
        expected_revision=0,
    )
    model = service.save_model_entry(
        ModelEntryDraft(
            name="Primary",
            connection_id=connection["connection"]["id"],
            model_id="alpha-chat",
            capabilities=["chat", "json"],
            verified=True,
            metadata={"context_length": 32768},
        ),
        expected_revision=1,
    )
    snapshot = service.create_snapshot(
        owner_type="simulation",
        owner_id="sim_one",
        bindings=RoleBindings(
            roles={ModelRole.PRIMARY: model["model"]["id"]}
        ),
        expected_revision=2,
    )
    return service, connection, model, snapshot


def test_resolver_builds_chat_config_from_snapshot(tmp_path):
    service, _, _, snapshot = configured_registry(tmp_path)
    resolver = ModelResolver(service)

    config = resolver.resolve_chat(ModelRole.PRIMARY, snapshot["id"])

    assert config.endpoint == "https://models.example.com/v1"
    assert config.model_id == "alpha-chat"
    assert config.api_key == "first-key"
    assert config.capabilities == ("chat", "json")
    assert config.context_length == 32768


def test_primary_binding_is_inherited_by_simulation_and_graphiti(tmp_path):
    service, _, _, snapshot = configured_registry(tmp_path)
    resolver = ModelResolver(service)

    simulation = resolver.resolve_chat(ModelRole.SIMULATION, snapshot["id"])
    boost = resolver.resolve_chat(ModelRole.SIMULATION_BOOST, snapshot["id"])
    graphiti = resolver.resolve_chat(ModelRole.GRAPHITI_LLM, snapshot["id"])

    assert simulation.model_id == "alpha-chat"
    assert boost.model_id == "alpha-chat"
    assert graphiti.model_id == "alpha-chat"


def test_existing_snapshot_keeps_key_after_connection_rotation(tmp_path):
    service, connection, _, snapshot = configured_registry(tmp_path)
    connection_id = connection["connection"]["id"]
    service.save_connection(
        ConnectionDraft(
            name="Cloud",
            endpoint="https://models.example.com/v1",
            api_key="rotated-key",
        ),
        connection_id=connection_id,
        secret_action="replace",
        expected_revision=3,
    )

    resolved = ModelResolver(service).resolve_chat(ModelRole.PRIMARY, snapshot["id"])

    assert resolved.api_key == "first-key"
    assert service.resolve_connection_secret(connection_id) == "rotated-key"


def test_legacy_env_import_is_idempotent_and_does_not_mutate_input(tmp_path):
    service = ModelRegistryService(tmp_path / "model-config")
    environ = {
        "LLM_API_KEY": "legacy-key",
        "LLM_BASE_URL": "https://legacy.example.com/v1",
        "LLM_MODEL_NAME": "legacy-chat",
        "GRAPHITI_LLM_MODEL": "graph-chat",
        "EMBEDDING_API_KEY": "embedding-key",
        "EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
        "EMBEDDING_MODEL": "legacy-embedding",
        "EMBEDDING_DIM": "768",
    }
    original = dict(environ)

    first = import_legacy_env_once(service, environ=environ)
    second = import_legacy_env_once(service, environ=environ)
    registry = service.get_redacted_registry()

    assert first.imported is True
    assert second.imported is False
    assert environ == original
    assert len(registry["connections"]) == 2
    assert {item["model_id"] for item in registry["models"]} == {
        "legacy-chat",
        "graph-chat",
        "legacy-embedding",
    }
    preset = registry["presets"][0]
    assert preset["id"] == "legacy-import"
    assert preset["roles"]["primary"]
    assert preset["roles"]["graphiti_embedding"]
    embedding = next(
        item for item in registry["models"] if item["model_id"] == "legacy-embedding"
    )
    assert embedding["metadata"]["dimension"] == 768
