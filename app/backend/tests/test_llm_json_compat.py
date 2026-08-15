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


# ---------------------------------------------------------------------------
# graphiti_patch._extract_json_from_markdown 的 JSON 鲁棒化
# （单引号 dict、截断 JSON 收敛）
# ---------------------------------------------------------------------------
from app.services.graphiti_patch import _extract_json_from_markdown as _graphiti_json


def test_extract_json_single_quote_dict():
    assert _graphiti_json("{'a': 1, 'b': ['x', 'y']}") == {"a": 1, "b": ["x", "y"]}


def test_extract_json_single_quote_dict_with_chinese():
    assert _graphiti_json(
        "{'name': '李慕白', 'kind': '剑侠'}"
    ) == {"name": "李慕白", "kind": "剑侠"}


def test_extract_json_truncated_trailing_garbage_converges():
    # 截断：有效 JSON + 尾部残缺杂文，应收敛到最长可解析前缀
    assert _graphiti_json('{"a": 1} 截断的后半段……') == {"a": 1}


def test_extract_json_truncated_unclosed_array_converges():
    # 截断：数组最后一个元素未闭合，收敛到较早的完整 JSON 对象
    assert _graphiti_json('[{"x": 1}, {"y"') == {"x": 1}


def test_extract_json_truncated_fenced_block_converges():
    # Markdown 围栏里被截断：收敛到围栏内完整可解析的对象
    assert _graphiti_json('[{"x": 1}, {"y"' ) == {"x": 1}


def test_extract_json_still_rejects_invalid_text():
    # 纯文本（无数值载体）仍应失败
    assert _graphiti_json("这不是 JSON，也没有代码块") is None


# ---------------------------------------------------------------------------
# 响应模型规范化（裸 dict 包装 / 校验失败重试）
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field
from app.services.graphiti_patch import (
    _normalize_structured_response,
    _normalize_and_validate,
)


class _Item(BaseModel):
    id: int = Field(...)
    name: str = Field(...)
    duplicate_idx: int = Field(...)
    duplicates: list = Field(default_factory=list)


class _ListResponse(BaseModel):
    entity_resolutions: list[_Item] = Field(...)


def test_normalize_bare_list_wraps():
    """裸数组 → {单列表字段: 数组}"""
    result = _normalize_structured_response(
        [{"id": 0, "name": "a", "duplicate_idx": -1, "duplicates": []}],
        _ListResponse,
    )
    assert result == {
        "entity_resolutions": [{"id": 0, "name": "a", "duplicate_idx": -1, "duplicates": []}]
    }


def test_normalize_bare_dict_wraps_single_item():
    """单条记录的裸 dict → {单列表字段: [该 dict]}（OpenCode 消歧阶段偶发）"""
    result = _normalize_structured_response(
        {"id": 0, "name": "科技都市", "duplicate_idx": -1, "duplicates": []},
        _ListResponse,
    )
    assert result == {
        "entity_resolutions": [{"id": 0, "name": "科技都市", "duplicate_idx": -1, "duplicates": []}]
    }


def test_normalize_already_wrapped_dict_unchanged():
    result = _normalize_structured_response(
        {"entity_resolutions": [{"id": 0, "name": "a", "duplicate_idx": -1}]},
        _ListResponse,
    )
    assert "entity_resolutions" in result


async def test_normalize_and_validate_retries_on_failure():
    """校验失败时重试一次 LLM 调用；重试成功返回合法结果。"""
    calls = {"n": 0}

    async def fake_llm_once():
        # 这里的 call_llm_once 代表“重试那一次新的 LLM 调用”，
        # 因此第一次被调用就应返回合法结构。
        calls["n"] += 1
        return '{"entity_resolutions": [{"id": 0, "name": "科技都市", "duplicate_idx": -1, "duplicates": []}]}'

    parsed = {"id": 0, "name": "科技都市", "duplicates": []}
    result = await _normalize_and_validate(parsed, _ListResponse, fake_llm_once)

    assert calls["n"] == 1
    assert result["entity_resolutions"][0]["duplicate_idx"] == -1


async def test_normalize_and_validate_passes_without_retry():
    calls = {"n": 0}

    async def fake_llm_once():
        calls["n"] += 1
        return "unused"

    parsed = {"entity_resolutions": [{"id": 0, "name": "a", "duplicate_idx": -1}]}
    result = await _normalize_and_validate(parsed, _ListResponse, fake_llm_once)

    assert calls["n"] == 0, "校验通过不应触发重试"
    assert result["entity_resolutions"][0]["name"] == "a"
