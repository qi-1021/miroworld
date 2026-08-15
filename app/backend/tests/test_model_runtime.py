"""model_runtime：项目角色绑定 → 运行时可执行凭据的测试。"""

from app.models.model_config import ModelRole
from app.services import model_runtime


class _Chat:
    def __init__(self, role, api_key, endpoint, model_id):
        self.role = role
        self.api_key = api_key
        self.endpoint = endpoint
        self.model_id = model_id


def _primary():
    return _Chat(ModelRole.PRIMARY, "sk-p", "https://primary.example/v1", "primary-model")


def _boost():
    return _Chat(
        ModelRole.SIMULATION_BOOST,
        "sk-b",
        "https://boost.example/v1",
        "boost-model",
    )


def test_resolve_project_chat_none_when_no_binding(monkeypatch):
    monkeypatch.setattr(
        model_runtime, "_load_project_snapshot",
        lambda project_id: (object(), None, {}),
    )
    assert model_runtime.resolve_project_chat("proj_x") is None


def test_resolve_project_chat_skips_unbound_role(monkeypatch):
    snapshot = {"id": "snap1", "bindings": {ModelRole.PRIMARY.value: "m1"}}
    monkeypatch.setattr(
        model_runtime, "_load_project_snapshot",
        lambda project_id: (object(), snapshot, {ModelRole.PRIMARY.value: "m1"}),
    )
    # simulation 未显式绑定 → 不做隐式回退
    assert model_runtime.resolve_project_chat("proj_x", ModelRole.SIMULATION) is None


def test_resolve_project_chat_env_primary_only(monkeypatch):
    class Resolver:
        def __init__(self, registry):
            self.registry = registry

        def resolve_chat(self, role, snapshot_id):
            return _primary()

    registry = object()
    snapshot = {"id": "snap1"}
    roles = {ModelRole.PRIMARY.value: "m1"}
    monkeypatch.setattr(
        model_runtime, "_load_project_snapshot",
        lambda project_id: (registry, snapshot, roles),
    )
    monkeypatch.setattr(model_runtime.ModelResolver, "__init__", lambda self, registry: None)
    monkeypatch.setattr(model_runtime.ModelResolver, "resolve_chat",
                        lambda self, role, snapshot_id: _primary())

    env = model_runtime.resolve_project_chat_env("proj_123")
    assert env["LLM_API_KEY"] == "sk-p"
    assert env["LLM_BASE_URL"] == "https://primary.example/v1"
    assert env["LLM_MODEL_NAME"] == "primary-model"
    assert "LLM_BOOST_MODEL_NAME" not in env


def test_resolve_project_chat_env_includes_explicit_boost(monkeypatch):
    def fake_resolve(self, role, snapshot_id):
        if role == ModelRole.PRIMARY:
            return _primary()
        if role == ModelRole.SIMULATION_BOOST:
            return _boost()
        raise AssertionError(role)

    registry = object()
    snapshot = {"id": "snap1"}
    roles = {
        ModelRole.PRIMARY.value: "m1",
        ModelRole.SIMULATION_BOOST.value: "m2",
    }
    monkeypatch.setattr(
        model_runtime, "_load_project_snapshot",
        lambda project_id: (registry, snapshot, roles),
    )
    monkeypatch.setattr(model_runtime.ModelResolver, "__init__", lambda self, registry: None)
    monkeypatch.setattr(model_runtime.ModelResolver, "resolve_chat", fake_resolve)

    env = model_runtime.resolve_project_chat_env("proj_123")
    assert env["LLM_BOOST_MODEL_NAME"] == "boost-model"
    assert env["LLM_BOOST_BASE_URL"] == "https://boost.example/v1"


def test_resolve_project_chat_env_falls_back_to_simulation_role(monkeypatch):
    sim = _Chat(ModelRole.SIMULATION, "sk-s", "https://sim.example/v1", "sim-model")

    def fake_resolve(self, role, snapshot_id):
        if role == ModelRole.PRIMARY:
            return _primary()
        if role == ModelRole.SIMULATION:
            return sim
        raise AssertionError(role)

    registry = object()
    snapshot = {"id": "snap1"}
    roles = {
        ModelRole.PRIMARY.value: "m1",
        ModelRole.SIMULATION.value: "m3",
    }
    monkeypatch.setattr(
        model_runtime, "_load_project_snapshot",
        lambda project_id: (registry, snapshot, roles),
    )
    monkeypatch.setattr(model_runtime.ModelResolver, "__init__", lambda self, registry: None)
    monkeypatch.setattr(model_runtime.ModelResolver, "resolve_chat", fake_resolve)

    env = model_runtime.resolve_project_chat_env("proj_123")
    assert env["LLM_BOOST_MODEL_NAME"] == "sim-model"
