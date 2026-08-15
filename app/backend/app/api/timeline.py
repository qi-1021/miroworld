"""
时间线（Timeline）API

契约（blueprint: timeline，url_prefix=/api/timeline）：
- POST   /api/timeline/extract       抽取触发（后台任务）  body {project_id, source: story|bg}
- GET    /api/timeline/status?task_id 查询任务进度
- GET    /api/timeline/<project_id>?source=story|bg  获取时间线（sort_lower 升序）
- PATCH  /api/timeline/<project_id>/<event_id>  人工修正/重排（部分字段）
- POST   /api/timeline/future        LLM 生成未来事件追加  body {project_id, goal, horizon?}

注意：/status、/extract、/future 等静态路由必须在动态路由 /<project_id> 之前注册，
否则会被动态路由吞掉（历史教训：/api/simulation/history 曾被吞成 404）。
"""
from flask import request, jsonify

from . import timeline_bp
from ..services import timeline_service
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.timeline')


# ---------------------------------------------------------------------------
# 静态路由（必须先于动态路由）
# ---------------------------------------------------------------------------
@timeline_bp.route('/extract', methods=['POST'])
def extract():
    """触发时间线抽取（后台任务，逐块抽取）。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get('project_id') or '').strip()
        source = str(data.get('source') or 'story').strip()
        task_id = timeline_service.start_extract(project_id, source)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"触发时间线抽取失败: {e}")
        return jsonify({"success": False, "error": f"抽取失败: {e}"}), 500


@timeline_bp.route('/status', methods=['GET'])
def status():
    """查询抽取进度。"""
    task_id = str(request.args.get('task_id') or '').strip()
    if not task_id:
        return jsonify({"success": False, "error": "缺少 task_id"}), 400
    st = timeline_service.get_status(task_id)
    if not st:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    return jsonify({"success": True, "data": st})


@timeline_bp.route('/future', methods=['POST'])
def future():
    """LLM 生成 kind='future' 事件追加到时间线；复用 /status 轮询。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get('project_id') or '').strip()
        goal = str(data.get('goal') or '').strip()
        horizon = data.get('horizon')
        if horizon is not None:
            try:
                horizon = int(horizon)
            except (TypeError, ValueError):
                horizon = None
        task_id = timeline_service.start_future(project_id, goal, horizon)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"生成未来事件失败: {e}")
        return jsonify({"success": False, "error": f"未来事件生成失败: {e}"}), 500


@timeline_bp.route('/fork', methods=['POST'])
def fork():
    """在某个历史事件点分叉做未来推演（后台任务）；复用 /status 轮询。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get('project_id') or '').strip()
        event_id = str(data.get('event_id') or '').strip()
        goal = str(data.get('goal') or '').strip()
        horizon = data.get('horizon')
        if horizon is not None:
            try:
                horizon = int(horizon)
            except (TypeError, ValueError):
                horizon = None
        task_id = timeline_service.start_fork(project_id, event_id, goal, horizon)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"发起分叉推演失败: {e}")
        return jsonify({"success": False, "error": f"分叉推演失败: {e}"}), 500


# ---------------------------------------------------------------------------
# 动态路由
# ---------------------------------------------------------------------------
@timeline_bp.route('/<project_id>', methods=['GET'])
def get_timeline(project_id):
    """获取时间线（按 sort_lower 升序）。"""
    try:
        source = request.args.get('source', '')
        if source not in ('story', 'bg', ''):
            return jsonify({"success": False, "error": "source 必须是 story 或 bg"}), 400
        # 读取全部事件；指定 source 时附带世界级未来事件（kind='future'），
        # 保证时间条的虚线未来区在 story/bg 两个标签页下都可见。
        data = timeline_service.load_timeline(project_id, None)
        all_events = data.get('events', [])
        if source:
            events = [
                e for e in all_events
                if e.get('source') == source
                or e.get('kind') in ('future', 'branch')
                or e.get('source') in ('future', 'branch')
            ]
        else:
            events = all_events
        events = sorted(events, key=lambda e: (e.get('sort_lower') or 0))
        return jsonify({
            "success": True,
            "data": {"project_id": project_id, "source": source, "events": events},
            "count": len(events),
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"读取时间线失败: {e}")
        return jsonify({"success": False, "error": f"读取失败: {e}"}), 500


@timeline_bp.route('/<project_id>/<event_id>', methods=['PATCH'])
def patch_event(project_id, event_id):
    """人工修正/重排一条事件，持久化。"""
    try:
        body = request.get_json(silent=True) or {}
        updated = timeline_service.patch_event(project_id, event_id, body)
        if updated is None:
            return jsonify({"success": False, "error": "事件不存在"}), 404
        return jsonify({"success": True, "data": updated})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"更新时间线事件失败: {e}")
        return jsonify({"success": False, "error": f"更新失败: {e}"}), 500


@timeline_bp.route('/<project_id>/<event_id>/objection', methods=['POST'])
def submit_objection(project_id, event_id):
    """对一条事件提交异议（归属/分类/时间/地点等）。"""
    try:
        body = request.get_json(silent=True) or {}
        updated = timeline_service.add_objection(
            project_id,
            event_id,
            category=str(body.get('category') or '').strip(),
            reason=str(body.get('reason') or '').strip(),
            suggestion=body.get('suggestion'),
        )
        if updated is None:
            return jsonify({"success": False, "error": "事件不存在"}), 404
        return jsonify({"success": True, "data": updated})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"提交事件异议失败: {e}")
        return jsonify({"success": False, "error": f"提交异议失败: {e}"}), 500
