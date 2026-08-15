"""
Graphiti-core Monkey Patch

Workaround for graphiti-core Issue #683:
LLM 生成的嵌套属性会导致 Neo4j 写入失败
(Neo4j property values only accept primitive types or arrays thereof)

Patch 策略：
- 拦截 bulk_utils.add_nodes_and_edges_bulk_tx
- 在写入 Neo4j 前将嵌套 dict/list 转为 JSON 字符串
"""

import json
import functools
from typing import Any, Dict

from ..utils.logger import get_logger

logger = get_logger('mirofish.graphiti_patch')

_patch_applied = False


def sanitize_for_neo4j(value: Any, path: str = "") -> Any:
    """
    递归 sanitize 值以适配 Neo4j 属性限制

    Neo4j 只接受:
    - 原始类型: str, int, float, bool, None
    - 原始类型的数组 (不能嵌套)

    策略:
    - 嵌套 dict → JSON 字符串
    - 嵌套 list (包含 dict) → JSON 字符串
    - 简单 list (只有原始类型) → 保持不变
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        # dict 需要序列化为 JSON 字符串
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"无法序列化 dict 属性 {path}: {e}")
            return str(value)

    if isinstance(value, (list, tuple)):
        # 检查是否是简单数组 (只有原始类型)
        is_simple = all(isinstance(v, (str, int, float, bool, type(None))) for v in value)
        if is_simple:
            return list(value)
        # 包含复杂类型，序列化为 JSON
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"无法序列化 list 属性 {path}: {e}")
            return str(value)

    # 其他类型转字符串
    return str(value)


def sanitize_attributes(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize 整个 attributes 字典
    """
    if not attrs:
        return {}

    sanitized = {}
    for key, value in attrs.items():
        sanitized[key] = sanitize_for_neo4j(value, path=key)
    return sanitized


def _normalize_structured_response(result: Any, response_model: Any) -> Any:
    """
    把裸数组等"形状不符"的 LLM 响应规范化为 response_model 期望的 dict。

    本地分支为兼容部分网关（如 OpenCode）禁用了严格 JSON Schema 模式，
    模型可能把 {"entity_resolutions": [...]} 直接输出成 [...]。
    这里在 response_model 有且仅有一个 list 字段时自动包装。
    """
    if response_model is None or not isinstance(result, list):
        return result
    try:
        list_fields = [
            name
            for name, field in response_model.model_fields.items()
            if "list" in str(field.annotation).lower()
        ]
    except Exception:
        return result
    if len(list_fields) == 1:
        return {list_fields[0]: result}
    return result


def _wrap_plain_text_as_response(result: str, response_model: Any) -> Any:
    """
    当 LLM 返回纯文本而非 JSON 时，若 response_model 只有一个 str 字段
    （如 EntitySummary.summary、ExtractedEntity 等单字段模型），
    直接把文本包装成 {field: text}。

    原因：graphiti 的 extract_summary 等提示词不含 JSON 格式说明，
    且其 _generate_response 的 response_format 被注释掉，
    兼容网关（OpenCode/DeepSeek）会直接返回纯文本摘要。
    """
    if response_model is None:
        return None
    try:
        str_fields = [
            name
            for name, field in response_model.model_fields.items()
            if "str" in str(field.annotation).lower() and "list" not in str(field.annotation).lower()
        ]
    except Exception:
        return None
    # 恰好一个字符串字段 → 纯文本就是它的值
    if len(str_fields) == 1 and result.strip():
        return {str_fields[0]: result.strip()}
    return None


def _is_edge_extraction(response_model: Any) -> bool:
    """判断响应模型是否为"边提取"（ExtractedEdges，字段 edges）"""
    if response_model is None:
        return False
    try:
        fields = getattr(response_model, "model_fields", {}) or {}
        return "edges" in fields or any("extracted_edges" in name for name in fields)
    except Exception:
        return False


def _extract_json_from_markdown(text: str) -> Any:
    """
    从 LLM 响应中提取 JSON，兼容：
    - Markdown 围栏（```json ... ```）
    - 围栏后附带的说明文本
    - 裸 JSON 对象 / 数组

    解析成功返回对象；失败返回 None（由调用方决定回退策略）。
    """
    if not text or not text.strip():
        return None
    candidates = []
    raw = text.strip()
    candidates.append(raw)
    # Markdown 围栏
    if "```" in raw:
        parts = raw.split("```")
        for i, part in enumerate(parts):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") or part.startswith("["):
                candidates.append(part)
    # 提取第一个 { ... } 或 [ ... ] 块（带花括号平衡扫描，容忍前后说明文字）
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        if start != -1:
            depth = 0
            for i in range(start, len(raw)):
                if raw[i] == opener:
                    depth += 1
                elif raw[i] == closer:
                    depth -= 1
                    if depth == 0:
                        candidates.append(raw[start:i + 1])
                        break
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _apply_response_normalization_patch() -> bool:
    """
    Patch OpenAIGenericClient._generate_response，兼容本地网关的常见响应问题：

    1. Markdown 围栏包裹的 JSON（```json ... ```）——graphiti 原版 json.loads 直接失败
    2. 空响应——原版返回 {} 导致下游 reflexion 重试链累积超时
    3. 裸数组响应——按 response_model 规范化结构
    """
    try:
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    except ImportError:
        return False

    original_generate = OpenAIGenericClient._generate_response

    @functools.wraps(original_generate)
    async def patched_generate(
        self,
        messages,
        response_model=None,
        max_tokens=None,
        model_size=None,
    ):
        import openai as _openai

        # 与原始实现一致的 message 转换
        openai_messages = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})
        try:
            from graphiti_core.llm_client.openai_generic_client import DEFAULT_MODEL
        except ImportError:
            DEFAULT_MODEL = 'gpt-4.1-mini'
        try:
            import time as _time
            _t0 = _time.time()
            logger.info(f'LLM 调用开始: model={self.model or DEFAULT_MODEL}, messages={len(openai_messages)}, prompt_len={sum(len(m.get("content","")) for m in openai_messages)}')
            logger.info(f'LLM 调用 system 前80字: {openai_messages[0]["content"][:80] if openai_messages else "无"}')
            response = await self.client.chat.completions.create(
                model=self.model or DEFAULT_MODEL,
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            logger.info(f'LLM 调用完成: {_time.time()-_t0:.1f}s')
            result = response.choices[0].message.content or ''
            if not result.strip():
                # 空响应：OpenCode 等网关在连续调用/长提示下会返回空内容。
                # 只重试 1 次（短间隔），仍空则返回空 dict 让 graphiti 继续
                # （宁可丢失该次提取，也不让重试拖垮整个构建）。
                import time as _time
                try:
                    _time.sleep(1.5)
                    response = await self.client.chat.completions.create(
                        model=self.model or DEFAULT_MODEL,
                        messages=openai_messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    result = response.choices[0].message.content or ''
                    if result.strip():
                        logger.info('LLM 空响应重试成功')
                except Exception as retry_err:
                    logger.warning(f'LLM 空响应重试调用失败: {retry_err}')
                    result = ''
                if not result.strip():
                    logger.warning('LLM 返回空响应，返回空 dict（构建继续）')
                    if _is_edge_extraction(response_model):
                        # edge 提取空响应 → 降级为空边列表（ExtractedEdges 必需字段）
                        return {"edges": []}
                    return {}
            parsed = _extract_json_from_markdown(result)
            if parsed is None:
                # 纯文本响应：若 response_model 是单字符串字段，直接包装
                wrapped = _wrap_plain_text_as_response(result, response_model)
                if wrapped is not None:
                    return wrapped
                logger.error(f'LLM 响应无法解析为 JSON: {result[:500]}')
                if _is_edge_extraction(response_model):
                    return {"edges": []}
                return {}
            return _normalize_structured_response(parsed, response_model)
        except _openai.RateLimitError as e:
            raise e
        except Exception as e:
            # 连接类错误（OpenCode 等网关在高频调用下偶发断开）：
            # graphiti 对 APIConnectionError 直接抛出不重试，这里显式重试。
            import time as _time
            last_error = e
            # edge 提取对兼容网关稳定失败，只重试 1 次避免拖垮构建；
            # 其他调用重试 2 次。
            max_retry = 1 if _is_edge_extraction(response_model) else 2
            for attempt in range(max_retry):
                _time.sleep(2.0 * (attempt + 1))  # 2s, 4s 退避
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model or DEFAULT_MODEL,
                        messages=openai_messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    result = response.choices[0].message.content or ''
                    if not result.strip():
                        logger.warning(f'LLM 重试 {attempt+1} 次仍返回空响应')
                        continue
                    parsed = _extract_json_from_markdown(result)
                    if parsed is None:
                        wrapped = _wrap_plain_text_as_response(result, response_model)
                        if wrapped is not None:
                            return wrapped
                        logger.warning(f'LLM 重试 {attempt+1} 次响应无法解析为 JSON')
                        continue
                    logger.info(f'LLM 连接错误重试成功（第 {attempt+1} 次）')
                    return _normalize_structured_response(parsed, response_model)
                except Exception as retry_err:
                    last_error = retry_err
                    logger.warning(f'LLM 连接错误重试 {attempt+1}/{max_retry} 失败: {retry_err}')

            # edge 提取降级：OpenCode 等网关对"大实体列表+大文本"的边提取
            # 请求稳定失败（空响应/断连）。节点已提取成功，缺边不影响图谱
            # 主体；这里把 edge 提取失败降级为"空边列表"，让构建继续。
            if _is_edge_extraction(response_model):
                logger.warning('edge 提取连续失败，降级返回空边列表，构建继续')
                return {"edges": []}

            logger.error(f'Error in generating LLM response after retries: {last_error}', exc_info=True)
            raise last_error

    OpenAIGenericClient._generate_response = patched_generate
    logger.info("Graphiti LLM 响应规范化 patch 应用成功（Markdown 兼容 + 裸数组规范化）")
    return True


def _apply_new_node_only_attributes_patch() -> bool:
    """
    Patch extract_attributes_from_nodes：只对"新节点"（尚无摘要）提取属性/摘要。

    背景：graphiti 每处理一个 episode，都会对本次提取出的【所有】节点
    重新跑一遍属性提取 + 摘要生成（每节点 1-2 次 LLM 调用）。长文档建图时
    同一批实体在后续 chunk 中反复出现，造成大量重复 LLM 调用——这是建图
    慢的最大单一来源（实测单 episode 8 实体 → 约 16+ 次 LLM 调用）。

    这里注入默认的 should_summarize_node 过滤：节点已有非空摘要
    （即已在图谱中存在）→ 跳过属性/摘要；仅全新节点做一次提取。
    """
    try:
        import graphiti_core.graphiti as _graphiti_module
        from graphiti_core.utils.maintenance import node_operations as _node_ops
    except ImportError:
        return False

    original = _graphiti_module.extract_attributes_from_nodes

    @functools.wraps(original)
    async def patched(
        clients,
        nodes,
        episode=None,
        previous_episodes=None,
        entity_types=None,
        should_summarize_node=None,
    ):
        # 注意：graphiti 用 `await should_summarize_node(node)` 调用过滤函数，
        # 必须是 async 函数（同步 bool 会导致 "object bool can't be used in 'await'"）。
        async def _only_new(node):
            summary = (node.summary or "").strip()
            return len(summary) < 10

        return await original(
            clients,
            nodes,
            episode,
            previous_episodes,
            entity_types,
            should_summarize_node if should_summarize_node is not None else _only_new,
        )

    # graphiti.py 以 `from ... import extract_attributes_from_nodes` 绑定名字，
    # 必须在 graphiti 模块命名空间上替换才生效（模块全局按调用时查找）。
    _graphiti_module.extract_attributes_from_nodes = patched
    # 源模块一并替换，覆盖其它调用点（维护任务等）
    if hasattr(_node_ops, "extract_attributes_from_nodes"):
        _node_ops.extract_attributes_from_nodes = patched
    logger.info("Graphiti 新节点优先属性/摘要 patch 应用成功（跳过已有节点的重复 LLM 调用）")
    return True


def apply_patch() -> bool:
    """
    应用 monkey-patch 到 graphiti-core

    Returns:
        bool: patch 是否成功应用
    """
    global _patch_applied

    if _patch_applied:
        logger.debug("Graphiti patch 已应用，跳过")
        return True

    try:
        from graphiti_core.utils import bulk_utils

        # 保存原始函数
        original_add_nodes_and_edges_bulk_tx = bulk_utils.add_nodes_and_edges_bulk_tx

        @functools.wraps(original_add_nodes_and_edges_bulk_tx)
        async def patched_add_nodes_and_edges_bulk_tx(
            tx,  # GraphDriverSession (from session.execute_write)
            episodic_nodes,
            episodic_edges,
            entity_nodes,
            entity_edges,
            embedder,
            driver,
        ):
            """
            Patched version: sanitize node/edge attributes before Neo4j write

            签名与 graphiti-core 0.25.0 的 add_nodes_and_edges_bulk_tx 保持一致:
            (tx, episodic_nodes, episodic_edges, entity_nodes, entity_edges, embedder, driver)
            """
            # Sanitize entity_nodes attributes
            for node in entity_nodes:
                if hasattr(node, 'attributes') and node.attributes:
                    node.attributes = sanitize_attributes(node.attributes)

            # Sanitize entity_edges attributes
            for edge in entity_edges:
                if hasattr(edge, 'attributes') and edge.attributes:
                    edge.attributes = sanitize_attributes(edge.attributes)

            # 调用原始函数
            return await original_add_nodes_and_edges_bulk_tx(
                tx,
                episodic_nodes,
                episodic_edges,
                entity_nodes,
                entity_edges,
                embedder,
                driver,
            )

        # 应用 patch
        bulk_utils.add_nodes_and_edges_bulk_tx = patched_add_nodes_and_edges_bulk_tx

        # 响应规范化 patch（兼容裸数组等非标准 JSON 结构）
        _apply_response_normalization_patch()

        # 新节点优先属性/摘要 patch（跳过已有节点的重复 LLM 调用，显著加速建图）
        _apply_new_node_only_attributes_patch()

        # 边提取分块 patch：graphiti 默认 MAX_NODES=15，一次边提取要推理
        # 15 实体 × 105 对组合，OpenCode 等网关对此稳定超时/断连（实测
        # 118s 后 Connection error），导致图谱只有节点没有边。
        # 拆成每块 6 个实体（15 对）的小任务，单次生成轻量得多，成功率高。
        try:
            from graphiti_core.utils.maintenance import edge_operations as _edge_ops
            if getattr(_edge_ops, "MAX_NODES", 15) > 6:
                _edge_ops.MAX_NODES = 6
                logger.info(
                    f"edge 提取 MAX_NODES {getattr(_edge_ops, 'MAX_NODES', 15)} → 6"
                    "（分块边提取，提升 OpenCode 网关成功率）"
                )
        except Exception as exc:
            logger.warning(f"应用 edge 分块 patch 失败: {exc}")

        # 并发限制 patch：OpenCode/DeepSeek 等网关在并发 LLM 请求下
        # 会返回空内容或断开连接（实测 3 并发全部失败、串行全部成功）。
        # graphiti 的 semaphore_gather 默认 SEMAPHORE_LIMIT=20，这里强制串行。
        try:
            from graphiti_core import helpers as _graphiti_helpers

            @functools.wraps(_graphiti_helpers.semaphore_gather)
            async def _serial_semaphore_gather(*coroutines, max_coroutines=None):
                # 强制串行执行：并发请求会让兼容网关（OpenCode）断开连接。
                results = []
                for coroutine in coroutines:
                    results.append(await coroutine)
                return results

            _graphiti_helpers.semaphore_gather = _serial_semaphore_gather

            # 各模块以 `from graphiti_core.helpers import semaphore_gather`
            # 形式绑定了名字，需逐一替换，否则 patch 不生效。
            _patched_modules = 0
            for _module_name in (
                "graphiti_core.driver.neo4j_driver",
                "graphiti_core.utils.bulk_utils",
                "graphiti_core.utils.maintenance.community_operations",
                "graphiti_core.utils.maintenance.node_operations",
                "graphiti_core.utils.maintenance.edge_operations",
                "graphiti_core.search.search",
                "graphiti_core.cross_encoder.gemini_reranker_client",
                "graphiti_core.cross_encoder.openai_reranker_client",
                "graphiti_core.decorators",
            ):
                try:
                    import importlib
                    _mod = importlib.import_module(_module_name)
                    if hasattr(_mod, "semaphore_gather"):
                        _mod.semaphore_gather = _serial_semaphore_gather
                        _patched_modules += 1
                except Exception as _exc:
                    logger.warning(f"替换 {_module_name}.semaphore_gather 失败: {_exc}")

            logger.info(
                f"Graphiti semaphore_gather 并发限制 patch 应用成功"
                f"（强制串行，替换 {_patched_modules} 个模块引用）"
            )
        except Exception as exc:
            logger.warning(f"应用并发限制 patch 失败: {exc}")

        _patch_applied = True
        logger.info("Graphiti bulk_utils patch 应用成功")
        return True

    except ImportError as e:
        logger.warning(f"无法导入 graphiti_core.utils.bulk_utils: {e}")
        return False
    except Exception as e:
        logger.error(f"应用 Graphiti patch 失败: {e}")
        return False
