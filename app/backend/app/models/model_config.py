"""模型配置领域对象。

这些对象只描述配置，不负责网络请求或文件持久化。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ModelRole(str, Enum):
    PRIMARY = "primary"
    SIMULATION = "simulation"
    SIMULATION_BOOST = "simulation_boost"
    GRAPHITI_LLM = "graphiti_llm"
    GRAPHITI_EMBEDDING = "graphiti_embedding"


class Capability(str, Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    MODELS = "models"
    TOOLS = "tools"
    JSON = "json"


@dataclass
class ConnectionDraft:
    name: str
    endpoint: str
    api_key: Optional[str] = None
    provider_id: str = "custom"
    protocol: str = "openai-compatible"
    capabilities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auth_scheme: str = "bearer"
    headers: Dict[str, str] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelEntryDraft:
    name: str
    connection_id: Optional[str]
    model_id: str
    capabilities: List[str] = field(default_factory=lambda: [Capability.CHAT.value])
    verified: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    local_path: Optional[str] = None


@dataclass
class RoleBindings:
    roles: Dict[ModelRole, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        return {
            (role.value if isinstance(role, ModelRole) else str(role)): model_id
            for role, model_id in self.roles.items()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "RoleBindings":
        return cls(
            roles={ModelRole(role): model_id for role, model_id in data.items()}
        )


@dataclass
class ModelSnapshot:
    snapshot_id: str
    owner_type: str
    owner_id: str
    created_at: str
    registry_revision: int
    bindings: Dict[str, str]
    resolved: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
