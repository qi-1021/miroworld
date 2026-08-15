from dataclasses import dataclass

import pytest

from app.models.model_config import ConnectionDraft
from app.services.model_detection import (
    DetectionRequestError,
    HttpResponse,
    ModelConnectionDetector,
    UnsafeEndpointError,
    normalize_endpoint,
)


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict
    body: dict | None


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, *, headers, json_body=None, timeout=10.0):
        self.requests.append(RecordedRequest(method, url, headers, json_body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def public_resolver(hostname):
    return ["93.184.216.34"]


def private_resolver(hostname):
    return ["10.2.3.4"]


def test_normalize_full_openai_chat_url_to_base_url():
    normalized = normalize_endpoint(
        " https://api.openai.com/v1/chat/completions/ "
    )

    assert normalized.provider_id == "openai"
    assert normalized.base_url == "https://api.openai.com/v1"
    assert normalized.chat_url == "https://api.openai.com/v1/chat/completions"
    assert normalized.models_url == "https://api.openai.com/v1/models"


def test_deepseek_root_endpoint_gets_compatible_v1_paths():
    normalized = normalize_endpoint("https://api.deepseek.com")

    assert normalized.provider_id == "deepseek"
    assert normalized.base_url == "https://api.deepseek.com/v1"
    assert normalized.chat_url.endswith("/v1/chat/completions")


def test_ollama_uses_native_model_discovery_and_openai_chat():
    normalized = normalize_endpoint("http://localhost:11434")

    assert normalized.provider_id == "ollama"
    assert normalized.models_url == "http://localhost:11434/api/tags"
    assert normalized.chat_url == "http://localhost:11434/v1/chat/completions"
    assert normalized.embedding_url == "http://localhost:11434/v1/embeddings"


def test_detector_discovers_and_verifies_chat_models():
    transport = FakeTransport(
        [
            HttpResponse(200, {"data": [{"id": "alpha-chat"}, {"id": "beta-chat"}]}),
            HttpResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            HttpResponse(200, {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}),
        ]
    )
    detector = ModelConnectionDetector(transport=transport, resolver=public_resolver)

    result = detector.detect(
        ConnectionDraft(
            name="Test API",
            endpoint="https://models.example.com/v1",
            api_key="secret-token",
        )
    )

    assert result.usable is True
    assert result.models == ["alpha-chat", "beta-chat"]
    assert result.capabilities["models"]["status"] == "available"
    assert result.capabilities["chat"]["status"] == "available"
    assert result.capabilities["embedding"]["status"] == "available"
    assert result.capabilities["embedding"]["dimension"] == 4
    assert transport.requests[0].url == "https://models.example.com/v1/models"
    assert transport.requests[1].body["model"] == "alpha-chat"
    assert transport.requests[2].url.endswith("/embeddings")
    assert transport.requests[0].headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in str(result.to_dict())


def test_ollama_discovery_accepts_native_tags_response_without_api_key():
    transport = FakeTransport(
        [
            HttpResponse(200, {"models": [{"name": "qwen3:8b"}]}),
            HttpResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            HttpResponse(200, {"data": [{"embedding": [0.1, 0.2, 0.3]}]}),
        ]
    )
    detector = ModelConnectionDetector(transport=transport)

    result = detector.detect(
        ConnectionDraft(name="Ollama", endpoint="http://localhost:11434")
    )

    assert result.provider_id == "ollama"
    assert result.models == ["qwen3:8b"]
    assert result.capabilities["embedding"]["status"] == "available"
    assert "Authorization" not in transport.requests[0].headers


def test_private_network_requires_explicit_permission():
    detector = ModelConnectionDetector(
        transport=FakeTransport([]), resolver=private_resolver
    )

    with pytest.raises(UnsafeEndpointError, match="私有/保留地址"):
        detector.detect(
            ConnectionDraft(name="Private", endpoint="http://models.internal:8000/v1")
        )


def test_private_network_can_be_enabled_for_local_deployment():
    transport = FakeTransport(
        [
            HttpResponse(200, {"data": [{"id": "local-model"}]}),
            HttpResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
            HttpResponse(200, {"data": [{"embedding": [0.1]}]}),
        ]
    )
    detector = ModelConnectionDetector(transport=transport, resolver=private_resolver)

    result = detector.detect(
        ConnectionDraft(
            name="Private",
            endpoint="http://models.internal:8000/v1",
            options={"allow_private_network": True},
        )
    )

    assert result.usable is True


def test_transport_error_redacts_api_key():
    transport = FakeTransport(
        [DetectionRequestError("Authorization Bearer secret-token failed")]
    )
    detector = ModelConnectionDetector(transport=transport, resolver=public_resolver)

    result = detector.detect(
        ConnectionDraft(
            name="Broken",
            endpoint="https://models.example.com/v1",
            api_key="secret-token",
        )
    )

    assert result.usable is False
    assert result.manual_model_required is True
    assert "secret-token" not in result.errors[0]
    assert "[REDACTED]" in result.errors[0]
