"""
t17 属性+摘要合并提取 patch 测试：

1. 合并成功：每节点 1 次调用，summary/attributes 正确写入，提示词紧凑（<4000）
2. 合并失败（重试 1 次仍失败）：回退原始两段式路径，行为不劣于现状
3. 无字段实体类型：只走原始摘要路径（不产生合并调用）
4. should_summarize_node=False：只走原始属性路径
5. 响应含 schema 外字段：只保留合法字段
"""

import asyncio
from types import SimpleNamespace
from unittest import mock

from pydantic import BaseModel, Field


class _EntityType(BaseModel):
    entity_name: str = Field('', description='实体全名')
    age: str = Field('', description='年龄')


class _NoFieldType(BaseModel):
    pass


def _node(name='阿米娅', labels=('人物', 'Entity')):
    return SimpleNamespace(
        name=name,
        labels=list(labels),
        attributes={},
        summary='',
        group_id='g1',
    )


class _FakeLLM:
    """记录 generate_response 调用；可按 response_model 分支返回。"""

    def __init__(self, merged_result=None, merged_exc=None, attr_result=None,
                 summary_result=None):
        self.calls = []          # (response_model, prompt_len)
        self.merged_result = merged_result
        self.merged_exc = merged_exc
        self.attr_result = attr_result or {}
        self.summary_result = summary_result or {'summary': 'S'}

    async def generate_response(self, messages, response_model=None, **kw):
        prompt_len = sum(len(m.content) for m in messages)
        self.calls.append((response_model, prompt_len))
        if response_model is None:
            if self.merged_exc is not None:
                raise self.merged_exc
            return self.merged_result
        if response_model is _EntityType:
            return self.attr_result
        return self.summary_result


def _apply():
    from app.services.graphiti_patch import apply_patch
    apply_patch()
    from graphiti_core.utils.maintenance import node_operations
    return node_operations.extract_attributes_from_node


def test_merged_single_call_success():
    fn = _apply()
    fake = _FakeLLM(merged_result={
        'summary': '罗德岛的年轻领袖。',
        'attributes': {'entity_name': '阿米娅', 'age': '14岁'},
    })
    node = _node()

    asyncio.run(fn(fake, node, episode=None, previous_episodes=None,
                   entity_type=_EntityType, should_summarize_node=None))

    assert len(fake.calls) == 1, f"合并路径应只有 1 次调用，实际 {len(fake.calls)}"
    assert fake.calls[0][0] is None, "合并调用应不带 response_model（手动校验）"
    assert fake.calls[0][1] < 4000, f"合并提示词应紧凑，实际 {fake.calls[0][1]} 字符"
    assert node.summary == '罗德岛的年轻领袖。'
    assert node.attributes == {'entity_name': '阿米娅', 'age': '14岁'}


def test_merged_failure_falls_back_to_original_two_calls():
    fn = _apply()
    fake = _FakeLLM(
        merged_exc=ConnectionError('gateway down'),
        attr_result={'entity_name': '阿米娅', 'age': '14岁'},
        summary_result={'summary': '旧路径摘要'},
    )
    node = _node()

    asyncio.run(fn(fake, node, episode=None, previous_episodes=None,
                   entity_type=_EntityType, should_summarize_node=None))

    # 2 次合并尝试 + 原始路径 2 次（属性 + 摘要）
    assert len(fake.calls) == 4, f"应 2 次合并尝试 + 2 次原始调用，实际 {len(fake.calls)}"
    assert fake.calls[0][0] is None and fake.calls[1][0] is None
    assert fake.calls[2][0] is _EntityType
    assert node.attributes == {'entity_name': '阿米娅', 'age': '14岁'}
    assert node.summary == '旧路径摘要'


def test_no_field_type_uses_original_summary_only():
    fn = _apply()
    fake = _FakeLLM(summary_result={'summary': '无字段实体'})
    node = _node()

    asyncio.run(fn(fake, node, episode=None, previous_episodes=None,
                   entity_type=_NoFieldType, should_summarize_node=None))

    assert len(fake.calls) == 1, "无字段类型应只做 1 次摘要调用"
    assert fake.calls[0][0] is not None, "不应走合并路径"


def test_should_summarize_false_uses_original_attributes_only():
    fn = _apply()
    fake = _FakeLLM(attr_result={'entity_name': '阿米娅', 'age': '14岁'})
    node = _node()

    async def _filter(n):
        return False

    asyncio.run(fn(fake, node, episode=None, previous_episodes=None,
                   entity_type=_EntityType, should_summarize_node=_filter))

    assert len(fake.calls) == 1, "跳过摘要时应只做 1 次属性调用"
    assert fake.calls[0][0] is _EntityType


def test_merged_drops_fields_outside_schema():
    fn = _apply()
    fake = _FakeLLM(merged_result={
        'summary': 'S',
        'attributes': {'entity_name': '阿米娅', 'age': '14岁', 'hack': '非法字段'},
    })
    node = _node()

    asyncio.run(fn(fake, node, episode=None, previous_episodes=None,
                   entity_type=_EntityType, should_summarize_node=None))

    assert 'hack' not in node.attributes, "schema 外字段应被丢弃"
    assert node.attributes == {'entity_name': '阿米娅', 'age': '14岁'}
