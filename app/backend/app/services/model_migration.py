"""将旧 `.env` 模型配置一次性导入模型注册表。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from ..models.model_config import (
    ConnectionDraft,
    ModelEntryDraft,
    ModelRole,
    RoleBindings,
)
from .model_registry import ModelRegistryService


@dataclass(frozen=True)
class MigrationResult:
    imported: bool
    revision: int
    preset_id: Optional[str] = None
    reason: Optional[str] = None


def _int_or_none(value: Optional[str]) -> Optional[int]:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def import_legacy_env_once(
    registry: ModelRegistryService, *, environ: Optional[Mapping[str, str]] = None
) -> MigrationResult:
    source = dict(environ if environ is not None else os.environ)
    current = registry.get_redacted_registry()
    if any(item.get("id") == "legacy-import" for item in current["presets"]):
        return MigrationResult(False, current["revision"], "legacy-import", "already_imported")

    llm_key = (source.get("LLM_API_KEY") or source.get("OPENAI_API_KEY") or "").strip()
    llm_url = (source.get("LLM_BASE_URL") or source.get("OPENAI_BASE_URL") or "").strip()
    primary_model = (source.get("LLM_MODEL_NAME") or "").strip()
    graphiti_model = (source.get("GRAPHITI_LLM_MODEL") or primary_model).strip()
    embedding_key = (source.get("EMBEDDING_API_KEY") or source.get("OPENAI_API_KEY") or llm_key).strip()
    embedding_url = (source.get("EMBEDDING_BASE_URL") or source.get("OPENAI_BASE_URL") or llm_url).strip()
    embedding_model = (source.get("EMBEDDING_MODEL") or source.get("GRAPHITI_EMBEDDING_MODEL") or "").strip()

    if not llm_url or not primary_model:
        return MigrationResult(False, current["revision"], reason="legacy_config_incomplete")

    revision = current["revision"]
    llm_connection = registry.save_connection(
        ConnectionDraft(
            name="旧版 LLM 配置", endpoint=llm_url, api_key=llm_key or None, provider_id="legacy"
        ),
        expected_revision=revision,
    )
    revision = llm_connection["revision"]
    llm_connection_id = llm_connection["connection"]["id"]

    primary = registry.save_model_entry(
        ModelEntryDraft(
            name=primary_model, connection_id=llm_connection_id, model_id=primary_model, verified=True
        ),
        expected_revision=revision,
    )
    revision = primary["revision"]
    roles = {
        ModelRole.PRIMARY: primary["model"]["id"],
        ModelRole.SIMULATION: primary["model"]["id"],
    }

    if graphiti_model == primary_model:
        roles[ModelRole.GRAPHITI_LLM] = primary["model"]["id"]
    else:
        graphiti = registry.save_model_entry(
            ModelEntryDraft(
                name=graphiti_model,
                connection_id=llm_connection_id,
                model_id=graphiti_model,
                verified=True,
            ),
            expected_revision=revision,
        )
        revision = graphiti["revision"]
        roles[ModelRole.GRAPHITI_LLM] = graphiti["model"]["id"]

    if embedding_url and embedding_model:
        embedding_connection = registry.save_connection(
            ConnectionDraft(
                name="旧版 Embedding 配置",
                endpoint=embedding_url,
                api_key=embedding_key or None,
                provider_id="legacy",
            ),
            expected_revision=revision,
        )
        revision = embedding_connection["revision"]
        embedding = registry.save_model_entry(
            ModelEntryDraft(
                name=embedding_model,
                connection_id=embedding_connection["connection"]["id"],
                model_id=embedding_model,
                capabilities=["embedding"],
                verified=True,
                metadata={"dimension": _int_or_none(source.get("EMBEDDING_DIM"))},
            ),
            expected_revision=revision,
        )
        revision = embedding["revision"]
        roles[ModelRole.GRAPHITI_EMBEDDING] = embedding["model"]["id"]

    preset = registry.save_preset(
        preset_id="legacy-import",
        name="从 .env 导入",
        bindings=RoleBindings(roles=roles),
        expected_revision=revision,
        source="legacy-env",
    )
    return MigrationResult(True, preset["revision"], "legacy-import")
