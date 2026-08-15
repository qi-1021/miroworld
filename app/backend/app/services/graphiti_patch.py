"""
Graphiti-core Monkey Patch

Workaround for graphiti-core Issue #683:
LLM 生成的嵌套属性会导致 Neo4j 写入失败
(Neo4j property values only accept primitive types or arrays thereof)

Patch 策略：
- 拦截 bulk_utils.add_nodes_and_edges_bulk_tx
- 在写入 Neo4j 前将嵌套 dict/list 转为 JSON 字符串
"""

import asyncio
import ast
import json
import functools
from typing import Any, Dict

from ..config import Config
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
    模型可能把 {"entity_resolutions": [...]} 直接输出成 [...]（裸数组），
    甚至输出成单条记录的裸 dict（如 {'id': 0, 'name': ...}）。
    这里在 response_model 有且仅有一个 list 字段时自动包装：
    - 裸数组 → {field: [...]}
    - 裸 dict（且不含该字段、看起来像单条列表项）→ {field: [dict]}
    """
    try:
        list_fields = [
            name
            for name, field in response_model.model_fields.items()
            if "list" in str(field.annotation).lower()
        ]
    except Exception:
        return result
    if len(list_fields) != 1:
        return result
    field_name = list_fields[0]

    if isinstance(result, list):
        return {field_name: result}

    # 裸 dict：如果结果里已经包含目标字段则原样返回（可能是部分响应）
    if isinstance(result, dict) and field_name in result:
        return result
    # 其余 dict（单条记录形状）→ 包装为单元素列表
    if isinstance(result, dict):
        logger.debug(
            f"裸 dict 响应（{list(result.keys())[:4]}…）包装为 {field_name}: [单条]"
        )
        return {field_name: [result]}

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


def _try_parse_robust(candidate: str) -> Any:
    """
    针对单个候选字符串的鲁棒 JSON 解析，依次尝试：
    1. json.loads (标准 JSON)
    2. ast.literal_eval (兼容 Python 单引号 dict，如 {'a': 1})，
       并把单引号版再喂回 json.loads 以得到标准 dict
    3. 截断收敛：当内容被截断（JSON 不完整）时，从末尾逐步收缩到
       最长可解析前缀（有界迭代，避免对超长输入失控）

    全部失败返回 None。
    """
    if not candidate:
        return None

    # 第 1 步：标准 JSON
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        pass

    # 第 2 步：ast.literal_eval（Python 字面量，兼容单引号 dict/list）
    try:
        value = ast.literal_eval(candidate)
        # 仅接受同构 JSON 容器（dict / list / 标量），拒绝 eval 出其它东西
        if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
            # 转回标准 JSON 再由 json.loads 解析，保证返回的是纯 dict/list 且键为合法 JSON
            normalized = json.loads(json.dumps(value, ensure_ascii=False, default=str))
            return normalized
    except (ValueError, SyntaxError):
        pass

    # 第 3 步：截断收敛 —— 逐步去掉末尾字符直到能解析（有界）
    stripped = candidate.rstrip()
    if len(stripped) <= 1:
        return None
    # 只看可能的尾部不完整情况：以 '}' 或 ']' 缺失为代表，先整体尝试一次
    for keep in range(len(stripped), max(1, len(stripped) - 4096), -1):
        fragment = stripped[:keep].rstrip()
        if not fragment:
            break
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(fragment)
                if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
                    if parser is ast.literal_eval:
                        value = json.loads(json.dumps(value, ensure_ascii=False, default=str))
                    return value
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
    return None


def _extract_json_from_markdown(text: str) -> Any:
    """
    从 LLM 响应中提取 JSON，兼容：
    - Markdown 围栏（```json ... ```）
    - 围栏后附带的说明文本
    - 裸 JSON 对象 / 数组
    - Python 风格单引号 dict（{'a': 1}）
    - 被截断的不完整 JSON（自动收敛到最长可解析前缀）

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
        parsed = _try_parse_robust(cand)
        if parsed is not None:
            return parsed
    return None


async def _normalize_and_validate(
    parsed: Any,
    response_model: Any,
    call_llm_once,
) -> Any:
    """
    规范化 LLM 响应并用 response_model 校验；校验失败时重试一次 LLM 调用。

    背景：OpenCode 等网关偶发返回"形状不符但内容正确"的响应
    （如 NodeResolutions 应返回 {"entity_resolutions": [...]}，实际返回
    单条记录裸 dict），Pydantic 校验失败会直接毁掉整个 episode。
    规范化（_normalize_structured_response）能救回大部分，剩下的靠
    一次随机重试（LLM 输出随机，重试往往得到合法结构）。
    """
    normalized = _normalize_structured_response(parsed, response_model)
    if response_model is None:
        return normalized
    try:
        response_model(**normalized)
        return normalized
    except Exception as exc:
        model_name = getattr(response_model, "__name__", "response_model")
        logger.warning(
            f'LLM 响应未通过 {model_name} 校验（{str(exc)[:100]}），重试一次'
        )
        import time as _time
        try:
            _time.sleep(1.5)
            retry_result = await call_llm_once()
            retry_parsed = (
                _extract_json_from_markdown(retry_result) if retry_result else None
            )
            if retry_parsed is not None:
                retry_normalized = _normalize_structured_response(
                    retry_parsed, response_model
                )
                try:
                    response_model(**retry_normalized)
                    logger.info('LLM 校验失败重试成功')
                    return retry_normalized
                except Exception:
                    logger.warning('LLM 校验失败重试仍不符合模型，原样返回')
                    return retry_normalized
        except Exception as retry_err:
            logger.warning(f'LLM 校验失败重试调用出错: {retry_err}')
        return normalized


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

            async def _llm_call_once():
                resp = await self.client.chat.completions.create(
                    model=self.model or DEFAULT_MODEL,
                    messages=openai_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return resp.choices[0].message.content or ''

            return await _normalize_and_validate(parsed, response_model, _llm_call_once)
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

                    async def _llm_call_once():
                        resp = await self.client.chat.completions.create(
                            model=self.model or DEFAULT_MODEL,
                            messages=openai_messages,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        )
                        return resp.choices[0].message.content or ''

                    return await _normalize_and_validate(
                        parsed, response_model, _llm_call_once
                    )
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


def _extract_count_from_records(records: Any) -> int:
    """
    从 execute_query 返回的首条记录中提取 'cnt' 计数。

    兼容不同驱动返回形式：
    - dict / Mapping：record.get('cnt') 或 record['cnt']
    - 带 .get 的对象（neo4j 官方 Record）
    - 带 .data() 的对象（如某类封装）
    提取不到一律返回 0（在 skip 逻辑里 0 才会触发跳过）。
    """
    if not records:
        return 0
    try:
        record = records[0]
    except (IndexError, TypeError):
        return 0
    cnt = None
    try:
        if hasattr(record, 'get'):
            cnt = record.get('cnt')
            if cnt is None and hasattr(record, 'data'):
                data = record.data()
                cnt = data.get('cnt') if isinstance(data, dict) else None
        elif isinstance(record, dict):
            cnt = record.get('cnt')
    except Exception:
        return 0
    try:
        return int(cnt or 0)
    except (TypeError, ValueError):
        return 0


def _apply_edge_skip_patch() -> bool:
    """
    Patch edge_operations.extract_edges：首个 episode 时跳过边提取。

    背景：建图的首个 chunk（episode）处理时，目标 group_id 在图谱中还没有
    任何 EntityNode。此时边提取既找不到"前序实体"做配对，又要对大实体列表 +
    大文本做一次很重的 LLM 推理，兼容网关在此场景稳定超时/断连，白白拖慢
    建图。

    策略（保守）：
    - 在 extract_edges 入口用 clients.driver 执行一个轻量 count 查询，
      统计 group_id 下已有的 EntityNode 数量。
    - 仅当 count == 0 且 Config.GRAPHITI_EDGE_MODE == 'skip-first' 时
      直接 return [] 跳过本次边提取。
    - 查询本身 try/except 包裹：查询失败视为"不跳过"（宁多不少，保守）。
    """
    try:
        from graphiti_core.utils.maintenance import edge_operations as _edge_ops
    except ImportError:
        return False

    original = _edge_ops.extract_edges

    @functools.wraps(original)
    async def patched_extract_edges(
        clients,
        episode,
        nodes,
        previous_episodes,
        edge_type_map,
        group_id: str = '',
        edge_types=None,
        custom_extraction_instructions=None,
    ):
        # 仅 skip-first 模式启用跳过逻辑
        if Config.GRAPHITI_EDGE_MODE == 'skip-first':
            should_skip = False
            try:
                driver = getattr(clients, 'driver', None)
                if driver is not None:
                    records, _, _ = await driver.execute_query(
                        "MATCH (n:Entity) WHERE n.group_id = $group_id "
                        "RETURN count(n) AS cnt",
                        group_id=group_id,
                    )
                    cnt = _extract_count_from_records(records)
                    should_skip = int(cnt or 0) == 0
            except Exception as exc:
                # 查询失败 → 保守不跳过，走正常边提取
                logger.warning(
                    f"edge-skip count 查询失败，按不跳过处理（group_id={group_id}）: {exc}"
                )
                should_skip = False
            if should_skip:
                logger.info(
                    f"group_id={group_id} 尚无 EntityNode，GRAPHITI_EDGE_MODE=skip-first"
                    "，跳过本次边提取"
                )
                return []

        return await original(
            clients,
            episode,
            nodes,
            previous_episodes,
            edge_type_map,
            group_id,
            edge_types,
            custom_extraction_instructions,
        )

    _edge_ops.extract_edges = patched_extract_edges
    logger.info(f"Graphiti 边提取跳过 patch 应用成功（GRAPHITI_EDGE_MODE={Config.GRAPHITI_EDGE_MODE}）")
    return True


def _apply_entity_extraction_retry_patch() -> bool:
    """
    Patch extract_nodes：实体提取结果过少时自动重试一次。

    背景：OpenCode 网关在负载波动时会对同样的文本返回"敷衍式"提取
    （实测同样 270 字文本，一次 46.8s 提取出 15 个实体，另两次 4.4s
    只提取 1 个）。实体过少会直接毁掉图谱质量（节点几乎为空）。
    这里对"非空文本但实体 < 3"的结果重试一次——LLM 输出随机，重试
    通常能拿到完整实体列表；重试仍少则接受原结果（不无限重试）。
    """
    try:
        from graphiti_core.utils.maintenance import node_operations as _node_ops
    except ImportError:
        return False

    original = _node_ops.extract_nodes

    @functools.wraps(original)
    async def patched_extract_nodes(
        clients,
        episode,
        previous_episodes,
        entity_types=None,
        excluded_entity_types=None,
        custom_extraction_instructions=None,
    ):
        result = await original(
            clients,
            episode,
            previous_episodes,
            entity_types,
            excluded_entity_types,
            custom_extraction_instructions,
        )
        content = (episode.content or "").strip()
        if len(result) < 3 and len(content) >= 100:
            logger.warning(
                f"实体提取仅 {len(result)} 个（文本 {len(content)} 字），重试一次"
            )
            retried = await original(
                clients,
                episode,
                previous_episodes,
                entity_types,
                excluded_entity_types,
                custom_extraction_instructions,
            )
            if len(retried) > len(result):
                logger.info(f"实体提取重试成功：{len(result)} → {len(retried)} 个")
                return retried
            logger.warning(f"实体提取重试仍为 {len(retried)} 个，接受该结果")
        return result

    # graphiti.py 以 `from ... import extract_nodes` 绑定名字，需同时替换
    # 源模块与 graphiti 模块命名空间（模块全局按调用时查找）。
    _node_ops.extract_nodes = patched_extract_nodes
    try:
        import graphiti_core.graphiti as _g
        _g.extract_nodes = patched_extract_nodes
    except Exception:
        pass
    logger.info("Graphiti 实体提取过少自动重试 patch 应用成功")
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

        # 实体提取过少自动重试（应对网关"敷衍式"低质量提取）
        _apply_entity_extraction_retry_patch()

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

        # 边提取跳过 patch：首个 episode（group 尚无 EntityNode）时跳过边提取，
        # 避免无意义的高成本 LLM 配对推理稳定失败拖慢建图。
        _apply_edge_skip_patch()

        # 并发限制 patch：OpenCode/DeepSeek 等网关在并发 LLM 请求下
        # 会返回空内容或断开连接（实测 3 并发全部失败、串行全部成功）。
        # graphiti 的 semaphore_gather 默认 SEMAPHORE_LIMIT=20。这里改为
        # asyncio.Semaphore 钳制版本，默认并发上限 1（完全等价于原串行行为），
        # 但保留向上调以在稳定网关下提速的空间。
        try:
            from graphiti_core import helpers as _graphiti_helpers

            # graphiti 的 semaphore_gather 通过 max_coroutines 控制并发；
            # 我们把它钳制到 [1, 上限]。未显式指定时默认 1（完全串行，
            # 与旧行为一致），让兼容网关保持最高稳定性。
            def _clamp_concurrency(max_coroutines: int | None) -> int:
                if max_coroutines is None:
                    return 1
                try:
                    return max(1, int(max_coroutines or 1))
                except (TypeError, ValueError):
                    return 1

            @functools.wraps(_graphiti_helpers.semaphore_gather)
            async def _serial_semaphore_gather(*coroutines, max_coroutines=None):
                # asyncio.Semaphore 钳制并发；默认 1 即完全串行（与旧行为一致）。
                limit = _clamp_concurrency(max_coroutines)
                semaphore = asyncio.Semaphore(limit)

                async def _run(coroutine):
                    async with semaphore:
                        return await coroutine

                return await asyncio.gather(*(_run(c) for c in coroutines))

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
                f"Graphiti semaphore_gather 并发钳制 patch 应用成功"
                f"（默认并发 1，替换 {_patched_modules} 个模块引用）"
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
