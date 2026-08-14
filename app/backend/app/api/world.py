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
- POST   /api/world/<project_id>/report      生成世界报告（body: simulation_id）
- GET    /api/world/<project_id>/report/<simulation_id>  读取已生成的世界报告
- POST   /api/world/<project_id>/simulate/whatif  基于已有模拟做 what-if 分支推演
- DELETE /api/world/<project_id>            删除项目的世界设定库
"""

import os
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
    """
    提交背景/正文，重建设定库索引。至少一个非空。

    两种请求方式：
    1. multipart/form-data（推荐，支持多文件）：
       - background_files: 背景设定文档，可多个（pdf/md/txt）
       - story_files: 小说正文文件，可多个（pdf/md/txt）
       - background_text / story_text: 可选，额外的直接文本
       - chunk_size / chunk_overlap: 可选
    2. application/json（兼容旧版）：
       - background / story: 直接文本
    """
    try:
        from ..utils.file_parser import FileParser
        from ..utils.logger import get_logger as _get_logger
        _logger = _get_logger('mirofish.api.world')

        chunk_size = Config.DEFAULT_CHUNK_SIZE
        overlap = Config.DEFAULT_CHUNK_OVERLAP
        metadata = {}
        background_parts = []
        story_parts = []
        file_manifest = []

        # ---------------- multipart 多文件上传 ----------------
        if request.files:
            bg_files = request.files.getlist('background_files')
            st_files = request.files.getlist('story_files')
            all_files = bg_files + st_files

            for f in all_files:
                if not f or not f.filename:
                    continue
                # 校验扩展名（ALLOWED_EXTENSIONS 是不带点的集合）
                ext = os.path.splitext(f.filename)[1].lower().lstrip('.')
                if ext not in Config.ALLOWED_EXTENSIONS:
                    _logger.warning(f"跳过不支持的文件类型: {f.filename} ({ext})")
                    continue
                # 保存临时文件并提取文本
                import tempfile
                suffix = '.' + ext if ext else '.txt'
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                try:
                    text = FileParser.extract_text(tmp_path)
                    if f in bg_files:
                        background_parts.append(text)
                    else:
                        story_parts.append(text)
                    file_manifest.append({
                        "filename": f.filename,
                        "size": len(text),
                        "source": "background" if f in bg_files else "story",
                    })
                except Exception as e:
                    _logger.warning(f"解析文件失败 {f.filename}: {e}")
                finally:
                    os.unlink(tmp_path)

            # 可选的直接文本
            background_parts.append(request.form.get('background_text', ''))
            story_parts.append(request.form.get('story_text', ''))
            try:
                chunk_size = int(request.form.get('chunk_size', Config.DEFAULT_CHUNK_SIZE))
                overlap = int(request.form.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP))
            except (TypeError, ValueError):
                pass
            metadata = {"files": file_manifest}

        # ---------------- JSON 文本输入（兼容） ----------------
        else:
            data = request.get_json(silent=True) or {}
            background_parts.append(data.get('background', ''))
            story_parts.append(data.get('story', ''))
            chunk_size = int(data.get('chunk_size', Config.DEFAULT_CHUNK_SIZE))
            overlap = int(data.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP))
            metadata = data.get('metadata') or {}

        background = "\n\n".join(p for p in background_parts if p and p.strip())
        story = "\n\n".join(p for p in story_parts if p and p.strip())

        if not background.strip() and not story.strip():
            return jsonify({
                "success": False,
                "error": "背景文档和小说正文不能同时为空，请至少上传一个文件或输入一段文本"
            }), 400

        bible = WorldBibleService.save_input(
            project_id=project_id,
            background=background,
            story=story,
            chunk_size=chunk_size,
            overlap=overlap,
            metadata=metadata,
        )
        result = bible.stats()
        result["files"] = file_manifest
        return jsonify({"success": True, "stats": result})
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
    """按需检索设定块（关键词 + 可选语义向量融合）"""
    try:
        data = request.get_json(silent=True) or {}
        query = str(data.get('query', '')).strip()
        if not query:
            return jsonify({"success": False, "error": "查询内容不能为空"}), 400
        # semantic：true/缺省时启用语义+关键词融合；false 时仅关键词检索
        semantic = data.get('semantic', True)
        if isinstance(semantic, str):
            semantic = semantic.lower() in ('1', 'true', 'yes', 'on')
        results = WorldBibleService.search(
            project_id=project_id,
            query=query,
            source=data.get('source'),
            limit=int(data.get('limit', 8)),
            semantic=bool(semantic),
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


# ---------------------------------------------------------------- 世界模拟（独立模式）

@world_bp.route('/<project_id>/simulate', methods=['POST'])
def start_world_simulation(project_id: str):
    """
    启动世界模拟（独立模式，与社交模拟无关）

    请求（JSON）：
        {
            "total_steps": 6,          // 可选，模拟步数
            "time_step_minutes": 30    // 可选，每步模拟分钟数
        }
    """
    try:
        from ..services.world_simulation import WorldSimulationService

        data = request.get_json(silent=True) or {}
        total_steps = int(data.get('total_steps', 6))
        time_step_minutes = int(data.get('time_step_minutes', 30))

        state = WorldSimulationService.start_simulation(
            project_id=project_id,
            total_steps=total_steps,
            time_step_minutes=time_step_minutes,
        )
        return jsonify({"success": True, "simulation": state.to_dict()})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"启动世界模拟失败: {e}")
        return jsonify({"success": False, "error": f"启动失败: {e}"}), 500


@world_bp.route('/<project_id>/simulations', methods=['GET'])
def list_world_simulations(project_id: str):
    """列出项目的世界模拟记录"""
    try:
        from ..services.world_simulation import WorldSimulationService
        sims = WorldSimulationService.list_simulations(project_id)
        return jsonify({"success": True, "simulations": sims})
    except Exception as e:
        logger.error(f"列出世界模拟失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@world_bp.route('/<project_id>/simulation/<simulation_id>', methods=['GET'])
def get_world_simulation(project_id: str, simulation_id: str):
    """查询单个世界模拟的状态与结果"""
    try:
        from ..services.world_simulation import WorldSimulationService
        state = WorldSimulationService.get_state(simulation_id)
        if state is None or state.project_id != project_id:
            return jsonify({"success": False, "error": "模拟不存在"}), 404
        return jsonify({"success": True, "simulation": state.to_dict()})
    except Exception as e:
        logger.error(f"查询世界模拟失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@world_bp.route('/<project_id>/simulation/<simulation_id>/control', methods=['POST'])
def control_world_simulation(project_id: str, simulation_id: str):
    """
    世界模拟控制（暂停/恢复/停止/采访）

    请求（JSON）：
        {
            "action": "pause" | "resume" | "stop" | "interview",
            "character_name": "角色名或id",   // interview 必填
            "prompt": "采访问题"              // interview 必填
        }

    返回：
        interview 成功：{"success": true, "command_id": ..., "action": ..., "result": {...}}
        其余动作：{"success": true, "command_id": ..., "action": ...}
    """
    try:
        from ..services.world_simulation import WorldSimulationService

        data = request.get_json(silent=True) or {}
        action = str(data.get('action', '')).strip()
        if action not in ('pause', 'resume', 'stop', 'interview'):
            return jsonify({
                "success": False,
                "error": "action 必须是 pause/resume/stop/interview",
            }), 400

        result = WorldSimulationService.control_simulation(
            project_id=project_id,
            simulation_id=simulation_id,
            action=action,
            character_name=data.get('character_name'),
            prompt=data.get('prompt'),
        )
        response_body = {"success": True, **result}
        return jsonify(response_body)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except TimeoutError as e:
        logger.error(f"世界模拟采访超时: {e}")
        return jsonify({"success": False, "error": str(e)}), 504
    except Exception as e:
        logger.error(f"世界模拟控制失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------- what-if 推演

@world_bp.route('/<project_id>/simulate/whatif', methods=['POST'])
def simulate_whatif(project_id: str):
    """
    基于一条已有模拟做 what-if 分支推演

    请求（JSON）：
        {
            "base_simulation_id": "xxx",    // 必填，基础模拟
            "question": "若魔法不需要代价？", // 必填，假设前提
            "steps": 3                       // 可选，推演步数
        }

    返回：新分支模拟的状态（含 result.meta.whatif_base / whatif_question）
    """
    try:
        from ..services.world_simulation import WorldSimulationService

        data = request.get_json(silent=True) or {}
        base_simulation_id = str(data.get('base_simulation_id', '')).strip()
        question = str(data.get('question', '')).strip()
        steps = int(data.get('steps', 3))

        state = WorldSimulationService.simulate_whatif(
            base_simulation_id=base_simulation_id,
            question=question,
            steps=steps,
        )
        return jsonify({"success": True, "simulation": state.to_dict()})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"what-if 推演失败: {e}")
        return jsonify({"success": False, "error": f"推演失败: {e}"}), 500


# ---------------------------------------------------------------- 世界报告

@world_bp.route('/<project_id>/report', methods=['POST'])
def generate_world_report(project_id: str):
    """
    生成世界模拟报告（编年史/推演报告）

    请求（JSON）：
        {
            "simulation_id": "xxx"   // 必填，目标世界模拟
        }

    返回：
        {
            "success": true,
            "report": {"text": "<Markdown>", "sections": [{"title","content"}]}
        }
    """
    try:
        from ..services.world_report import WorldReportService

        data = request.get_json(silent=True) or {}
        simulation_id = str(data.get('simulation_id', '')).strip()
        if not simulation_id:
            return jsonify({"success": False, "error": "simulation_id 不能为空"}), 400

        report = WorldReportService.generate_report(project_id, simulation_id)
        return jsonify({"success": True, "report": report})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error(f"生成世界报告失败: {e}")
        return jsonify({"success": False, "error": f"生成报告失败: {e}"}), 500


@world_bp.route('/<project_id>/report/<simulation_id>', methods=['GET'])
def get_world_report(project_id: str, simulation_id: str):
    """读取已生成的世界报告"""
    try:
        from ..services.world_report import WorldReportService

        report = WorldReportService.load_report(project_id, simulation_id)
        if report is None:
            return jsonify({"success": False, "error": "报告尚未生成"}), 404
        return jsonify({"success": True, "report": report})
    except Exception as e:
        logger.error(f"读取世界报告失败: {e}")
        return jsonify({"success": False, "error": f"读取报告失败: {e}"}), 500


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
