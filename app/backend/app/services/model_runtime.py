"""运行时模型解析辅助：项目角色绑定 → 可执行凭据。

统一"网页里切换模型 → 任务真正使用该模型"的解析入口：
- resolve_project_chat：按项目绑定的角色解析出 ResolvedChatModel；
- resolve_project_chat_config：返回 (api_key, base_url, model) 三元组，供
  OasisProfileGenerator / SimulationConfigGenerator 等旧组件直接使用；
- resolve_project_chat_env：生成子进程环境变量覆盖（媒体模拟脚本读取
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME 与 LLM_BOOST_*）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..models.model_config import ModelRole
from .model_registry import ModelRegistryService
from .model_resolver import ModelResolver


def _load_project_snapshot(project_id: str) -> Tuple[Any, Optional[Dict[str, Any]], Dict[str, str]]:
    """加载项目角色绑定并创建一次不可变快照。

    返回 (registry, snapshot, roles)：
    - 项目未绑定任何模型时 snapshot 为 None；
    - 快照创建失败时吞掉异常并返回 (registry, None, roles)。
    """
    registry = ModelRegistryService()
    bindings = registry.get_project_bindings(project_id) if project_id else None
    roles = bindings.to_dict() if bindings else {}
    if not roles:
        return registry, None, roles
    try:
        snapshot = registry.create_snapshot(
            owner_type="project",
            owner_id=project_id,
            bindings=bindings,
            expected_revision=None,
        )
        return registry, snapshot, roles
    except Exception:
        return registry, None, roles


def resolve_project_chat(project_id: str, role: ModelRole = ModelRole.PRIMARY):
    """按项目绑定解析聊天模型，返回 ResolvedChatModel 或 None（任何失败都返回 None）。

    只解析显式绑定的角色，不做隐式回退；需要回退时调用方自己降级。
    """
    if not project_id:
        return None
    try:
        registry, snapshot, roles = _load_project_snapshot(project_id)
        if not snapshot or not roles.get(role.value):
            return None
        return ModelResolver(registry).resolve_chat(role, snapshot["id"])
    except Exception:
        return None


def resolve_project_chat_config(
    project_id: str, role: ModelRole = ModelRole.PRIMARY
) -> Optional[Tuple[str, str, str]]:
    """返回 (api_key, base_url, model) 三元组；项目未绑定/凭据不完整返回 None。"""
    resolved = resolve_project_chat(project_id, role)
    if not resolved:
        return None
    if not (resolved.api_key and resolved.endpoint and resolved.model_id):
        return None
    return resolved.api_key, resolved.endpoint, resolved.model_id


def resolve_project_chat_env(project_id: str) -> Dict[str, str]:
    """生成媒体模拟子进程的环境变量覆盖。

    primary 绑定 → LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME；
    显式绑定 simulation_boost 或 simulation 角色 → LLM_BOOST_*。
    未绑定任何项目模型时返回空 dict（子进程沿用 .env）。
    """
    overrides: Dict[str, str] = {}
    if not project_id:
        return overrides

    try:
        registry, snapshot, roles = _load_project_snapshot(project_id)
        if not snapshot:
            return overrides
        resolver = ModelResolver(registry)

        if roles.get(ModelRole.PRIMARY.value):
            primary = resolver.resolve_chat(ModelRole.PRIMARY, snapshot["id"])
            if primary.api_key and primary.endpoint and primary.model_id:
                overrides["LLM_API_KEY"] = primary.api_key
                overrides["LLM_BASE_URL"] = primary.endpoint
                overrides["LLM_MODEL_NAME"] = primary.model_id

        # 加速模型：只有显式绑定了 simulation_boost / simulation 才覆盖
        for role in (ModelRole.SIMULATION_BOOST, ModelRole.SIMULATION):
            if not roles.get(role.value):
                continue
            boost = resolver.resolve_chat(role, snapshot["id"])
            if boost.api_key and boost.endpoint and boost.model_id:
                overrides["LLM_BOOST_API_KEY"] = boost.api_key
                overrides["LLM_BOOST_BASE_URL"] = boost.endpoint
                overrides["LLM_BOOST_MODEL_NAME"] = boost.model_id
                break
    except Exception:
        pass
    return overrides


def resolve_project_chat_config_any(
    project_id: str,
) -> Optional[Tuple[str, str, str]]:
    """项目绑定优先，未绑定时回退注册表候选（与 graphiti 回退链一致）。"""
    config = resolve_project_chat_config(project_id)
    if config:
        return config
    try:
        from .graphiti_patch import iter_chat_model_candidates
        candidates = iter_chat_model_candidates()
        if candidates:
            api_key, base_url, model = candidates[0]
            if api_key and base_url and model:
                return api_key, base_url, model
    except Exception:
        pass
    return None
