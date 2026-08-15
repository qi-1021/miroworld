"""模型配置、检测、角色绑定与快照 API。"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict

from flask import jsonify, request

from . import models_bp
from ..models.model_config import (
    ConnectionDraft,
    ModelEntryDraft,
    RoleBindings,
)
from ..services.model_detection import (
    DetectionResult,
    ModelConnectionDetector,
    PrivateNetworkRequiredError,
    UnsafeEndpointError,
)
from ..services.local_embedding import (
    LocalModelError,
    LocalModelNotFoundError,
    LocalRuntimeMissingError,
    compute_local_fingerprint,
    inspect_local_model,
    probe_local_model,
    scan_local_models,
)
from ..services.model_registry import (
    ModelRegistryConflict,
    ModelRegistryService,
)


registry_service = ModelRegistryService()
_logger = logging.getLogger('mirofish.api.models')


def detect_connection(draft: ConnectionDraft) -> DetectionResult:
    return ModelConnectionDetector().detect(draft)


def _success(data: Any, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def _error(code: str, message: str, status: int, *, data: Any = None):
    payload: Dict[str, Any] = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status


def _json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return body


def _connection_draft(body: Dict[str, Any], *, api_key: Any = None) -> ConnectionDraft:
    name = str(body.get("name") or "").strip()
    endpoint = str(body.get("endpoint") or "").strip()
    if not name:
        name = "自动识别连接"
    if not endpoint:
        raise ValueError("请填写接入点")
    return ConnectionDraft(
        name=name,
        endpoint=endpoint,
        api_key=body.get("api_key") if api_key is None else api_key,
        provider_id=str(body.get("provider_id") or "custom"),
        protocol=str(body.get("protocol") or "openai-compatible"),
        capabilities=body.get("capabilities") or {},
        auth_scheme=str(body.get("auth_scheme") or "bearer"),
        headers=body.get("headers") or {},
        options=body.get("options") or {},
    )


def _handle_exception(exc: Exception):
    if isinstance(exc, ModelRegistryConflict):
        return _error(
            "REGISTRY_CONFLICT",
            str(exc),
            409,
            data={"registry": registry_service.get_redacted_registry()},
        )
    if isinstance(exc, PrivateNetworkRequiredError):
        return _error(
            "PRIVATE_NETWORK_REQUIRED",
            str(exc),
            422,
            data={"hostname": exc.hostname, "addresses": exc.addresses},
        )
    if isinstance(exc, UnsafeEndpointError):
        return _error("UNSAFE_ENDPOINT", str(exc), 422)
    if isinstance(exc, LocalRuntimeMissingError):
        return _error(
            "LOCAL_RUNTIME_MISSING",
            str(exc),
            422,
            data={"install_hint": LocalRuntimeMissingError.INSTALL_HINT},
        )
    if isinstance(exc, LocalModelNotFoundError):
        return _error("LOCAL_MODEL_NOT_FOUND", str(exc), 404)
    if isinstance(exc, LocalModelError):
        return _error("LOCAL_MODEL_ERROR", str(exc), 422)
    if isinstance(exc, ValueError):
        return _error("VALIDATION_ERROR", str(exc), 400)
    return _error("INTERNAL_ERROR", "模型配置操作失败", 500)


@models_bp.route("/embedding-preference", methods=["GET"])
def get_embedding_preference_route():
    """读取向量模型偏好（cloud/local/auto）。"""
    from ..services.embedding_resolver import get_embedding_preference
    return _success({"preference": get_embedding_preference()})


@models_bp.route("/embedding-preference", methods=["PUT"])
def put_embedding_preference_route():
    """写入向量模型偏好（cloud/local/auto），并立即使当前进程内缓存失效。"""
    from ..services.embedding_resolver import set_embedding_preference
    data = request.get_json(silent=True) or {}
    try:
        pref = set_embedding_preference(str(data.get("preference") or ""))
        # 切换偏好后清掉 world_bible 的懒加载 embedder 缓存，
        # 否则要等后端重启才会按新偏好选择云端/本地模型
        try:
            from ..services.world_bible import WorldBibleService
            WorldBibleService._reset_embedder_cache()
        except Exception as exc:  # 缓存清理失败不应影响偏好已保存的结果
            _logger.warning(f"清理向量模型缓存失败（忽略）: {exc}")
        return _success({"preference": pref, "cache_reset": True})
    except ValueError as exc:
        return _error("VALIDATION_ERROR", str(exc), 400)


@models_bp.route("/registry", methods=["GET"])
def get_registry():
    return _success(registry_service.get_redacted_registry())


@models_bp.route("/connections/detect", methods=["POST"])
def detect_connection_route():
    try:
        result = detect_connection(_connection_draft(_json_body()))
        return _success(result.to_dict())
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/connections", methods=["POST"])
def create_connection():
    try:
        body = _json_body()
        result = registry_service.save_connection(
            _connection_draft(body),
            expected_revision=body.get("revision"),
        )
        return _success(result, 201)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/connections/<connection_id>", methods=["PATCH"])
def update_connection(connection_id: str):
    try:
        body = _json_body()
        existing = registry_service.get_connection(connection_id)
        merged = {**existing, **body}
        secret_action = str(body.get("secret_action") or "keep")
        result = registry_service.save_connection(
            _connection_draft(merged, api_key=body.get("api_key")),
            connection_id=connection_id,
            secret_action=secret_action,
            expected_revision=body.get("revision"),
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/connections/<connection_id>/discover", methods=["POST"])
def discover_connection_models(connection_id: str):
    try:
        connection = registry_service.get_connection(connection_id)
        api_key = registry_service.resolve_connection_secret(connection_id)
        draft = _connection_draft(connection, api_key=api_key)
        result = detect_connection(draft)
        return _success(result.to_dict())
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/connections/<connection_id>/test", methods=["POST"])
def test_connection(connection_id: str):
    return discover_connection_models(connection_id)


@models_bp.route("/connections/<connection_id>", methods=["DELETE"])
def delete_connection(connection_id: str):
    """删除连接（级联删除其模型条目与密钥）。"""
    try:
        result = registry_service.delete_connection(
            connection_id=connection_id,
            expected_revision=request.args.get("revision", type=int),
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/entries", methods=["POST"])
def create_model_entry():
    try:
        body = _json_body()
        draft = ModelEntryDraft(
            name=str(body.get("name") or body.get("model_id") or "").strip(),
            connection_id=body.get("connection_id"),
            model_id=str(body.get("model_id") or "").strip(),
            capabilities=list(body.get("capabilities") or ["chat"]),
            verified=bool(body.get("verified", False)),
            metadata=body.get("metadata") or {},
            local_path=body.get("local_path"),
        )
        result = registry_service.save_model_entry(
            draft, expected_revision=body.get("revision")
        )
        return _success(result, 201)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/entries/<entry_id>/test", methods=["POST"])
def test_model_entry(entry_id: str):
    """对单个模型条目执行最小聊天测试，成功后标记为已验证。"""
    try:
        entry = registry_service.get_model_entry(entry_id)
        if not entry:
            raise ValueError("模型条目不存在")
        if "chat" not in entry.get("capabilities", []):
            raise ValueError("该模型未声明聊天能力，无法测试")
        connection = registry_service.get_connection(entry["connection_id"])
        if not connection:
            raise ValueError("模型关联的连接不存在")
        api_key = registry_service.resolve_connection_secret(entry["connection_id"])

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=connection["endpoint"])
        response = client.chat.completions.create(
            model=entry["model_id"],
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=8,
            temperature=0,
            timeout=30,
        )
        content = response.choices[0].message.content if response.choices else ""
        if not content or not content.strip():
            raise ValueError("模型返回了空响应，请重试或更换模型")

        result = registry_service.save_model_entry(
            ModelEntryDraft(
                name=entry["name"],
                connection_id=entry["connection_id"],
                model_id=entry["model_id"],
                capabilities=entry.get("capabilities", ["chat"]),
                verified=True,
                metadata={**(entry.get("metadata") or {}), "verified_at": "now"},
                local_path=entry.get("local_path"),
            ),
            model_id=entry_id,
            expected_revision=registry_service.get_redacted_registry()["revision"],
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/entries/<entry_id>", methods=["DELETE"])
def delete_model_entry(entry_id: str):
    """删除模型条目（若被项目绑定、预设或快照引用则拒绝）。"""
    try:
        result = registry_service.delete_model_entry(
            model_entry_id=entry_id,
            expected_revision=request.args.get("revision", type=int),
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/presets", methods=["POST"])
def create_preset():
    try:
        body = _json_body()
        result = registry_service.save_preset(
            preset_id=str(body.get("id") or "").strip(),
            name=str(body.get("name") or "").strip(),
            bindings=RoleBindings.from_dict(body.get("roles") or {}),
            expected_revision=body.get("revision"),
        )
        return _success(result, 201)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/presets/<preset_id>", methods=["DELETE"])
def delete_preset(preset_id: str):
    """删除预设。"""
    try:
        result = registry_service.delete_preset(
            preset_id=preset_id,
            expected_revision=request.args.get("revision", type=int),
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/projects/<project_id>/bindings", methods=["GET"])
def get_project_bindings(project_id: str):
    bindings = registry_service.get_project_bindings(project_id)
    return _success({"project_id": project_id, "roles": bindings.to_dict() if bindings else {}})


@models_bp.route("/projects/<project_id>/bindings", methods=["PUT"])
def update_project_bindings(project_id: str):
    try:
        body = _json_body()
        result = registry_service.save_project_bindings(
            project_id=project_id,
            bindings=RoleBindings.from_dict(body.get("roles") or {}),
            expected_revision=body.get("revision"),
        )
        return _success(result)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/tasks/<owner_type>/<owner_id>/snapshot", methods=["POST"])
def create_task_snapshot(owner_type: str, owner_id: str):
    try:
        body = _json_body()
        roles = body.get("roles")
        if roles is None and owner_type == "project":
            project_bindings = registry_service.get_project_bindings(owner_id)
            roles = project_bindings.to_dict() if project_bindings else {}
        result = registry_service.create_snapshot(
            owner_type=owner_type,
            owner_id=owner_id,
            bindings=RoleBindings.from_dict(roles or {}),
            expected_revision=body.get("revision"),
        )
        return _success(result, 201)
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/tasks/<owner_type>/<owner_id>/snapshot/<snapshot_id>", methods=["GET"])
def get_task_snapshot(owner_type: str, owner_id: str, snapshot_id: str):
    try:
        snapshot = registry_service.get_snapshot(snapshot_id)
        if snapshot["owner_type"] != owner_type or snapshot["owner_id"] != owner_id:
            raise ValueError("模型快照不属于该任务")
        return _success(snapshot)
    except Exception as exc:
        return _handle_exception(exc)


# ==================== 本地向量模型 ====================


@models_bp.route("/local/scan", methods=["GET"])
def scan_local_models_route():
    """扫描 app/models/embeddings/ 下的本地向量模型目录。"""
    try:
        from ..services.local_embedding import LOCAL_MODELS_ROOT

        return _success({"models": scan_local_models(), "root": str(LOCAL_MODELS_ROOT)})
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/local/<name>/inspect", methods=["GET"])
def inspect_local_model_route(name: str):
    """读取单个本地模型元数据。"""
    try:
        return _success(inspect_local_model(name))
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/local/<name>/test", methods=["POST"])
def test_local_model_route(name: str):
    """真实加载本地模型并执行一次向量计算。"""
    try:
        return _success(probe_local_model(name))
    except Exception as exc:
        return _handle_exception(exc)


@models_bp.route("/local/<name>/register", methods=["POST"])
def register_local_model_route(name: str):
    """把本地模型注册为模型库条目（向量能力，无需连接）。

    同一本地目录重复注册时更新已有条目，而不是新增重复条目。
    """
    try:
        body = _json_body()
        info = inspect_local_model(name)
        fingerprint = compute_local_fingerprint(
            name=name,
            dimension=info.get("dimension"),
            max_length=info.get("max_length"),
            model_type=info.get("model_type"),
        )
        draft = ModelEntryDraft(
            name=str(body.get("name") or name).strip(),
            connection_id=None,
            model_id=name,
            capabilities=["embedding"],
            verified=bool(body.get("verified", True)),
            metadata={
                "dimension": info.get("dimension"),
                "max_length": info.get("max_length"),
                "model_type": info.get("model_type"),
                "local": True,
                "fingerprint": fingerprint,
            },
            local_path=name,
        )
        # 已注册过同一本地目录时更新，避免产生重复条目
        existing = None
        state = registry_service.get_redacted_registry()
        for entry in state.get("models", []):
            if entry.get("local_path") == name:
                existing = entry
                break
        if existing is not None:
            result = registry_service.save_model_entry(
                draft,
                model_id=existing["id"],
                expected_revision=body.get("revision"),
            )
            return _success(result)
        result = registry_service.save_model_entry(
            draft, expected_revision=body.get("revision")
        )
        return _success(result, 201)
    except Exception as exc:
        return _handle_exception(exc)
