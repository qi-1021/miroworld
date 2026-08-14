"""从不可变快照解析运行时模型配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..models.model_config import ModelRole
from .model_registry import ModelRegistryService


ROLE_FALLBACKS: Dict[ModelRole, Tuple[ModelRole, ...]] = {
    ModelRole.PRIMARY: tuple(),
    ModelRole.SIMULATION: (ModelRole.PRIMARY,),
    ModelRole.SIMULATION_BOOST: (ModelRole.SIMULATION, ModelRole.PRIMARY),
    ModelRole.GRAPHITI_LLM: (ModelRole.PRIMARY,),
    ModelRole.GRAPHITI_EMBEDDING: tuple(),
}


@dataclass(frozen=True)
class ResolvedChatModel:
    role: ModelRole
    model_entry_id: str
    connection_id: str
    endpoint: str
    api_key: Optional[str]
    model_id: str
    protocol: str
    capabilities: Tuple[str, ...]
    context_length: Optional[int]
    options: Dict[str, Any]


@dataclass(frozen=True)
class ResolvedEmbeddingModel:
    model_entry_id: str
    connection_id: Optional[str]
    endpoint: Optional[str]
    api_key: Optional[str]
    model_id: str
    local_path: Optional[str]
    dimension: Optional[int]
    metadata: Dict[str, Any]


class ModelResolver:
    def __init__(self, registry: Optional[ModelRegistryService] = None):
        self.registry = registry or ModelRegistryService()

    def _resolve_entry_id(
        self, snapshot: Dict[str, Any], requested_role: ModelRole
    ) -> tuple[ModelRole, str]:
        bindings = snapshot.get("bindings", {})
        for role in (requested_role, *ROLE_FALLBACKS.get(requested_role, tuple())):
            if bindings.get(role.value):
                return role, bindings[role.value]
        raise ValueError(f"模型快照未绑定角色: {requested_role.value}")

    def resolve_chat(
        self, role: ModelRole, snapshot_id: str
    ) -> ResolvedChatModel:
        snapshot = self.registry.get_snapshot(snapshot_id, redacted=False)
        resolved_role, model_entry_id = self._resolve_entry_id(snapshot, role)
        entry = self.registry.get_model_entry(model_entry_id)
        if "chat" not in entry.get("capabilities", []):
            raise ValueError("所选模型不具备聊天能力")
        connection_id = entry.get("connection_id")
        if not connection_id:
            raise ValueError("聊天模型缺少连接")
        connection = self.registry.get_connection(connection_id)
        secret = self.registry.resolve_snapshot_secret(snapshot_id, resolved_role)
        metadata = entry.get("metadata", {})
        return ResolvedChatModel(
            role=role,
            model_entry_id=model_entry_id,
            connection_id=connection_id,
            endpoint=connection["endpoint"],
            api_key=secret,
            model_id=entry["model_id"],
            protocol=connection.get("protocol", "openai-compatible"),
            capabilities=tuple(entry.get("capabilities", [])),
            context_length=metadata.get("context_length"),
            options={**connection.get("options", {}), **metadata.get("options", {})},
        )

    def resolve_embedding(self, snapshot_id: str) -> ResolvedEmbeddingModel:
        snapshot = self.registry.get_snapshot(snapshot_id, redacted=False)
        resolved_role, model_entry_id = self._resolve_entry_id(
            snapshot, ModelRole.GRAPHITI_EMBEDDING
        )
        entry = self.registry.get_model_entry(model_entry_id)
        if "embedding" not in entry.get("capabilities", []):
            raise ValueError("所选模型不具备向量能力")
        connection_id = entry.get("connection_id")
        connection = self.registry.get_connection(connection_id) if connection_id else None
        metadata = entry.get("metadata", {})
        return ResolvedEmbeddingModel(
            model_entry_id=model_entry_id,
            connection_id=connection_id,
            endpoint=connection.get("endpoint") if connection else None,
            api_key=(
                self.registry.resolve_snapshot_secret(snapshot_id, resolved_role)
                if connection_id
                else None
            ),
            model_id=entry["model_id"],
            local_path=entry.get("local_path"),
            dimension=metadata.get("dimension"),
            metadata=dict(metadata),
        )
