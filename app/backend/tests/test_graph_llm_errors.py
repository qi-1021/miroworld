"""图谱 API 中 LLM 错误信息的可读化测试。"""
import asyncio
import time
from types import SimpleNamespace
from unittest import mock

from pydantic import BaseModel, Field

from app.api.graph import _llm_error_message


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeAPIError(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.message = message
        self.response = response


def test_llm_error_message_extracts_provider_message():
    error = FakeAPIError(
        "Error code: 402",
        response=FakeResponse(
            {"error": {"message": "Insufficient Balance", "type": "unknown_error"}}
        ),
    )

    assert _llm_error_message(error) == "Insufficient Balance"


def test_llm_error_message_falls_back_to_exception_text():
    error = FakeAPIError("connection refused")

    assert _llm_error_message(error) == "connection refused"


# ---------------------------------------------------------------------------
# Graphiti 边提取降级吞并测试：edge 提取失败时返回 {"edges": []}，构建继续
# ---------------------------------------------------------------------------
class _EdgesModel(BaseModel):
    """模拟 ExtractedEdges：含 edges 字段，_is_edge_extraction 应判定为 True。"""

    edges: list[dict] = Field(default_factory=list)


class _Handled_edges_model(BaseModel):
    """不含 edges 字段的模型，验证 _is_edge_extraction 判 False。"""

    summary: str = ""


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


def _completions_cls(content_fn):
    """构造可配置的 completions：content_fn(call_index) 决定第 n 次返回的分片。"""

    class FakeChatCompletions:
        def __init__(self):
            self.call_count = 0

        async def create(self, **kwargs):
            i = self.call_count
            self.call_count += 1
            content = content_fn(i)
            if content is None:
                # 模拟空响应：choices 非空但 message.content 为空串
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    return FakeChatCompletions


def _edge_client(content_fn):
    completions = _completions_cls(content_fn)()
    raw_openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = SimpleNamespace(
        client=raw_openai,  # self.client = 底层 openai 客户端（graphiti 客户端结构）
        model="gpt-4.1-mini",
        temperature=0.0,
        max_tokens=4096,
    )
    client._clean_input = staticmethod(lambda s: s)
    return client


def _run_generate(client, response_model):
    """应用到 OpenAIGenericClient 后的 patched_generate（通过 patch 后调用）。"""
    from app.services.graphiti_patch import _apply_response_normalization_patch

    assert _apply_response_normalization_patch() is True

    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

    messages = [_msg("system", "你是助手"), _msg("user", "提取边")]
    return asyncio.run(
        OpenAIGenericClient._generate_response(client, messages, response_model=response_model)
    )


def test_edge_empty_response_degrades_to_empty_edges():
    """edge 提取连续空响应 → 返回 {'edges': []}，不抛异常。"""
    client = _edge_client(lambda i: None)  # 每次都空
    with mock.patch("time.sleep"):
        result = _run_generate(client, _EdgesModel())
    assert result == {"edges": []}


def test_edge_unparseable_text_degrades_to_empty_edges():
    """edge 提取返回无法解析的纯文本 → 返回 {'edges': []}。"""
    # 空一次（进入重试），随后返回无法解析的文本 → 降级
    client = _edge_client(lambda i: None if i == 0 else "这不是 JSON 文本")
    with mock.patch("time.sleep"):
        result = _run_generate(client, _EdgesModel())
    assert result == {"edges": []}


def test_edge_connection_error_degrades_to_empty_edges():
    """edge 提取连续连接错误 → 返回 {'edges': []}，构建继续。"""

    async def boom(i):
        raise ConnectionError("connection refused")

    completions = SimpleNamespace(create=boom)
    raw_openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = SimpleNamespace(
        client=raw_openai,
        model="gpt-4.1-mini",
        temperature=0.0,
        max_tokens=4096,
    )
    client._clean_input = staticmethod(lambda s: s)
    with mock.patch("time.sleep"):
        result = _run_generate(client, _EdgesModel())
    assert result == {"edges": []}


def test_non_edge_empty_response_returns_empty_dict():
    """非 edge 提取空响应 → 返回 {}（不改写为 edges）。"""
    client = _edge_client(lambda i: None)
    with mock.patch("time.sleep"):
        result = _run_generate(client, _Handled_edges_model())
    assert result == {}
