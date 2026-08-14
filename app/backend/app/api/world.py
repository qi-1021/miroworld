"""
世界输入与设定库 API

端点：
- POST   /api/world/<project_id>/input      提交背景/正文（至少一个），重建设定库索引
- GET    /api/world/<project_id>/settings   查询设定库统计
- GET    /api/world/<project_id>/chunks     列出设定库分块（可按 source 过滤）
- POST   /api/world/<project_id>/search     按需检索设定块（有限筛选）
- POST   /api/world/<project_id>/conflicts/detect   运行冲突检测（异步任务）
- GET    /api/world/<project_id>/conflicts  获取最近一次冲突检测报告
- PATCH  /api/world/<project_id>/conflicts/<conflict_id>  更新冲突状态（open/accepted/dismissed）
- DELETE /api/world/<project_id>            删除项目的世界设定库
"""

import threading
from flask import request, jsonify

from . import world_bp
from ..config import Config
from ..utils.logger import get_logger
from ..models.task import TaskManager, TaskStatus
from ..services.world_bible import WorldBibleService
from ..services.conflict_detector import (
    ConflictDetector,
    save_conflict_report,
    load_conflict_report,
)
from ..utils.llm_client import LLMClient

logger = get_logger('mirofish.api.world')

# 全局任务管理器（与 graph/simulation 共用模式）
task_manager = TaskManager()


def _build_llm_client_for_project(project_id: str) -> LLMClient:
    """优先使用项目绑定的已验证模型，其次注册表第一个已验证 chat 模型，最后回退旧配置。"""
    try:
        from ..services.model_registry import ModelRegistryService
        from ..services.model_resolver import ModelResolver
        from ..models.model_config import ModelRole

        registry = ModelRegistryService()
        bindings = registry.get_project_bindings(project_id)
        if bindings and bindings.to_dict().get(ModelRole.PRIMARY.value):
            snapshot = registry.create_snapshot(
                owner_type="project",
                owner_id=project_id,
                bindings=bindings,
                expected_revision=None,
            )
            resolved = ModelResolver(registry).resolve_chat(ModelRole.PRIMARY, snapshot["id"])
            return LLMClient(
                api_key=resolved.api_key,
                base_url=resolved.endpoint,
                model=resolved.model_id,
            )
    except Exception as e:
        logger.warning(f"使用项目绑定模型失败，尝试注册表回退: {e}")

    # 注册表回退：第一个已验证的 chat 模型（与 Graphiti 解析策略一致）
    try:
        from ..services.zep_graphiti_impl import GraphitiClient
        resolved = GraphitiClient._resolve_registry_chat_model()
        if resolved:
            api_key, base_url, model = resolved
            return LLMClient(api_key=api_key, base_url=base_url, model=model)
    except Exception as e:
        logger.warning(f"注册表模型回退失败，使用默认配置: {e}")

    return LLMClient()


# ---------------------------------------------------------------- 输入与设定库

@world_bp.route('/<project_id>/input', methods=['POST'])
def save_world_input(project_id: str):
    """提交背景/正文（JSON），重建设定库索引。至少一个非空。"""
    try:
        data = request.get_json(silent=True) or {}
        background = data.get('background', '')
        story = data.get('story', '')
        chunk_size = int(data.get('chunk_size', Config.DEFAULT_CHUNK_SIZE))
        overlap = int(data.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP))
        metadata = data.get('metadata') or {}

        bible = WorldBibleService.save_input(
            project_id=project_id,
            background=background,
            story=story,
            chunk_size=chunk_size,
            overlap=overlap,
            metadata=metadata,
        )
        return jsonify({"success": True, "stats": bible.stats()})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"保存世界输入失败: {e}")
        return jsonify({"success": False, "error": f"保存失败: {e}"}), 500


@world_bp.route('/<project_id>/settings', methods=['GET'])
def get_world_settings(project_id: str):
    """查询设定库统计信息"""
    stats = WorldBibleService.get_stats(project_id)
    if stats is None:
        return jsonify({"success": True, "stats": None}), 200
    return jsonify({"success": True, "stats": stats})


@world_bp.route('/<project_id>/chunks', methods=['GET'])
def list_world_chunks(project_id: str):
    """列出设定库分块"""
    bible = WorldBibleService.get_bible(project_id)
    if bible is None:
        return jsonify({"success": True, "chunks": []}), 200
    source = request.args.get('source')  # 'background' | 'story' | None
    limit = int(request.args.get('limit', 50))
    chunks = []
    for c in bible.chunks:
        if source and c.source != source:
            continue
        chunks.append(c.to_dict())
        if len(chunks) >= limit:
            break
    return jsonify({"success": True, "chunks": chunks, "total": len(bible.chunks)})


@world_bp.route('/<project_id>/search', methods=['POST'])
def search_world(project_id: str):
    """按需检索设定块（有限筛选）"""
    try:
        data = request.get_json(silent=True) or {}
        query = str(data.get('query', '')).strip()
        if not query:
            return jsonify({"success": False, "error": "查询内容不能为空"}), 400
        results = WorldBibleService.search(
            project_id=project_id,
            query=query,
            source=data.get('source'),
            limit=int(data.get('limit', 8)),
        )
        return jsonify({"success": True, "results": results})
    except Exception as e:
        logger.error(f"检索失败: {e}")
        return jsonify({"success": False, "error": f"检索失败: {e}"}), 500


# ---------------------------------------------------------------- 冲突检测

@world_bp.route('/<project_id>/conflicts/detect', methods=['POST'])
def detect_conflicts(project_id: str):
    """运行冲突检测（异步任务，返回 task_id）"""
    bible = WorldBibleService.get_bible(project_id)
    if bible is None or (not bible.background_text.strip() and not bible.story_text.strip()):
        return jsonify({"success": False, "error": "尚未提交世界输入，无法检测冲突"}), 400
    if not bible.background_text.strip() or not bible.story_text.strip():
        return jsonify({"success": False, "error": "冲突检测需要同时有背景文档和小说正文"}), 400

    task_id = task_manager.create_task(
        task_type="world_conflict_detect",
        metadata={"project_id": project_id},
    )

    def run_detect():
        try:
            task_manager.update_task(
                task_id, status=TaskStatus.PROCESSING,
                message="开始冲突检测...", progress=5,
            )
            detector = ConflictDetector(llm_client=_build_llm_client_for_project(project_id))

            def progress_cb(phase: str, progress: int):
                task_manager.update_task(task_id, message=phase, progress=progress)

            report = detector.detect_with_progress(
                project_id=project_id,
                background_text=bible.background_text,
                story_text=bible.story_text,
                progress_cb=progress_cb,
            )
            if report.status == "failed":
                task_manager.fail_task(task_id, report.error or "冲突检测失败")
                return

            save_conflict_report(project_id, report)
            task_manager.complete_task(task_id, result={"conflict_count": len(report.conflicts)})
        except Exception as e:
            logger.error(f"冲突检测任务失败: {e}")
            task_manager.fail_task(task_id, str(e))

    threading.Thread(target=run_detect, daemon=True).start()
    return jsonify({"success": True, "task_id": task_id})


@world_bp.route('/<project_id>/conflicts', methods=['GET'])
def get_conflicts(project_id: str):
    """获取最近一次冲突检测报告"""
    report = load_conflict_report(project_id)
    if report is None:
        return jsonify({"success": True, "report": None}), 200
    return jsonify({"success": True, "report": report.to_dict()})


@world_bp.route('/<project_id>/conflicts/<conflict_id>', methods=['PATCH'])
def update_conflict_status(project_id: str, conflict_id: str):
    """更新冲突处理状态（open/accepted/dismissed）"""
    try:
        data = request.get_json(silent=True) or {}
        status = str(data.get('status', '')).strip()
        if status not in ('open', 'accepted', 'dismissed'):
            return jsonify({"success": False, "error": "状态必须是 open/accepted/dismissed"}), 400

        report = load_conflict_report(project_id)
        if report is None:
            return jsonify({"success": False, "error": "没有可更新的冲突报告"}), 404

        updated = False
        for c in report.conflicts:
            if c.conflict_id == conflict_id:
                c.status = status
                updated = True
                break
        if not updated:
            return jsonify({"success": False, "error": "冲突不存在"}), 404

        save_conflict_report(project_id, report)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"更新冲突状态失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------- 删除

@world_bp.route('/<project_id>', methods=['DELETE'])
def delete_world_data(project_id: str):
    """删除项目的世界设定库与冲突报告"""
    try:
        WorldBibleService.delete(project_id)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"删除世界数据失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
