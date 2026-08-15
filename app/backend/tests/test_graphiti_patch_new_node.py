"""
测试 graphiti_patch 的"新节点优先"属性/摘要提取 patch。

背景：graphiti 每个 episode 会对本次提取出的所有节点重新跑属性+摘要
（每节点 1-2 次 LLM 调用）。长文档建图时同一批实体反复出现，造成大量
重复调用。patch 注入默认 should_summarize_node 过滤：已有摘要的节点跳过。

本测试用假的原始实现替换后再打 patch，验证默认过滤逻辑：
- 新节点（无摘要）→ 处理
- 已有摘要的节点 → 跳过
"""

import asyncio


class _FakeNode:
    """模拟 graphiti EntityNode：只需 summary 字段参与过滤判断。"""

    def __init__(self, summary: str = ""):
        self.summary = summary


def test_new_node_only_summary_filter_applies():
    """apply 后，extract_attributes_from_nodes 默认只处理尚无摘要的新节点。"""
    import graphiti_core.graphiti as g
    from graphiti_core.utils.maintenance import node_operations as no

    seen_filters = []

    async def fake_original(
        clients,
        nodes,
        episode=None,
        previous_episodes=None,
        entity_types=None,
        should_summarize_node=None,
    ):
        # 记录默认注入的过滤函数，并模拟"被过滤掉的节点不做 LLM 调用"
        seen_filters.append(should_summarize_node)
        if should_summarize_node is None:
            return list(nodes)
        return [n for n in nodes if await should_summarize_node(n)]

    # 先替换两个命名空间为假实现，再应用 patch（patch 会包装当前引用）
    no.extract_attributes_from_nodes = fake_original
    g.extract_attributes_from_nodes = fake_original

    from app.services.graphiti_patch import _apply_new_node_only_attributes_patch

    assert _apply_new_node_only_attributes_patch() is True

    new_node = _FakeNode("")
    existing_node = _FakeNode("剑圣李慕白，已隐居十年……")

    results = asyncio.run(
        g.extract_attributes_from_nodes(None, [new_node, existing_node])
    )

    assert seen_filters, "应注入默认的 should_summarize_node 过滤"
    flt = seen_filters[-1]

    async def _check(node):
        return await flt(node)

    assert asyncio.run(_check(new_node)) is True, "新节点（无摘要）应被处理"
    assert asyncio.run(_check(existing_node)) is False, "已有摘要的节点应被跳过"
    assert results == [new_node], "只有新节点应触发属性/摘要提取"


def test_explicit_filter_overrides_default():
    """调用方显式传入 should_summarize_node 时，应优先使用显式过滤。"""
    import graphiti_core.graphiti as g
    from graphiti_core.utils.maintenance import node_operations as no

    seen_filters = []

    async def fake_original(
        clients,
        nodes,
        episode=None,
        previous_episodes=None,
        entity_types=None,
        should_summarize_node=None,
    ):
        seen_filters.append(should_summarize_node)
        if should_summarize_node is None:
            return list(nodes)
        return [n for n in nodes if await should_summarize_node(n)]

    no.extract_attributes_from_nodes = fake_original
    g.extract_attributes_from_nodes = fake_original

    from app.services.graphiti_patch import _apply_new_node_only_attributes_patch

    _apply_new_node_only_attributes_patch()

    # graphiti 用 `await filter(node)` 调用过滤函数，显式过滤必须是 async
    async def always_false(node):
        return False

    node = _FakeNode("")
    results = asyncio.run(
        g.extract_attributes_from_nodes(None, [node], should_summarize_node=always_false)
    )

    assert seen_filters[-1] is always_false, "显式过滤应覆盖默认的新节点过滤"
    assert results == [], "显式过滤为 False 时节点应被跳过"