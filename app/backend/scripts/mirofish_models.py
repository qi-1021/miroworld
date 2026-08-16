#!/usr/bin/env python3
"""Miroworld 模型配置命令行工具。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.model_config import (  # noqa: E402
    ConnectionDraft,
    ModelEntryDraft,
    RoleBindings,
)
from app.services.model_detection import ModelConnectionDetector  # noqa: E402
from app.services.model_migration import import_legacy_env_once  # noqa: E402
from app.services.model_registry import (  # noqa: E402
    ModelRegistryConflict,
    ModelRegistryService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mirofish-models", description="管理 Miroworld 模型连接、模型和任务绑定"
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--data-dir", help=argparse.SUPPRESS)
    groups = parser.add_subparsers(dest="group", required=True)

    connections = groups.add_parser("connections", help="管理模型连接")
    connection_commands = connections.add_subparsers(dest="action", required=True)
    connection_commands.add_parser("list", help="列出连接")
    add = connection_commands.add_parser("add", help="添加连接")
    add.add_argument("--endpoint", required=True)
    add.add_argument("--api-key")
    add.add_argument("--name")
    add.add_argument("--allow-private-network", action="store_true")
    detect = connection_commands.add_parser("detect", help="只检测，不保存")
    detect.add_argument("--endpoint", required=True)
    detect.add_argument("--api-key")
    detect.add_argument("--name")
    detect.add_argument("--allow-private-network", action="store_true")
    discover = connection_commands.add_parser("discover", help="发现已保存连接的模型")
    discover.add_argument("connection_id")
    remove_connection = connection_commands.add_parser("remove", help="删除连接（级联删除其模型与密钥）")
    remove_connection.add_argument("connection_id")

    models = groups.add_parser("models", help="管理模型条目")
    model_commands = models.add_subparsers(dest="action", required=True)
    model_commands.add_parser("list", help="列出模型")
    model_add = model_commands.add_parser("add", help="登记模型")
    model_add.add_argument("--connection", required=True)
    model_add.add_argument("--model-id", required=True)
    model_add.add_argument("--name")
    model_add.add_argument("--capability", action="append", default=[])
    model_add.add_argument("--verified", action="store_true")
    remove_model = model_commands.add_parser("remove", help="删除模型条目")
    remove_model.add_argument("entry_id")

    presets = groups.add_parser("presets", help="管理预设")
    preset_commands = presets.add_subparsers(dest="action", required=True)
    preset_commands.add_parser("list", help="列出预设")
    remove_preset = preset_commands.add_parser("remove", help="删除预设")
    remove_preset.add_argument("preset_id")

    bindings = groups.add_parser("bindings", help="管理项目角色绑定")
    binding_commands = bindings.add_subparsers(dest="action", required=True)
    show = binding_commands.add_parser("show")
    show.add_argument("project_id")
    set_binding = binding_commands.add_parser("set")
    set_binding.add_argument("project_id")
    set_binding.add_argument("--role", action="append", required=True)

    snapshots = groups.add_parser("snapshots", help="管理任务快照")
    snapshot_commands = snapshots.add_subparsers(dest="action", required=True)
    snapshot_create = snapshot_commands.add_parser("create")
    snapshot_create.add_argument("owner_type")
    snapshot_create.add_argument("owner_id")
    snapshot_create.add_argument("--role", action="append", required=True)

    env = groups.add_parser("env", help="导入旧环境配置")
    env_commands = env.add_subparsers(dest="action", required=True)
    env_commands.add_parser("import")
    return parser


def _parse_roles(values: Sequence[str]) -> RoleBindings:
    roles = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"角色绑定格式应为 role=model_entry_id: {value}")
        role, entry_id = value.split("=", 1)
        if not role.strip() or not entry_id.strip():
            raise ValueError(f"无效角色绑定: {value}")
        roles[role.strip()] = entry_id.strip()
    return RoleBindings.from_dict(roles)


def _connection_draft(args) -> ConnectionDraft:
    return ConnectionDraft(
        name=args.name or "自动识别连接",
        endpoint=args.endpoint,
        api_key=args.api_key,
        options={"allow_private_network": bool(args.allow_private_network)},
    )


def _execute(args, registry: ModelRegistryService) -> Any:
    state = registry.get_redacted_registry()
    revision = state["revision"]
    if args.group == "connections" and args.action == "list":
        return {"revision": revision, "connections": state["connections"]}
    if args.group == "connections" and args.action == "detect":
        return ModelConnectionDetector().detect(_connection_draft(args)).to_dict()
    if args.group == "connections" and args.action == "add":
        return registry.save_connection(_connection_draft(args), expected_revision=revision)
    if args.group == "connections" and args.action == "discover":
        connection = registry.get_connection(args.connection_id)
        draft = ConnectionDraft(
            name=connection["name"],
            endpoint=connection["endpoint"],
            api_key=registry.resolve_connection_secret(args.connection_id),
            provider_id=connection.get("provider_id", "custom"),
            protocol=connection.get("protocol", "openai-compatible"),
            headers=connection.get("headers", {}),
            options=connection.get("options", {}),
        )
        return ModelConnectionDetector().detect(draft).to_dict()
    if args.group == "models" and args.action == "list":
        return {"revision": revision, "models": state["models"]}
    if args.group == "models" and args.action == "add":
        capabilities = args.capability or ["chat"]
        return registry.save_model_entry(
            ModelEntryDraft(
                name=args.name or args.model_id,
                connection_id=args.connection,
                model_id=args.model_id,
                capabilities=capabilities,
                verified=args.verified,
            ),
            expected_revision=revision,
        )
    if args.group == "connections" and args.action == "remove":
        return registry.delete_connection(
            connection_id=args.connection_id, expected_revision=revision
        )
    if args.group == "models" and args.action == "remove":
        return registry.delete_model_entry(
            model_entry_id=args.entry_id, expected_revision=revision
        )
    if args.group == "presets" and args.action == "list":
        return {"revision": revision, "presets": state["presets"]}
    if args.group == "presets" and args.action == "remove":
        return registry.delete_preset(
            preset_id=args.preset_id, expected_revision=revision
        )
    if args.group == "bindings" and args.action == "show":
        value = registry.get_project_bindings(args.project_id)
        return {"project_id": args.project_id, "roles": value.to_dict() if value else {}}
    if args.group == "bindings" and args.action == "set":
        return registry.save_project_bindings(
            project_id=args.project_id,
            bindings=_parse_roles(args.role),
            expected_revision=revision,
        )
    if args.group == "snapshots" and args.action == "create":
        return registry.create_snapshot(
            owner_type=args.owner_type,
            owner_id=args.owner_id,
            bindings=_parse_roles(args.role),
            expected_revision=revision,
        )
    if args.group == "env" and args.action == "import":
        result = import_legacy_env_once(registry)
        return {
            "imported": result.imported,
            "revision": result.revision,
            "preset_id": result.preset_id,
            "reason": result.reason,
        }
    raise ValueError("不支持的命令")


def _human_text(args, result: Any) -> str:
    if args.group == "connections" and args.action == "list":
        items = result["connections"]
        if not items:
            return "尚未配置模型连接。"
        return "\n".join(
            f"{item['id']}  {item['name']}  {item['endpoint']}  密钥:{'已配置' if item['has_secret'] else '无'}"
            for item in items
        )
    if args.group == "models" and args.action == "list":
        items = result["models"]
        if not items:
            return "尚未登记模型。"
        return "\n".join(
            f"{item['id']}  {item['name']}  {item['model_id']}  {'已验证' if item['verified'] else '未验证'}"
            for item in items
        )
    if args.group == "presets" and args.action == "list":
        items = result["presets"]
        if not items:
            return "尚未创建预设。"
        return "\n".join(
            f"{item['id']}  {item.get('name', '未命名')}  角色数:{len(item.get('roles', {}))}"
            for item in items
        )
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(
    argv: Optional[Sequence[str]] = None, *, registry: Optional[ModelRegistryService] = None
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    service = registry or ModelRegistryService(args.data_dir)
    try:
        result = _execute(args, service)
        print(
            json.dumps({"success": True, "data": result}, ensure_ascii=False)
            if args.as_json
            else _human_text(args, result)
        )
        return 0
    except ModelRegistryConflict as exc:
        payload = {"success": False, "error": {"code": "REGISTRY_CONFLICT", "message": str(exc)}}
    except Exception as exc:
        payload = {"success": False, "error": {"code": "COMMAND_FAILED", "message": str(exc)}}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
