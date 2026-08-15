"""
测试 graphiti_patch 的"新节点优先"属性/摘要提取 patch。

背景：graphiti 每个 episode 会对本次提取出的所有节点重新跑属性+摘要
（每节点 1-2 次 LLM 调用）。长文档建图时同一批实体反复出现，造成大量
重复调用。patch 注入默认 should_summarize_node 过滤：已有摘要的节点跳过。

本测试用假的原始实现替换后再打 patch，验证默认过滤逻辑：
- 新节点（无摘要）→ 处理
- 已有摘要的节点 → 跳过

同时也覆盖：
- edge-skip patch（首个 episode 跳过边提取）
"""

import asyncio
from types import SimpleNamespace

from app.config import Config


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


# ---------------------------------------------------------------------------
# edge-skip patch：首个 episode（group 尚无 EntityNode）时跳过边提取
# ---------------------------------------------------------------------------
class _CountDriver:
    """返回指定 EntityNode 数量；raise_on_query 时让 count 查询抛错。"""

    def __init__(self, count, raise_on_query=False):
        self._count = count
        self._raise = raise_on_query
        self.calls = 0

    async def execute_query(self, query, **kwargs):
        self.calls += 1
        if self._raise:
            raise RuntimeError("neo4j down")
        record = {"cnt": self._count}
        return [record], None, None


def _patch_edge_ops(orig_impl):
    """替换 edge_operations.extract_edges 为假实现后应用 patch，返回 (edge_ops_模块, 追踪)。"""
    from graphiti_core.utils.maintenance import edge_operations as eo
    from app.services.graphiti_patch import _apply_edge_skip_patch

    calls = {"orig": 0}

    async def fake_original(
        clients,
        episode,
        nodes,
        previous_episodes,
        edge_type_map,
        group_id="",
        edge_types=None,
        custom_extraction_instructions=None,
    ):
        calls["orig"] += 1
        return [SimpleNamespace(fake="edge")]

    eo.extract_edges = fake_original
    assert _apply_edge_skip_patch() is True
    return eo, calls


def test_edge_skip_when_group_has_no_nodes():
    """group_id 下 EntityNode 数量为 0 且 skip-first → 直接返回 []，不调原函数。"""
    from graphiti_core.utils.maintenance import edge_operations as eo

    prev_mode = Config.GRAPHITI_EDGE_MODE
    Config.GRAPHITI_EDGE_MODE = "skip-first"
    try:
        _, calls = _patch_edge_ops(None)
        clients = SimpleNamespace(driver=_CountDriver(0))
        result = asyncio.run(
            eo.extract_edges(clients, "ep", "nodes", "prev", {}, group_id="fresh")
        )
        assert result == [], "0 实体时应跳过边提取返回空列表"
        assert calls["orig"] == 0, "不应调用原始 extract_edges"
    finally:
        Config.GRAPHITI_EDGE_MODE = prev_mode


def test_edge_skip_query_failure_is_conservative():
    """count 查询失败时保守不跳过，走原始 extract_edges。"""
    from graphiti_core.utils.maintenance import edge_operations as eo

    prev_mode = Config.GRAPHITI_EDGE_MODE
    Config.GRAPHITI_EDGE_MODE = "skip-first"
    try:
        calls = _patch_edge_ops(None)[1]
        clients = SimpleNamespace(driver=_CountDriver(999, raise_on_query=True))
        result = asyncio.run(
            eo.extract_edges(clients, "ep", "nodes", "prev", {}, group_id="g")
        )
        assert result == [SimpleNamespace(fake="edge")] or len(result) > 0
        assert calls["orig"] == 1, "查询失败应保守调用原始 extract_edges"
    finally:
        Config.GRAPHITI_EDGE_MODE = prev_mode


def test_edge_skip_disabled_in_always_mode():
    """GRAPHITI_EDGE_MODE=always 时不跳过，即使 group 无节点也调原始函数。"""
    from graphiti_core.utils.maintenance import edge_operations as eo

    prev_mode = Config.GRAPHITI_EDGE_MODE
    Config.GRAPHITI_EDGE_MODE = "always"
    try:
        _, calls = _patch_edge_ops(None)
        clients = SimpleNamespace(driver=_CountDriver(0))
        result = asyncio.run(
            eo.extract_edges(clients, "ep", "nodes", "prev", {}, group_id="fresh")
        )
        assert calls["orig"] == 1, "always 模式应调用原始 extract_edges（不跳过）"
    finally:
        Config.GRAPHITI_EDGE_MODE = prev_mode


def test_edge_skip_continues_when_group_has_nodes():
    """group 已有 EntityNode 时跳过逻辑不触发（仍需 original 实际比对）。"""
    from graphiti_core.utils.maintenance import edge_operations as eo

    prev_mode = Config.GRAPHITI_EDGE_MODE
    Config.GRAPHITI_EDGE_MODE = "skip-first"
    try:
        _, calls = _patch_edge_ops(None)
        clients = SimpleNamespace(driver=_CountDriver(5))
        result = asyncio.run(
            eo.extract_edges(clients, "ep", "nodes", "prev", {}, group_id="existing")
        )
        assert calls["orig"] == 1, "已有节点时应走原始 extract_edges"
        assert result == [SimpleNamespace(fake="edge")]
    finally:
        Config.GRAPHITI_EDGE_MODE = prev_mode

def test_entity_extraction_retry_on_few_entities():
    """实体提取过少（<3）时自动重试一次；重试更多则采用重试结果。"""
    import graphiti_core.graphiti as g
    from graphiti_core.utils.maintenance import node_operations as no

    calls = {"n": 0}

    async def fake_extract(clients, episode, previous_episodes, entity_types=None,
                           excluded_entity_types=None, custom_extraction_instructions=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_FakeNode("敷衍提取")]  # 1 个 → 触发重试
        return [_FakeNode("苍澜界"), _FakeNode("北境霜国"), _FakeNode("龙脊城")]

    no.extract_nodes = fake_extract
    g.extract_nodes = fake_extract

    from app.services.graphiti_patch import _apply_entity_extraction_retry_patch
    assert _apply_entity_extraction_retry_patch() is True

    class _Ep:
        content = "大陆名唤苍澜界，由三大帝国鼎立：北境霜国以铁骑闻名，龙脊城是贸易重镇。" * 3

    results = asyncio.run(g.extract_nodes(None, _Ep(), []))
    assert calls["n"] == 2, "应重试一次"
    assert len(results) == 3, "应采用重试后的完整结果"


def test_entity_extraction_no_retry_when_enough():
    """实体数 >= 3 时不重试。"""
    import graphiti_core.graphiti as g
    from graphiti_core.utils.maintenance import node_operations as no

    calls = {"n": 0}

    async def fake_extract(clients, episode, previous_episodes, entity_types=None,
                           excluded_entity_types=None, custom_extraction_instructions=None):
        calls["n"] += 1
        return [_FakeNode("a"), _FakeNode("b"), _FakeNode("c"), _FakeNode("d")]

    no.extract_nodes = fake_extract
    g.extract_nodes = fake_extract

    from app.services.graphiti_patch import _apply_entity_extraction_retry_patch
    _apply_entity_extraction_retry_patch()

    class _Ep:
        content = "很长的一段文本" * 50

    results = asyncio.run(g.extract_nodes(None, _Ep(), []))
    assert calls["n"] == 1, "实体足够时不应重试"
    assert len(results) == 4


def test_edge_skip_patch_binds_graphiti_namespace():
    """edge-skip patch 必须同时替换 graphiti.py 模块命名空间的 extract_edges。

    回归：此前只替换 edge_operations.extract_edges，graphiti.py 在导入时
    已绑定原函数，线上 _extract_and_resolve_edges 仍走原版边提取，
    skip-first 形同虚设（实测每次烧 2×119s）。
    """
    import graphiti_core.graphiti as g
    from app.services.graphiti_patch import apply_patch
    apply_patch()
    src = g.extract_edges.__code__.co_filename
    assert "graphiti_patch" in src, f"graphiti.extract_edges 未指向 patch 版本: {src}"


def test_compact_extraction_prompt_via_wrapper():
    """精简提取提示词必须通过 prompt_library 包装器路径生效（回归）。

    此前补丁只替换了 extract_nodes 模块的函数，而 node_operations 实际
    走 prompt_library.extract_nodes.extract_text（VersionWrapper 捕获了
    原函数），导致线上提取提示词仍为 3872 字符、网关 120s+ 慢调用。
    """
    from app.services.graphiti_patch import apply_patch
    apply_patch()
    from graphiti_core.prompts import prompt_library

    content = "大陆名唤苍澜界，由三大帝国鼎立。" * 60
    ctx = {
        "entity_types": '[{"entity_type_id": 0, "entity_type_name": "Entity"}]',
        "episode_content": content,
        "custom_extraction_instructions": "",
    }
    msgs = prompt_library.extract_nodes.extract_text(ctx)
    total = len(msgs[0].content) + len(msgs[1].content)
    assert total < 2500, f"提示词未精简: {total}"
