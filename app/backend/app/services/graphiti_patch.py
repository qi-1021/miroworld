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


def _apply_response_normalization_patch() -> bool:
    """
    Patch OpenAIGenericClient._generate_response：
    在解析出 JSON 后按 response_model 规范化结构，兼容裸数组响应。
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
        result = await original_generate(
            self,
            messages,
            response_model=response_model,
            max_tokens=max_tokens,
            model_size=model_size,
        )
        return _normalize_structured_response(result, response_model)

    OpenAIGenericClient._generate_response = patched_generate
    logger.info("Graphiti LLM 响应规范化 patch 应用成功")
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

        _patch_applied = True
        logger.info("Graphiti bulk_utils patch 应用成功")
        return True

    except ImportError as e:
        logger.warning(f"无法导入 graphiti_core.utils.bulk_utils: {e}")
        return False
    except Exception as e:
        logger.error(f"应用 Graphiti patch 失败: {e}")
        return False
