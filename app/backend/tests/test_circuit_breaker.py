"""
t9 模型回退链 + 断路器测试：

1. CircuitBreaker 状态机：连续失败达到阈值熔断；成功重置；窗口过期自动复位。
2. report_llm_failure / report_llm_success 与断路器联动。
3. iter_chat_model_candidates 回退顺序（GRAPHITI_LLM → PRIMARY → 第一个已验证 chat）。
4. pick_fallback_model 熔断时跳过当前模型选下一个。
5. 用 0 关闭断路器时不熔断。
"""
import time

import pytest


class _FakeRegistry:
    """让 ModelRegistryService 的调用走假数据。"""

    def __init__(self, models, bindings=None, presets=None):
        self._models = models
        self._bindings = bindings or []
        self._presets = presets or []

    def get_redacted_registry(self):
        return {
            "models": self._models,
            "project_bindings": self._bindings,
            "presets": self._presets,
        }

    def resolve_connection_secret(self, connection_id):
        return f"secret-{connection_id}"

    def get_connection(self, connection_id):
        return {"endpoint": f"http://{connection_id}.local"}


def _chat(model_id):
    return {
        "id": model_id,
        "model_id": model_id,
        "verified": True,
        "capabilities": ["chat"],
        "connection_id": "conn-" + model_id,
    }


# ---------------------------------------------------------------------------
# 断路器状态机
# ---------------------------------------------------------------------------
def test_breaker_opens_after_threshold(monkeypatch):
    from app.services.graphiti_patch import CircuitBreaker

    br = CircuitBreaker(threshold=3, seconds=120)
    assert br.enabled is True
    assert br.report_failure("m1") is False
    assert br.report_failure("m1") is False
    # 第 3 次恰好触发熔断
    assert br.report_failure("m1") is True
    assert br.is_open_for("m1") is True
    assert br.is_open_for("m2") is False


def test_breaker_resets_on_success(monkeypatch):
    from app.services.graphiti_patch import CircuitBreaker

    br = CircuitBreaker(threshold=3, seconds=120)
    br.report_failure("m1")
    br.report_failure("m1")
    br.report_success("m1")  # 重置计数
    assert br.report_failure("m1") is False  # 计数从 0 重新开始
    assert br.is_open_for("m1") is False


def test_breaker_success_on_breached_model_closes(monkeypatch):
    from app.services.graphiti_patch import CircuitBreaker

    br = CircuitBreaker(threshold=2, seconds=120)
    br.report_failure("m1")
    br.report_failure("m1")  # tripped
    assert br.is_open_for("m1") is True
    # 其它模型成功只清计数，不闭合窗口
    br.report_success("m2")
    assert br.is_open_for("m1") is True
    # 熔断中的模型本身成功 → 立即闭合
    br.report_success("m1")
    assert br.is_open_for("m1") is False


def test_breaker_window_expires(monkeypatch):
    from app.services.graphiti_patch import CircuitBreaker

    br = CircuitBreaker(threshold=2, seconds=1)
    br.report_failure("m1")
    br.report_failure("m1")  # tripped
    assert br.is_open_for("m1") is True
    # 等窗口过期
    with monkeypatch.context() as m:
        fake_now = {"t": time.time() + 5}
        # 直接推进 _open_until 不可靠，改用短窗口 sleep 验证自动复位
        time.sleep(1.2)
        assert br.breached_model() is None  # 窗口过期自动复位
        assert br.is_open_for("m1") is False


def test_breaker_disabled_when_threshold_zero():
    from app.services.graphiti_patch import CircuitBreaker

    br = CircuitBreaker(threshold=0, seconds=120)
    assert br.enabled is False
    assert br.report_failure("m1") is False
    assert br.is_open_for("m1") is False


# ---------------------------------------------------------------------------
# 回退链
# ---------------------------------------------------------------------------
def _patch_registry(monkeypatch, registry):
    import app.services.model_registry as mr
    monkeypatch.setattr(mr, "ModelRegistryService", lambda: registry)


def test_iter_candidates_order(monkeypatch):
    from app.services import graphiti_patch

    _patch_registry(monkeypatch, _FakeRegistry(
        models=[_chat("a"), _chat("b"), _chat("c")],
        bindings=[],
        presets=[
            {"roles": {"graphiti_llm": "a"}},
        ],
    ))
    cands = graphiti_patch.iter_chat_model_candidates()
    assert cands, "应解析出候选"
    assert cands[0][2] == "a", "GRAPHITI_LLM 绑定应排第一"


def test_iter_candidates_graphiti_primary_first_chat_order(monkeypatch):
    from app.services import graphiti_patch

    _patch_registry(monkeypatch, _FakeRegistry(
        models=[_chat("a"), _chat("b"), _chat("c")],
        bindings=[{"roles": {"graphiti_llm": "a", "primary": "b"}}],
        presets=[],
    ))
    cands = graphiti_patch.iter_chat_model_candidates()
    order = [c[2] for c in cands]
    assert order == ["a", "b"], "graphiti_llm→primary 去重后即为完整链（c 与二者同属已验证 chat，无需重复兜底）"


def test_iter_candidates_first_chat_fallback_when_bindings_invalid(monkeypatch):
    """绑定指向模型 id 但非已验证 chat 时，应落到第一个已验证 chat 兜底。"""
    from app.services import graphiti_patch

    _patch_registry(monkeypatch, _FakeRegistry(
        models=[_chat("a")],  # 只有 a 是已验证 chat
        bindings=[{"roles": {"graphiti_llm": "zzz", "primary": "yyy"}}],  # 绑定的模型不存在
        presets=[],
    ))
    cands = graphiti_patch.iter_chat_model_candidates()
    order = [c[2] for c in cands]
    assert order == ["a"], "绑定模型无效时应兜底到第一个已验证 chat 模型 a"


def test_pick_fallback_skips_breached(monkeypatch):
    from app.services import graphiti_patch

    _patch_registry(monkeypatch, _FakeRegistry(
        models=[_chat("a"), _chat("b")],
        bindings=[{"roles": {"graphiti_llm": "a", "primary": "b"}}],
        presets=[],
    ))
    br = graphiti_patch.CircuitBreaker(threshold=1, seconds=120)
    # 熔断首选 a
    br.report_failure("a")
    monkeypatch.setattr(graphiti_patch, "_circuit_breaker", br)
    picked = graphiti_patch.pick_fallback_model()
    assert picked is not None and picked[2] == "b", "应跳过熔断的 a，选中 PRIMARY b"


def test_pick_fallback_returns_first_when_none_breached(monkeypatch):
    from app.services import graphiti_patch

    _patch_registry(monkeypatch, _FakeRegistry(
        models=[_chat("a"), _chat("b")],
        bindings=[{"roles": {"graphiti_llm": "a", "primary": "b"}}],
        presets=[],
    ))
    br = graphiti_patch.CircuitBreaker(threshold=1, seconds=120)
    monkeypatch.setattr(graphiti_patch, "_circuit_breaker", br)
    picked = graphiti_patch.pick_fallback_model()
    assert picked is not None and picked[2] == "a", "未熔断时应返回首选 a"


def test_report_helpers_trip_breaker(monkeypatch):
    from app.services import graphiti_patch

    br = graphiti_patch.CircuitBreaker(threshold=3, seconds=120)
    monkeypatch.setattr(graphiti_patch, "_circuit_breaker", br)
    tripped = [
        graphiti_patch.report_llm_failure("m")
        for _ in range(3)
    ]
    assert tripped == [False, False, True]
    graphiti_patch.report_llm_success("m")
    graphiti_patch.reset_circuit_breaker()
    assert graphiti_patch.get_circuit_breaker().is_open_for("m") is False
