"""LLM JSON 响应兼容解析测试。"""
import json
from types import SimpleNamespace

import pytest
from openai import BadRequestError

from app.utils.llm_client import LLMClient


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"ok": true}', {"ok": True}),
        ('```json\n{"ok": true}\n```', {"ok": True}),
        ('```\n{"ok": true}\n```', {"ok": True}),
        ('以下是结果：\n```json\n{"ok": true}\n```\n完', {"ok": True}),
        ('前文说明 {"ok": true} 后文说明', {"ok": True}),
    ],
)
def test_parse_json_response_accepts_common_formats(raw, expected):
    assert LLMClient._parse_json_response(raw) == expected


def test_parse_json_response_rejects_invalid_text():
    with pytest.raises(ValueError, match="不是有效 JSON"):
        LLMClient._parse_json_response("这不是 JSON")


class FakeCompletions:
    """按顺序返回预置内容；None 表示空响应（choices 为空）。"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        content = self._contents.pop(0) if self._contents else None
        if content is None:
            return SimpleNamespace(choices=[])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def _make_client(contents, max_empty_retries=2, disable_thinking=True):
    client = LLMClient(
        api_key="test",
        base_url="http://localhost:1",
        max_empty_retries=max_empty_retries,
        disable_thinking=disable_thinking,
    )
    fake = FakeCompletions(contents)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return client, fake


def test_chat_retries_empty_response_and_succeeds():
    client, fake = _make_client([None, '{"ok": true}'])
    assert client.chat(messages=[{"role": "user", "content": "hi"}]) == '{"ok": true}'
    assert fake.call_count == 2


def test_chat_retries_when_choices_empty():
    client, fake = _make_client([None, None, "ok"])
    assert client.chat(messages=[{"role": "user", "content": "hi"}]) == "ok"
    assert fake.call_count == 3


def test_chat_sends_thinking_disabled_by_default():
    client, fake = _make_client(["ok"])
    client.chat(messages=[{"role": "user", "content": "hi"}])
    assert fake.last_kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


def test_chat_omits_thinking_when_disabled_flag_false():
    client, fake = _make_client(["ok"], disable_thinking=False)
    client.chat(messages=[{"role": "user", "content": "hi"}])
    assert "extra_body" not in fake.last_kwargs


def _bad_request_error():
    response = SimpleNamespace(
        status_code=400,
        headers={},
        request=SimpleNamespace(),
        text='{"error": {"message": "thinking not supported"}}',
    )
    return BadRequestError(
        "Error code: 400",
        response=response,
        body={"error": {"message": "thinking not supported"}},
    )


def test_chat_falls_back_when_gateway_rejects_thinking_param():
    class RejectingCompletions(FakeCompletions):
        def create(self, **kwargs):
            self.call_count += 1
            self.last_kwargs = kwargs
            if kwargs.get("extra_body"):
                raise _bad_request_error()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    fake = RejectingCompletions([])
    client = LLMClient(api_key="test", base_url="http://localhost:1")
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    assert client.chat(messages=[{"role": "user", "content": "hi"}]) == "ok"
    assert fake.call_count == 2
    assert "extra_body" not in fake.last_kwargs


def test_chat_json_raises_readable_error_when_all_retries_empty():
    client, fake = _make_client([None, None, None])
    with pytest.raises(ValueError, match="空响应"):
        client.chat_json(messages=[{"role": "user", "content": "hi"}])
    # json 模式 3 次尝试 + 兜底 3 次尝试
    assert fake.call_count == 6


def test_chat_json_succeeds_after_empty_retry():
    client, fake = _make_client([None, '```json\n{"ok": true}\n```'])
    assert client.chat_json(messages=[{"role": "user", "content": "hi"}]) == {"ok": True}
    assert fake.call_count == 2


def test_chat_json_falls_back_to_non_json_mode_after_all_empty():
    # 第一次调用（json 模式）内部 3 次尝试全空，第二次兜底（无 json 模式）成功
    client, fake = _make_client([None, None, None, '{"ok": true}'])
    assert client.chat_json(messages=[{"role": "user", "content": "hi"}]) == {"ok": True}
    assert fake.call_count == 4


def test_chat_json_falls_back_when_json_mode_returns_non_json_text():
    # json 模式返回了非 JSON 文本，兜底调用返回有效 JSON
    client, fake = _make_client(["这不是 JSON", '{"ok": true}'])
    assert client.chat_json(messages=[{"role": "user", "content": "hi"}]) == {"ok": True}
    assert fake.call_count == 2
