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
from flask import request, jsonify, send_file

from . import timeline_bp
from ..services import timeline_service
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.timeline')


# ---------------------------------------------------------------------------
# 静态路由（必须先于动态路由）
# ---------------------------------------------------------------------------
@timeline_bp.route('/extract', methods=['POST'])
def extract():
    """触发时间线抽取（后台任务，逐块抽取）。

    body:
        project_id: str 必填
        source: 'story' | 'bg'，默认 story
        resume: bool 可选，true 时从上次断点续跑
    """
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get('project_id') or '').strip()
        source = str(data.get('source') or 'story').strip()
        resume = bool(data.get('resume', False))
        task_id = timeline_service.start_extract(project_id, source, resume=resume)
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


def _as_guidance_list(raw):
    """把 guidance（可能为字符串或数组）规范化为 List[str]。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    return [str(raw)] if str(raw).strip() else []


@timeline_bp.route('/fork', methods=['POST'])
def fork():
    """在某个历史事件点分叉做未来推演（后台任务，支持 guidance 注入）；复用 /status 轮询。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get('project_id') or '').strip()
        event_id = str(data.get('event_id') or '').strip()
        goal = str(data.get('goal') or '').strip()
        guidance = _as_guidance_list(data.get('guidance'))
        horizon = data.get('horizon')
        if horizon is not None:
            try:
                horizon = int(horizon)
            except (TypeError, ValueError):
                horizon = None
        task_id = timeline_service.start_fork(project_id, event_id, goal, horizon, guidance)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"发起分叉推演失败: {e}")
        return jsonify({"success": False, "error": f"分叉推演失败: {e}"}), 500


@timeline_bp.route('/fork/guidance', methods=['POST'])
def fork_guidance():
    """对运行中的 fork 任务注入/追加 guidance。
    任务不存在 → 404；非 running / guidance 非法 → 400。"""
    try:
        data = request.get_json(silent=True) or {}
        task_id = str(data.get('task_id') or '').strip()
        guidance = str(data.get('guidance') or '').strip()
        # 先判任务是否存在，区分 404/400
        if not timeline_service.get_status(task_id):
            return jsonify({"success": False, "error": "任务不存在"}), 404
        result = timeline_service.inject_fork_guidance(task_id, guidance)
        return jsonify({"success": True, "data": result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"注入分叉 guidance 失败: {e}")
        return jsonify({"success": False, "error": f"注入失败: {e}"}), 500


@timeline_bp.route('/<project_id>/batch', methods=['POST'])
def batch_events(project_id):
    """批量操作时间线事件。

    body: { action: "delete"|"update", event_ids: [...], patch?: {...} }
    - delete: 删除指定事件（不级联删分支）
    - update: 用 patch 批量更新（白名单字段：summary/source/kind/ev_type/
      location_name/location_text/time_text/time_kind/age/year/characters/confidence/sort_lower）
    """
    try:
        data = request.get_json(silent=True) or {}
        action = str(data.get('action') or '').strip()
        event_ids = data.get('event_ids') or []
        if not isinstance(event_ids, list):
            return jsonify({"success": False, "error": "event_ids 必须是数组"}), 400
        patch = data.get('patch')
        result = timeline_service.batch_events(project_id, action, event_ids, patch)
        return jsonify({"success": True, "data": result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"批量操作时间线失败: {e}")
        return jsonify({"success": False, "error": f"批量操作失败: {e}"}), 500


@timeline_bp.route('/<project_id>/threads', methods=['GET'])
def get_threads(project_id):
    """获取背景时间线线索清单（第一遍识别结果，可能为空）。"""
    try:
        threads = timeline_service.load_threads(project_id)
        return jsonify({"success": True, "data": {"project_id": project_id, "threads": threads}, "count": len(threads)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"读取时间线线索失败: {e}")
        return jsonify({"success": False, "error": f"读取失败: {e}"}), 500


@timeline_bp.route('/<project_id>/structure', methods=['GET'])
def get_structure(project_id):
    """获取时间线结构类型判断结果（single/parallel/tree/network/meta/mixed；可能为 null）。

    前端据此展示结构视图与抽取策略信息。
    """
    try:
        structure = timeline_service.load_structure(project_id)
        return jsonify({"success": True, "data": {"project_id": project_id, "structure": structure}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"读取时间线结构类型失败: {e}")
        return jsonify({"success": False, "error": f"读取失败: {e}"}), 500


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


@timeline_bp.route('/<project_id>/branch/continue', methods=['POST'])
def branch_continue(project_id):
    """从某分支当前末尾续推后续事件（后台任务）；复用 /status 轮询。"""
    try:
        data = request.get_json(silent=True) or {}
        branch_id = str(data.get('branch_id') or '').strip()
        # guidance 必填（Str 或 List[str]），去除空项
        guidance = _as_guidance_list(data.get('guidance'))
        if not guidance:
            return jsonify({"success": False, "error": "guidance 不能为空"}), 400
        if not timeline_service.branch_exists(project_id, branch_id):
            return jsonify({"success": False, "error": "分支不存在"}), 404
        horizon = data.get('horizon')
        if horizon is not None:
            try:
                horizon = int(horizon)
            except (TypeError, ValueError):
                horizon = None
        task_id = timeline_service.start_branch_continue(project_id, branch_id, list(guidance), horizon)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"发起分支续推失败: {e}")
        return jsonify({"success": False, "error": f"续推失败: {e}"}), 500


@timeline_bp.route('/<project_id>/branch/compare', methods=['GET'])
def compare_branch(project_id):
    """对比某分支与主线的差异（before/base_only/changed/branch_new 分类）。"""
    try:
        branch_id = str(request.args.get('branch_id') or '').strip()
        if not branch_id:
            return jsonify({"success": False, "error": "缺少 branch_id"}), 400
        result = timeline_service.compare_branch(project_id, branch_id)
        if result is None:
            return jsonify({"success": False, "error": "分支不存在"}), 404
        return jsonify({
            "success": True,
            "data": result,
            "count": len(result.get("entries", [])),
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"对比分支失败: {e}")
        return jsonify({"success": False, "error": f"对比失败: {e}"}), 500


@timeline_bp.route('/<project_id>/final-report', methods=['POST'])
def generate_final_report(project_id):
    """（重新）生成项目的最终时间线报告：梗概 + 小说正文（确定性聚合，不联网）。

    返回 { success, data: { project_id, generated_at, format,
    deterministic, goal, structure, best_flow, events_count, synopsis, novel } }。
    """
    try:
        from ..services import timeline_report
        report = timeline_report.generate_report(project_id)
        return jsonify({"success": True, "data": report})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"生成最终时间线报告失败: {e}")
        return jsonify({"success": False, "error": f"生成失败: {e}"}), 500


@timeline_bp.route('/<project_id>/final-report', methods=['GET'])
def get_final_report(project_id):
    """读取已生成的项目最终时间线报告；未生成返回 200 + has_report=false。"""
    try:
        from ..services import timeline_report
        report = timeline_report.load_report(project_id)
        if report is None:
            return jsonify({
                "success": True,
                "data": {
                    "project_id": project_id,
                    "has_report": False,
                },
            })
        report["has_report"] = True
        return jsonify({"success": True, "data": report})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"读取最终时间线报告失败: {e}")
        return jsonify({"success": False, "error": f"读取失败: {e}"}), 500


@timeline_bp.route('/<project_id>/final-report/download', methods=['GET'])
def download_final_report(project_id):
    """下载项目最终时间线报告的 Markdown 文件。"""
    import os
    try:
        from ..services import timeline_report
        report = timeline_report.load_report(project_id)
        if report is None:
            return jsonify({"success": False, "error": "报告尚未生成，请先 POST 生成"}), 404
        md_path = timeline_report._report_md_path(project_id)
        if not os.path.exists(md_path):
            # 兜底：临时渲染并返回
            from flask import make_response
            resp = make_response(timeline_report.render_markdown(report))
            resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
            resp.headers["Content-Disposition"] = "attachment; filename=final-report.md"
            return resp
        return send_file(
            md_path,
            as_attachment=True,
            download_name=f"final-report-{project_id}.md",
            mimetype="text/markdown",
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"下载最终时间线报告失败: {e}")
        return jsonify({"success": False, "error": f"下载失败: {e}"}), 500


@timeline_bp.route('/<project_id>/characters', methods=['GET'])
def get_characters(project_id):
    """获取人物设定档案；空则从事件自动种子。"""
    try:
        profiles = timeline_service.ensure_characters(project_id)
        return jsonify({"success": True, "data": {"project_id": project_id, "characters": profiles}, "count": len(profiles)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"读取人物设定失败: {e}")
        return jsonify({"success": False, "error": f"读取失败: {e}"}), 500


@timeline_bp.route('/<project_id>/characters', methods=['PUT'])
def put_characters(project_id):
    """保存人物设定档案（name 非空否则 400）。"""
    try:
        data = request.get_json(silent=True) or {}
        raw = data.get('characters') or []
        if not isinstance(raw, list):
            return jsonify({"success": False, "error": "characters 必须是数组"}), 400
        if not any(isinstance(it, dict) and (it.get('name') or '').strip() for it in raw):
            return jsonify({"success": False, "error": "characters 至少需要一个非空 name"}), 400
        saved = timeline_service.save_characters(project_id, raw)
        if not saved:
            return jsonify({"success": False, "error": "保存人物设定失败"}), 500
        return jsonify({"success": True, "data": {"project_id": project_id, "characters": timeline_service.load_characters(project_id)}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"保存人物设定失败: {e}")
        return jsonify({"success": False, "error": f"保存失败: {e}"}), 500


@timeline_bp.route('/<project_id>/characters/generate', methods=['POST'])
def generate_characters(project_id):
    """异步生成人物设定初稿（后台任务）；复用 /status 轮询。"""
    try:
        task_id = timeline_service.start_characters_generate(project_id)
        return jsonify({"success": True, "data": {"task_id": task_id}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"触发人物设定生成失败: {e}")
        return jsonify({"success": False, "error": f"生成失败: {e}"}), 500


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


@timeline_bp.route('/<project_id>/<event_id>', methods=['DELETE'])
def delete_event(project_id, event_id):
    """删除一条事件（仅删该事件，不级联删分支）。"""
    try:
        deleted = timeline_service.delete_event(project_id, event_id)
        if not deleted:
            return jsonify({"success": False, "error": "事件不存在"}), 404
        return jsonify({"success": True, "data": {"deleted": True}})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"删除事件失败: {e}")
        return jsonify({"success": False, "error": f"删除失败: {e}"}), 500


@timeline_bp.route('/<project_id>/merge', methods=['POST'])
def merge_events(project_id):
    """把若干 source 事件合并进 target 事件，删除 source，返回合并后 target。"""
    try:
        body = request.get_json(silent=True) or {}
        target_id = str(body.get('target_id') or '').strip()
        source_ids = body.get('source_ids') or []
        if not isinstance(source_ids, list) or not [s for s in source_ids if str(s).strip()]:
            return jsonify({"success": False, "error": "source_ids 必须是非空数组"}), 400
        merged = timeline_service.merge_events(
            project_id, target_id,
            [str(s).strip() for s in source_ids if str(s).strip()],
        )
        if merged is None:
            return jsonify({"success": False, "error": "target 或 source 事件不存在"}), 404
        return jsonify({"success": True, "data": merged})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"合并事件失败: {e}")
        return jsonify({"success": False, "error": f"合并失败: {e}"}), 500


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
