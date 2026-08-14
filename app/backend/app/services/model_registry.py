"""模型注册表与任务快照持久化。

注册表是 Web UI、CLI 和运行时解析器共同使用的唯一配置入口。秘密单独存放，
并以修订号绑定到快照，避免轮换密钥时改变正在运行的任务。
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.model_config import (
    ConnectionDraft,
    ModelEntryDraft,
    ModelRole,
    ModelSnapshot,
    RoleBindings,
)


class ModelRegistryConflict(RuntimeError):
    def __init__(self, current_revision: int):
        super().__init__(f"模型配置版本冲突，当前版本为 {current_revision}")
        self.current_revision = current_revision


class ModelRegistryService:
    """线程安全、文件持久化的模型注册表。"""

    _lock = threading.RLock()

    def __init__(self, data_dir: Optional[os.PathLike[str] | str] = None):
        default_dir = Path(__file__).resolve().parents[3] / "data" / "model-config"
        self.data_dir = Path(data_dir) if data_dir else default_dir
        self.registry_path = self.data_dir / "registry.json"
        self.secrets_path = self.data_dir / "secrets.json"
        self._ensure_files()

    def _ensure_files(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._atomic_write(self.registry_path, self._empty_registry())
        if not self.secrets_path.exists():
            self._atomic_write(self.secrets_path, {"version": 1, "connections": {}})
        self._restrict_secret_permissions()

    @staticmethod
    def _empty_registry() -> Dict[str, Any]:
        return {
            "version": 1,
            "revision": 0,
            "connections": [],
            "models": [],
            "presets": [],
            "project_bindings": [],
            "snapshots": [],
            "switches": [],
        }

    def _restrict_secret_permissions(self) -> None:
        try:
            current = stat.S_IMODE(self.secrets_path.stat().st_mode)
            desired = current & 0o600
            os.chmod(self.secrets_path, desired)
        except OSError:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _atomic_write(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取模型配置文件: {path}") from exc

    def _read_registry(self) -> Dict[str, Any]:
        value = self._read_json(self.registry_path)
        value.setdefault("revision", 0)
        for key in ("connections", "models", "presets", "project_bindings", "snapshots", "switches"):
            value.setdefault(key, [])
        return value

    def _read_secrets(self) -> Dict[str, Any]:
        value = self._read_json(self.secrets_path)
        value.setdefault("connections", {})
        return value

    @staticmethod
    def _check_revision(registry: Dict[str, Any], expected_revision: Optional[int]) -> None:
        current = int(registry.get("revision", 0))
        if expected_revision is not None and expected_revision != current:
            raise ModelRegistryConflict(current)

    @staticmethod
    def _mask_secret(secret: Optional[str]) -> Dict[str, Any]:
        if not secret:
            return {"has_secret": False, "secret_suffix": None}
        return {"has_secret": True, "secret_suffix": secret[-4:]}

    def _redact_connection(self, connection: Dict[str, Any], secrets: Dict[str, Any]) -> Dict[str, Any]:
        result = {key: value for key, value in connection.items() if key != "secret_revision_id"}
        secret = secrets.get("connections", {}).get(connection["id"], {})
        current = secret.get("current")
        value = secret.get("revisions", {}).get(current, {}).get("value") if current else None
        result.update(self._mask_secret(value))
        return result

    def get_redacted_registry(self) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            secrets = self._read_secrets()
            return {
                "version": registry.get("version", 1),
                "revision": registry.get("revision", 0),
                "connections": [self._redact_connection(item, secrets) for item in registry["connections"]],
                "models": [dict(item) for item in registry["models"]],
                "presets": [dict(item) for item in registry["presets"]],
                "project_bindings": [dict(item) for item in registry["project_bindings"]],
                "snapshots": [self._redact_snapshot(item) for item in registry["snapshots"]],
                "switches": [dict(item) for item in registry["switches"]],
            }

    def get_snapshot(self, snapshot_id: str, *, redacted: bool = True) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            snapshot = next(
                (item for item in registry["snapshots"] if item["snapshot_id"] == snapshot_id),
                None,
            )
            if snapshot is None:
                raise ValueError("模型快照不存在")
            return self._redact_snapshot(snapshot) if redacted else dict(snapshot)

    def get_connection(self, connection_id: str) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            connection = next(
                (item for item in registry["connections"] if item["id"] == connection_id),
                None,
            )
            if connection is None:
                raise ValueError("连接不存在")
            return dict(connection)

    def get_model_entry(self, model_entry_id: str) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            entry = next(
                (item for item in registry["models"] if item["id"] == model_entry_id),
                None,
            )
            if entry is None:
                raise ValueError("模型条目不存在")
            return dict(entry)

    def save_preset(
        self,
        *,
        preset_id: str,
        name: str,
        bindings: RoleBindings,
        expected_revision: Optional[int],
        source: str = "user",
    ) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            self._check_revision(registry, expected_revision)
            roles = bindings.to_dict()
            model_ids = {item["id"] for item in registry["models"]}
            missing = [entry_id for entry_id in roles.values() if entry_id not in model_ids]
            if missing:
                raise ValueError(f"预设引用不存在的模型: {', '.join(missing)}")
            preset = {
                "id": preset_id,
                "name": name,
                "roles": roles,
                "source": source,
                "updated_at": self._now(),
            }
            existing = next(
                (item for item in registry["presets"] if item["id"] == preset_id),
                None,
            )
            if existing:
                registry["presets"][registry["presets"].index(existing)] = preset
            else:
                registry["presets"].append(preset)
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "preset": preset}

    def save_project_bindings(
        self,
        *,
        project_id: str,
        bindings: RoleBindings,
        expected_revision: Optional[int],
    ) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            self._check_revision(registry, expected_revision)
            model_ids = {item["id"]: item for item in registry["models"]}
            for role, entry_id in bindings.to_dict().items():
                entry = model_ids.get(entry_id)
                if entry is None:
                    raise ValueError(f"项目绑定引用不存在的模型: {entry_id}")
                if not entry.get("verified"):
                    raise ValueError(f"模型 {entry.get('name', entry_id)} 尚未通过能力测试")
            binding = {
                "project_id": project_id,
                "roles": bindings.to_dict(),
                "updated_at": self._now(),
            }
            existing = next(
                (item for item in registry["project_bindings"] if item["project_id"] == project_id),
                None,
            )
            if existing:
                registry["project_bindings"][registry["project_bindings"].index(existing)] = binding
            else:
                registry["project_bindings"].append(binding)
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "binding": binding}

    def get_project_bindings(self, project_id: str) -> Optional[RoleBindings]:
        with self._lock:
            registry = self._read_registry()
            item = next(
                (entry for entry in registry["project_bindings"] if entry["project_id"] == project_id),
                None,
            )
            return RoleBindings.from_dict(item["roles"]) if item else None

    @staticmethod
    def _redact_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(snapshot)
        resolved = {}
        for role, data in snapshot.get("resolved", {}).items():
            resolved[role] = {key: value for key, value in data.items() if key != "secret_revision_id"}
        result["resolved"] = resolved
        return result

    def save_connection(
        self,
        draft: ConnectionDraft,
        *,
        expected_revision: Optional[int],
        connection_id: Optional[str] = None,
        secret_action: str = "replace",
    ) -> Dict[str, Any]:
        if not draft.endpoint or not draft.endpoint.strip():
            raise ValueError("接入点不能为空")
        if not draft.name or not draft.name.strip():
            raise ValueError("连接名称不能为空")
        if secret_action not in {"replace", "keep", "clear"}:
            raise ValueError("不支持的密钥操作")

        with self._lock:
            registry = self._read_registry()
            secrets = self._read_secrets()
            self._check_revision(registry, expected_revision)
            requested_connection_id = connection_id
            connection_id = connection_id or self._new_id("conn")
            existing = next((item for item in registry["connections"] if item["id"] == connection_id), None)
            if requested_connection_id is not None and existing is None:
                raise ValueError("连接不存在")

            connection = {
                "id": connection_id,
                "name": draft.name.strip(),
                "endpoint": draft.endpoint.strip(),
                "provider_id": draft.provider_id,
                "protocol": draft.protocol,
                "capabilities": draft.capabilities,
                "auth_scheme": draft.auth_scheme,
                "headers": draft.headers,
                "options": draft.options,
                "updated_at": self._now(),
            }
            if existing:
                index = registry["connections"].index(existing)
                registry["connections"][index] = connection
            else:
                registry["connections"].append(connection)

            secret_record = secrets["connections"].setdefault(connection_id, {"current": None, "revisions": {}})
            if secret_action == "replace" and draft.api_key is not None:
                secret_revision_id = self._new_id("secret")
                secret_record["revisions"][secret_revision_id] = {"value": draft.api_key, "created_at": self._now()}
                secret_record["current"] = secret_revision_id
            elif secret_action == "clear":
                secret_record["current"] = None
            secrets["connections"][connection_id] = secret_record

            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            self._atomic_write(self.secrets_path, secrets)
            self._restrict_secret_permissions()
            return {"revision": registry["revision"], "connection": self._redact_connection(connection, secrets)}

    def save_model_entry(
        self, draft: ModelEntryDraft, *, expected_revision: Optional[int], model_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not draft.name or not draft.name.strip():
            raise ValueError("模型名称不能为空")
        if not draft.model_id or not draft.model_id.strip():
            raise ValueError("模型 ID 不能为空")
        if draft.connection_id is None and not draft.local_path:
            raise ValueError("模型必须关联连接或本地路径")

        with self._lock:
            registry = self._read_registry()
            self._check_revision(registry, expected_revision)
            if draft.connection_id and not any(item["id"] == draft.connection_id for item in registry["connections"]):
                raise ValueError("关联连接不存在")
            entry = {
                "id": model_id or self._new_id("model"),
                "name": draft.name.strip(),
                "connection_id": draft.connection_id,
                "model_id": draft.model_id.strip(),
                "capabilities": list(draft.capabilities),
                "verified": bool(draft.verified),
                "metadata": dict(draft.metadata),
                "local_path": draft.local_path,
                "updated_at": self._now(),
            }
            existing = next(
                (item for item in registry["models"] if item["id"] == entry["id"]),
                None,
            )
            if existing:
                registry["models"][registry["models"].index(existing)] = entry
            else:
                registry["models"].append(entry)
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "model": entry}

    def _referencing_owners(self, registry: Dict[str, Any], model_entry_id: str) -> List[str]:
        """返回引用某模型条目的所有者描述列表（项目绑定/预设/任务快照）。"""
        references = []
        for binding in registry.get("project_bindings", []):
            if model_entry_id in (binding.get("roles") or {}).values():
                references.append(f"项目 {binding['project_id']}")
        for preset in registry.get("presets", []):
            if model_entry_id in (preset.get("roles") or {}).values():
                references.append(f"预设 {preset.get('name', preset['id'])}")
        for snapshot in registry.get("snapshots", []):
            if model_entry_id in (snapshot.get("bindings") or {}).values():
                references.append(f"{snapshot.get('owner_type', '任务')} {snapshot.get('owner_id', '?')} 的快照")
        return references

    def delete_model_entry(
        self, *, model_entry_id: str, expected_revision: Optional[int]
    ) -> Dict[str, Any]:
        """删除模型条目；若被项目绑定、预设或任务快照引用则拒绝。"""
        with self._lock:
            registry = self._read_registry()
            self._check_revision(registry, expected_revision)
            entry = next((item for item in registry["models"] if item["id"] == model_entry_id), None)
            if entry is None:
                raise ValueError("模型条目不存在")
            references = self._referencing_owners(registry, model_entry_id)
            if references:
                raise ValueError(
                    f"模型 {entry.get('name', model_entry_id)} 正被引用：{', '.join(references)}；"
                    f"请先解除引用再删除"
                )
            registry["models"] = [item for item in registry["models"] if item["id"] != model_entry_id]
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "deleted": model_entry_id}

    def delete_connection(
        self, *, connection_id: str, expected_revision: Optional[int]
    ) -> Dict[str, Any]:
        """删除连接：级联删除其模型条目与密钥；若模型被引用则拒绝。"""
        with self._lock:
            registry = self._read_registry()
            secrets = self._read_secrets()
            self._check_revision(registry, expected_revision)
            connection = next((item for item in registry["connections"] if item["id"] == connection_id), None)
            if connection is None:
                raise ValueError("连接不存在")
            entries = [item for item in registry["models"] if item.get("connection_id") == connection_id]
            referenced = []
            for entry in entries:
                for ref in self._referencing_owners(registry, entry["id"]):
                    referenced.append(f"{entry.get('name', entry['id'])}（被{ref}引用）")
            if referenced:
                raise ValueError(
                    f"连接 {connection['name']} 下的模型正被引用：{'；'.join(referenced)}；"
                    f"请先解除引用再删除"
                )
            registry["connections"] = [item for item in registry["connections"] if item["id"] != connection_id]
            registry["models"] = [item for item in registry["models"] if item.get("connection_id") != connection_id]
            secrets["connections"].pop(connection_id, None)
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            self._atomic_write(self.secrets_path, secrets)
            self._restrict_secret_permissions()
            return {"revision": registry["revision"], "deleted": connection_id, "removed_models": len(entries)}

    def delete_preset(
        self, *, preset_id: str, expected_revision: Optional[int]
    ) -> Dict[str, Any]:
        """删除预设。"""
        with self._lock:
            registry = self._read_registry()
            self._check_revision(registry, expected_revision)
            preset = next((item for item in registry["presets"] if item["id"] == preset_id), None)
            if preset is None:
                raise ValueError("预设不存在")
            registry["presets"] = [item for item in registry["presets"] if item["id"] != preset_id]
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "deleted": preset_id}

    def create_snapshot(
        self,
        *,
        owner_type: str,
        owner_id: str,
        bindings: RoleBindings,
        expected_revision: Optional[int],
    ) -> Dict[str, Any]:
        with self._lock:
            registry = self._read_registry()
            secrets = self._read_secrets()
            self._check_revision(registry, expected_revision)
            models_by_id = {item["id"]: item for item in registry["models"]}
            resolved: Dict[str, Dict[str, Any]] = {}
            for role, model_entry_id in bindings.to_dict().items():
                entry = models_by_id.get(model_entry_id)
                if entry is None:
                    raise ValueError(f"模型条目不存在: {model_entry_id}")
                if not entry.get("verified"):
                    raise ValueError(f"模型 {entry.get('name', model_entry_id)} 尚未通过能力测试")
                connection_id = entry.get("connection_id")
                secret_revision_id = None
                if connection_id:
                    connection = next((item for item in registry["connections"] if item["id"] == connection_id), None)
                    if connection is None:
                        raise ValueError(f"模型关联连接不存在: {connection_id}")
                    secret_revision_id = secrets.get("connections", {}).get(connection_id, {}).get("current")
                resolved[role] = {
                    "model_entry_id": model_entry_id,
                    "connection_id": connection_id,
                    "secret_revision_id": secret_revision_id,
                    "capabilities": entry.get("capabilities", []),
                }

            snapshot = ModelSnapshot(
                snapshot_id=self._new_id("snap"),
                owner_type=owner_type,
                owner_id=owner_id,
                created_at=self._now(),
                registry_revision=int(registry.get("revision", 0)),
                bindings=bindings.to_dict(),
                resolved=resolved,
            ).to_dict()
            registry["snapshots"].append(snapshot)
            registry["revision"] = int(registry.get("revision", 0)) + 1
            self._atomic_write(self.registry_path, registry)
            return {"revision": registry["revision"], "id": snapshot["snapshot_id"], "snapshot": self._redact_snapshot(snapshot)}

    def resolve_snapshot_secret(self, snapshot_id: str, role: ModelRole) -> Optional[str]:
        with self._lock:
            registry = self._read_registry()
            snapshot = next((item for item in registry["snapshots"] if item["snapshot_id"] == snapshot_id), None)
            if snapshot is None:
                raise ValueError("模型快照不存在")
            resolved = snapshot.get("resolved", {}).get(role.value, {})
            connection_id = resolved.get("connection_id")
            revision_id = resolved.get("secret_revision_id")
            if not connection_id or not revision_id:
                return None
            secrets = self._read_secrets()
            return secrets.get("connections", {}).get(connection_id, {}).get("revisions", {}).get(revision_id, {}).get("value")

    def resolve_connection_secret(self, connection_id: str) -> Optional[str]:
        with self._lock:
            secrets = self._read_secrets()
            record = secrets.get("connections", {}).get(connection_id, {})
            revision_id = record.get("current")
            return record.get("revisions", {}).get(revision_id, {}).get("value") if revision_id else None
