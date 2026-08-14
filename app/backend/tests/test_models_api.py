import json
from types import SimpleNamespace

import openai
import pytest

from app import create_app
from app.api import models as models_api
from app.services.model_detection import DetectionResult
from app.services.model_registry import ModelRegistryService


@pytest.fixture
def client(tmp_path, monkeypatch):
    registry = ModelRegistryService(tmp_path / "model-config")
    monkeypatch.setattr(models_api, "registry_service", registry)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), registry


def fake_detection():
    return DetectionResult(
        provider_id="custom",
        provider_name="自定义 OpenAI-compatible",
        normalized_endpoint="https://models.example.com/v1",
        capability_urls={
            "models": "https://models.example.com/v1/models",
            "chat": "https://models.example.com/v1/chat/completions",
            "embedding": "https://models.example.com/v1/embeddings",
        },
        capabilities={
            "models": {"status": "available"},
            "chat": {"status": "available"},
        },
        models=["alpha-chat"],
        usable=True,
        manual_model_required=False,
    )


def test_detection_draft_is_not_persisted(client, monkeypatch):
    http, registry = client
    monkeypatch.setattr(models_api, "detect_connection", lambda draft: fake_detection())

    response = http.post(
        "/api/models/connections/detect",
        json={
            "name": "Test",
            "endpoint": "https://models.example.com/v1",
            "api_key": "top-secret",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["models"] == ["alpha-chat"]
    assert "top-secret" not in json.dumps(payload)
    assert registry.get_redacted_registry()["revision"] == 0


def test_save_connection_returns_masked_secret(client):
    http, _ = client

    response = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "Cloud",
            "endpoint": "https://models.example.com/v1",
            "api_key": "top-secret",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["data"]["connection"]["has_secret"] is True
    assert payload["data"]["connection"]["secret_suffix"] == "cret"
    assert "top-secret" not in json.dumps(payload)


def test_stale_revision_returns_conflict_with_current_registry(client):
    http, _ = client
    first = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "First",
            "endpoint": "http://localhost:11434",
        },
    )
    assert first.status_code == 201

    stale = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "Stale",
            "endpoint": "https://models.example.com/v1",
        },
    )

    assert stale.status_code == 409
    payload = stale.get_json()
    assert payload["error"]["code"] == "REGISTRY_CONFLICT"
    assert payload["data"]["registry"]["revision"] == 1


def test_connection_models_and_project_bindings_flow(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(models_api, "detect_connection", lambda draft: fake_detection())
    saved_connection = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "Cloud",
            "endpoint": "https://models.example.com/v1",
            "api_key": "top-secret",
        },
    ).get_json()["data"]
    connection_id = saved_connection["connection"]["id"]

    discovery = http.post(f"/api/models/connections/{connection_id}/discover")
    assert discovery.status_code == 200
    assert discovery.get_json()["data"]["models"] == ["alpha-chat"]

    model_response = http.post(
        "/api/models/entries",
        json={
            "revision": 1,
            "name": "Alpha Chat",
            "connection_id": connection_id,
            "model_id": "alpha-chat",
            "capabilities": ["chat"],
            "verified": True,
        },
    )
    assert model_response.status_code == 201
    model_id = model_response.get_json()["data"]["model"]["id"]

    binding = http.put(
        "/api/models/projects/proj_one/bindings",
        json={"revision": 2, "roles": {"primary": model_id}},
    )
    assert binding.status_code == 200

    snapshot = http.post(
        "/api/models/tasks/simulation/sim_one/snapshot",
        json={"revision": 3, "roles": {"primary": model_id}},
    )
    assert snapshot.status_code == 201
    assert snapshot.get_json()["data"]["snapshot"]["owner_id"] == "sim_one"


def test_invalid_body_returns_structured_validation_error(client):
    http, _ = client

    response = http.post(
        "/api/models/connections",
        data="not-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


class _FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
        )


def test_model_entry_test_marks_entry_verified(client, monkeypatch):
    http, registry = client

    saved = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "Cloud",
            "endpoint": "https://models.example.com/v1",
            "api_key": "top-secret",
        },
    ).get_json()["data"]
    connection_id = saved["connection"]["id"]

    model = http.post(
        "/api/models/entries",
        json={
            "revision": 1,
            "name": "Alpha Chat",
            "connection_id": connection_id,
            "model_id": "alpha-chat",
            "capabilities": ["chat"],
            "verified": False,
        },
    ).get_json()["data"]["model"]
    model_id = model["id"]

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: fake)

    response = http.post(f"/api/models/entries/{model_id}/test")
    assert response.status_code == 200
    assert response.get_json()["data"]["model"]["verified"] is True

    registry_state = registry.get_redacted_registry()
    entry = next(item for item in registry_state["models"] if item["id"] == model_id)
    assert entry["verified"] is True


def test_model_entry_test_fails_on_empty_response(client, monkeypatch):
    http, _ = client

    saved = http.post(
        "/api/models/connections",
        json={
            "revision": 0,
            "name": "Cloud",
            "endpoint": "https://models.example.com/v1",
            "api_key": "top-secret",
        },
    ).get_json()["data"]
    connection_id = saved["connection"]["id"]

    model = http.post(
        "/api/models/entries",
        json={
            "revision": 1,
            "name": "Alpha Chat",
            "connection_id": connection_id,
            "model_id": "alpha-chat",
            "capabilities": ["chat"],
            "verified": False,
        },
    ).get_json()["data"]["model"]
    model_id = model["id"]

    class _EmptyCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=_EmptyCompletions()))
    monkeypatch.setattr(openai, "OpenAI", lambda *args, **kwargs: fake)

    response = http.post(f"/api/models/entries/{model_id}/test")
    assert response.status_code == 400
    assert "空响应" in response.get_json()["error"]["message"]
