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
    DefenseRound,
    save_conflict_report,
    load_conflict_report,
    load_conflict,
)
from ..services.conflict_correction import (
    ConflictCorrectionService,
    load_corrections,
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


# ---------------------------------------------------------------- 用途模式

@world_bp.route('/modes', methods=['GET'])
def list_modes():
    """
    列出可用的用途模式（novel-world / character-card / timeline 等）。

    供前端在选择"世界/Miroworld 用途"时展示。模式经 POST /api/world/<id>/input
    的可选 mode 参数透传进 metadata['mode']。

    返回：
        { "success": true, "modes": [ {key,label,inputs,pipeline,artifacts}, ... ] }
    """
    try:
        from ..services.mode_registry import get_modes
        return jsonify({"success": True, "modes": get_modes()})
    except Exception as e:
        logger.error(f"读取用途模式失败: {e}")
        return jsonify({"success": False, "error": f"读取模式失败: {e}"}), 500


@world_bp.route('/simulations/orphans', methods=['GET'])
def list_orphan_world_simulations():
    """列出 data/world-sim 下全部孤儿/空世界模拟（归属项目不存在，可安全删除）。

    返回：
        { "success": true, "orphans": [{project_id, simulation_id, status, created_at, has_events}], "count": N }
    """
    try:
        from ..services.world_simulation import WorldSimulationService
        orphans = WorldSimulationService.list_orphan_simulations(limit=200)
        return jsonify({"success": True, "orphans": orphans, "count": len(orphans)})
    except Exception as e:
        logger.error(f"列出孤儿世界模拟失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@world_bp.route('/simulations/cleanup', methods=['POST'])
def cleanup_orphan_world_simulations():
    """清理 data/world-sim 下全部孤儿/空世界模拟。

    请求（JSON，可选）：
        { "dry_run": true }   // true 时只统计不删除（默认 false 实际删除）

    返回：
        { "success": true, "scan": N, "removed": N, "skipped": N }
    """
    try:
        data = request.get_json(silent=True) or {}
        from ..services.world_simulation import WorldSimulationService
        result = WorldSimulationService.cleanup_orphans(dry_run=bool(data.get('dry_run', False)))
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"清理孤儿世界模拟失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
        # 注意：request.files 在"只填文本、不上传文件"时为空，
        # 必须同时检查 request.form，否则纯文本 multipart 请求会落到 JSON 分支。
        if request.files or request.form:
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
            # 任务目标（可选）：作为世界推演的默认目标
            goal = (request.form.get('goal') or '').strip()
            if goal:
                metadata["goal"] = goal
            # 用途模式（可选）：透传进 metadata，不改变现有处理逻辑
            mode = (request.form.get('mode') or '').strip()
            if mode:
                metadata["mode"] = mode

        # ---------------- JSON 文本输入（兼容） ----------------
        else:
            data = request.get_json(silent=True) or {}
            background_parts.append(data.get('background', ''))
            story_parts.append(data.get('story', ''))
            chunk_size = int(data.get('chunk_size', Config.DEFAULT_CHUNK_SIZE))
            overlap = int(data.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP))
            metadata = dict(data.get('metadata') or {})
            goal = str(data.get('goal') or '').strip()
            if goal:
                metadata["goal"] = goal
            mode = str(data.get('mode') or '').strip()
            if mode:
                metadata["mode"] = mode

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
        # 同步文件清单到项目元数据，使首页历史数据库能显示已上传资料，
        # 而不是总是“无资料”。文本-only 保存时不会清掉已有文件清单。
        try:
            from ..models.project import ProjectManager
            proj = ProjectManager.get_project(project_id)
            if proj is not None:
                existing = list(proj.files or [])
                seen_keys = {
                    (str(f.get("filename") or ""), str(f.get("source") or ""))
                    for f in existing
                }
                for item in file_manifest:
                    key = (
                        str(item.get("filename") or ""),
                        str(item.get("source") or ""),
                    )
                    if key not in seen_keys:
                        existing.append(item)
                        seen_keys.add(key)
                proj.files = existing
                proj.total_text_length = len(background) + len(story)
                ProjectManager.save_project(proj)
        except Exception as e:
            logger.warning(f"同步世界输入文件清单到项目元数据失败（忽略）: {e}")

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
    """查询设定库统计信息（含任务目标与世界图谱状态）"""
    stats = WorldBibleService.get_stats(project_id)
    if stats is None:
        return jsonify({"success": True, "stats": None}), 200
    # 附带世界知识图谱状态（若有）
    try:
        from ..models.project import ProjectManager
        project = ProjectManager.get_project(project_id)
        stats["graph_id"] = project.graph_id if project else None
        stats["graph_status"] = (
            project.status.value if project and project.status else None
        )
    except Exception:
        stats["graph_id"] = None
        stats["graph_status"] = None
    return jsonify({"success": True, "stats": stats})


# ---------------------------------------------------------------- 世界知识图谱

@world_bp.route('/<project_id>/graph/build', methods=['POST'])
def build_world_graph(project_id: str):
    """
    为世界设定库构建知识图谱（LLM 本体生成 + Graphiti/Neo4j 建图）。

    与媒体分析流程相同的建图管线，但文本来源是设定库（背景+正文）。
    构建完成后 project.graph_id 会被写入，世界模拟事件也会回写到该图谱。

    请求（JSON）：
        {
            "goal": "可选，任务目标（作为本体生成的上文）",
            "force": false,   // 已有图谱时是否强制重建
            "resume": false,  // 已有图谱且存在 build-progress 时，跳过已完成 chunk 续构建
            "skip_auto_refill": false,  // true 时建图完成后不自动启动补边
            "chunk_size": 1500,
            "chunk_overlap": 150,
            "batch_size": 4,     // 每批写入的块数，默认 4，可覆盖 1-16
            "max_workers": 1     // 批内并发数，默认 1（串行最稳），可覆盖 1-3
        }

    说明：分批写入时每完成一批立即 mark_chunks_done 落断点（build-progress），
    中断只丢当前在途批次，已完成批次可断点续建。批内逐条上报进度；
    max_workers>1 会并行处理（OpenCode 网关更宜保持 1）。

    返回：
        { "success": true, "task_id": "...", "graph_id": null|"..." }
    """
    from ..models.project import ProjectManager, ProjectStatus
    from ..services.graph_builder import GraphBuilderService
    from ..services.ontology_generator import OntologyGenerator
    from ..services.text_processor import TextProcessor

    data = request.get_json(silent=True) or {}
    force = bool(data.get('force', False))
    resume = bool(data.get('resume', False))
    skip_auto_refill = bool(data.get('skip_auto_refill', False))
    goal = str(data.get('goal') or '').strip()

    try:
        bible = WorldBibleService.get_bible(project_id)
    except Exception as e:
        return jsonify({"success": False, "error": f"读取设定库失败: {e}"}), 500

    if bible is None or (not bible.background_text.strip() and not bible.story_text.strip()):
        return jsonify({
            "success": False,
            "error": "尚未提交世界输入，请先在「世界设定」中保存背景/正文"
        }), 400

    project = ProjectManager.get_project(project_id)
    if project is None:
        project = ProjectManager.create_project(name="世界模拟")

    # 断点续构建：已有 graph_id 且（显式 resume 或 force 但存在 build-progress）时，
    # 不再强制新建图，而是复用同一 graph_id 继续未完成 chunk。
    from ..services.world_graph_refill import load_build_progress
    existing_progress = load_build_progress(project_id) if project and project.graph_id else None
    can_resume = bool(existing_progress and project and project.graph_id)
    if project.graph_id and not force and not resume and not can_resume:
        return jsonify({
            "success": False,
            "error": "世界图谱已存在，如需重建请加 force: true，或加 resume: true 断点续构建",
            "graph_id": project.graph_id,
        }), 400

    # 组装设定文本（背景+正文）
    parts = []
    if bible.background_text.strip():
        parts.append(f"【世界背景设定】\n{bible.background_text}")
    if bible.story_text.strip():
        parts.append(f"【小说正文】\n{bible.story_text}")
    text = "\n\n".join(parts)

    chunk_size = int(data.get('chunk_size', Config.DEFAULT_CHUNK_SIZE))
    overlap = int(data.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP))
    # 每批写入的块数：默认 4（OpenCode 网关下更稳），body 可覆盖 1-16（超出则夹取）
    raw_batch_size = data.get('batch_size', 4)
    try:
        batch_size = int(raw_batch_size)
    except (TypeError, ValueError):
        batch_size = 4
    batch_size = max(1, min(16, batch_size))
    # 批内并发处理数：默认 1（串行最稳），可覆盖 1-3（超出夹取）。
    # 注意：OpenCode/DeepSeek 兼容端点在并发请求下易空响应/断连，非必要勿 >1。
    raw_max_workers = data.get('max_workers', 1)
    try:
        max_workers = int(raw_max_workers)
    except (TypeError, ValueError):
        max_workers = 1
    max_workers = max(1, min(3, max_workers))

    # 同项目并发构建守卫：已有 processing/pending 的 world_graph_build 任务时，
    # 直接返回进行中的 task_id，避免重复线程写同一图谱（导致进度混乱/拖慢）。
    for _task in task_manager.list_tasks():
        try:
            _meta = _task.get("metadata") if isinstance(_task, dict) else {}
            _status = _task.get("status")
        except Exception:
            continue
        if (
            _meta.get("kind") == "world_graph_build"
            and _meta.get("project_id") == project_id
            and _status in ("pending", "processing")
        ):
            return jsonify({
                "success": True,
                "task_id": _task.get("task_id"),
                "graph_id": project.graph_id,
                "already_running": True,
                "message": "该项目的世界图谱构建任务已在进行中，复用现有任务",
            })

    # 后台任务：本体生成 → 建图 → 写回 project.graph_id
    task_id = task_manager.create_task(
        f"构建世界图谱: {project.name or project_id}",
        metadata={"kind": "world_graph_build", "project_id": project_id},
    )
    project.graph_build_task_id = task_id
    project.status = ProjectStatus.GRAPH_BUILDING
    ProjectManager.save_project(project)

    def _build_task():
        build_logger = logger
        try:
            task_manager.update_task(
                task_id, status=TaskStatus.PROCESSING,
                progress=3, message="准备世界设定文本..."
            )

            # 1. LLM 生成本体（面向小说世界的实体/关系类型）
            task_manager.update_task(
                task_id, progress=8, message="LLM 分析设定生成世界本体..."
            )
            generator = OntologyGenerator(llm_client=_build_llm_client_for_project(project_id))
            from ..services.ontology_generator import generate_ontology_with_cache
            ontology = generate_ontology_with_cache(
                generator=generator,
                document_texts=[text],
                simulation_requirement=goal or "构建小说世界的知识图谱",
                additional_context=(
                    "这是世界模拟的设定资料（背景设定与小说正文）。"
                    "请提取适合知识图谱的实体类型（人物/地点/组织/物品/概念等）与关系类型，"
                    "并全部使用与文本一致的中文命名。"
                ),
                cache_key_parts=(text, goal or "", generator.llm_client.model),
            )
            task_manager.update_task(
                task_id, progress=20,
                message=f"本体生成完成：{len(ontology.get('entity_types', []))} 个实体类型"
            )

            # 2. 创建/复用图谱并设置本体
            builder = GraphBuilderService()
            # 注意：此处必须重新取 project（闭包内对 project 的赋值会使其
            # 成为局部变量，直接引用外层 project 会触发 UnboundLocalError）
            proj = ProjectManager.get_project(project_id) or project
            from ..services.world_graph_refill import (
                load_build_progress, chunk_hash, mark_chunks_done,
                save_episodes_cache,
            )

            # 已有图谱 + 断点清单 → 复用同一 graph_id 续构建，避免从头开始
            if proj.graph_id and (resume or can_resume):
                graph_id = proj.graph_id
                task_manager.update_task(
                    task_id, progress=25,
                    message=f"断点续构建：复用已有图谱 {graph_id}",
                )
            else:
                graph_id = builder.create_graph(name=f"世界图谱-{proj.name or project_id}")
                proj.graph_id = graph_id
                ProjectManager.save_project(proj)
                task_manager.update_task(
                    task_id, progress=25, message=f"图谱已创建: {graph_id}"
                )
            builder.set_ontology(graph_id, ontology)

            # 3. 分块并添加 episode（跳过 build-progress 中已完成的 chunk）
            chunks = TextProcessor.split_text(text, chunk_size=chunk_size, overlap=overlap)
            total_chunks = len(chunks)
            # 缓存 episode 文本，供后续"补边"重放（低频；失败仅警告，不影响建图）
            try:
                save_episodes_cache(project_id, chunks)
            except Exception:
                logger.warning("缓存世界图谱 episodes 失败（忽略）")

            progress = load_build_progress(project_id) or {"chunks": []}
            done_by_index = {}
            for item in progress.get("chunks", []):
                if isinstance(item, dict) and item.get("status") == "done":
                    try:
                        done_by_index[int(item.get("index", -1))] = item
                    except (TypeError, ValueError):
                        continue
            remaining_indices = []
            remaining_chunks = []
            for idx, chunk in enumerate(chunks):
                item = done_by_index.get(idx)
                if item and item.get("hash") == chunk_hash(chunk):
                    continue
                remaining_indices.append(idx)
                remaining_chunks.append(chunk)

            task_manager.update_task(
                task_id, progress=30,
                message=f"设定文本已分割为 {total_chunks} 个块，待写入 {len(remaining_indices)} 个块",
            )

            if remaining_chunks:
                # 分批写入：每批发送→等待该批处理→立即 mark_chunks_done 落断点。
                # 相比"全部完成才存断点"，中断时仅丢当前在途批次，已完成的批可断点续建，
                # 不会几小时白跑。每批+批内逐条同步更新任务进度（30-85% 线性推进）。
                episode_uuids = []
                total_batches = (len(remaining_chunks) + batch_size - 1) // batch_size
                done_batches = 0

                for b in range(0, len(remaining_chunks), batch_size):
                    batch_chunks = remaining_chunks[b:b + batch_size]
                    batch_indices = remaining_indices[b:b + batch_size]
                    batch_num = b // batch_size + 1

                    # 该批 episode 数据（与 add_text_batches 内部一致）
                    episodes = [{"data": c, "type": "text"} for c in batch_chunks]
                    task_manager.update_task(
                        task_id, progress=30 + int((b / max(len(remaining_chunks), 1)) * 55),
                        message=f"发送第 {batch_num}/{total_batches} 批（{len(batch_chunks)} 块）...",
                    )

                    # 批内逐条进度：根据已写入的全局块数，在 [本批起点, 本批终点) 线性推进
                    batch_start_global = b
                    batch_len = len(batch_chunks)

                    def _per_episode(done, total, msg, _b=b, _bstart=batch_start_global,
                                     _blen=batch_len, _nrem=len(remaining_chunks)):
                        frac = (done / _blen) if _blen else 1.0
                        pct = 30 + int(((_bstart + _blen * frac) / max(_nrem, 1)) * 55)
                        task_manager.update_task(
                            task_id, progress=max(30, min(85, pct)),
                            message=f"第 {batch_num}/{total_batches} 批 · {msg or ''}",
                        )

                    try:
                        batch_uuids = builder.client.add_episode_batch(
                            graph_id=graph_id, episodes=episodes,
                            progress_callback=_per_episode, max_workers=max_workers,
                        )
                    except Exception as _be:
                        # 该批失败：不标记 done（断点保留前序批次），抛出让任务失败可续。
                        task_manager.update_task(
                            task_id,
                            message=f"批次 {batch_num} 发送失败，前序批次已存断点（可 resume）",
                        )
                        raise

                    # 等待本批处理完成（graphiti 后端为同步，立即返回）
                    builder._wait_for_episodes(batch_uuids)
                    # 立即把本批 chunk 写入 build-progress 断点
                    mark_chunks_done(
                        project_id, batch_chunks, batch_indices,
                        batch_uuids, graph_id=graph_id,
                    )
                    episode_uuids.extend(batch_uuids)
                    done_batches += 1
                    task_manager.update_task(
                        task_id,
                        progress=30 + int((len(episode_uuids) / max(len(remaining_chunks), 1)) * 55),
                        message=f"批次 {batch_num}/{total_batches} 完成（已达 {done_batches}/{total_batches} 批）",
                    )
            else:
                episode_uuids = []
                task_manager.update_task(
                    task_id, progress=85,
                    message="所有 chunk 已在断点中完成，跳过写入",
                )

            # 4. 统计并收尾
            graph_data = builder.get_graph_data(graph_id)
            node_count = graph_data.get("node_count", 0)
            edge_count = graph_data.get("edge_count", 0)
            proj = ProjectManager.get_project(project_id) or project
            proj.status = ProjectStatus.GRAPH_COMPLETED
            ProjectManager.save_project(proj)

            task_result = {
                "project_id": project_id,
                "graph_id": graph_id,
                "node_count": node_count,
                "edge_count": edge_count,
                "chunk_count": total_chunks,
                "resumed_chunk_count": total_chunks - len(remaining_chunks),
                "auto_refill_task": None,
            }

            # 建图完成后自动补边（可选）：默认开启；前端可传 skip_auto_refill 跳过，
            # 避免用户以为还在建图。仅当补边队列可用且 project 已有 graph_id 才启动。
            if Config.GRAPHITI_AUTO_REFILL and not skip_auto_refill:
                try:
                    from ..services.world_graph_refill import start_edge_refill
                    auto_refill_task = start_edge_refill(
                        project_id=project_id,
                        graph_id=graph_id,
                        task_manager=task_manager,
                    )
                    task_result["auto_refill_task"] = auto_refill_task
                    build_logger.info(
                        f"建图完成，已自动启动补边任务: {auto_refill_task}"
                    )
                except Exception as refill_err:
                    build_logger.warning(
                        f"自动补边启动失败（忽略，不影响建图）: {refill_err}"
                    )
                    task_result["auto_refill_task"] = None

            task_manager.update_task(
                task_id, status=TaskStatus.COMPLETED, progress=100,
                message=f"世界图谱构建完成（{node_count} 节点 / {edge_count} 边）",
                result=task_result,
            )
            build_logger.info(
                f"世界图谱构建完成: project={project_id}, graph={graph_id}, "
                f"nodes={node_count}, edges={edge_count}"
            )
        except Exception as e:
            import traceback
            from ..services.llm_error_normalizer import normalize_llm_error
            friendly = normalize_llm_error(e)
            error_msg = f"{friendly}\n\n详细堆栈:\n{traceback.format_exc()}"
            logger.error(f"世界图谱构建失败: {error_msg}")
            task_manager.fail_task(task_id, friendly)
            try:
                project = ProjectManager.get_project(project_id)
                if project:
                    project.status = ProjectStatus.FAILED
                    project.error = f"世界图谱构建失败: {friendly}"
                    ProjectManager.save_project(project)
            except Exception:
                pass

    thread = threading.Thread(target=_build_task, daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "task_id": task_id,
        "graph_id": project.graph_id,
        "message": "世界图谱构建已启动（本体生成 + Graphiti 建图）",
    })


@world_bp.route('/<project_id>/graph', methods=['GET'])
def get_world_graph(project_id: str):
    """读取世界知识图谱数据（节点/边/统计）"""
    try:
        from ..models.project import ProjectManager
        from ..services.graph_builder import GraphBuilderService

        project = ProjectManager.get_project(project_id)
        if project is None or not project.graph_id:
            return jsonify({"success": True, "graph": None, "graph_id": None})

        builder = GraphBuilderService()
        graph_data = builder.get_graph_data(project.graph_id)
        return jsonify({
            "success": True,
            "graph": graph_data,
            "graph_id": project.graph_id,
        })
    except Exception as e:
        logger.error(f"读取世界图谱失败: {e}")
        return jsonify({"success": False, "error": f"读取世界图谱失败: {e}"}), 500


@world_bp.route('/<project_id>/graph/refill_edges', methods=['POST'])
def refill_world_graph_edges(project_id: str):
    """
    补边：把建图时缓存的 episode 重新 add_episode，以提取此前被
    skip-first 跳过的边。临时用 GRAPHITI_EDGE_MODE=always + MAX_NODES=4，
    单条有界重试，失败跳过该条。后台异步任务，返回 task_id 供前端轮询。

    请求（JSON，可选）：
        { "force": false }   // 预留：未来可选强制清空重放

    返回：
        { "success": true, "task_id": "..." }
    """
    try:
        from ..models.project import ProjectManager
        from ..services.world_graph_refill import start_edge_refill

        project = ProjectManager.get_project(project_id)
        graph_id = project.graph_id if project else None
        task_id = start_edge_refill(
            project_id=project_id,
            graph_id=graph_id,
            task_manager=task_manager,
        )
        return jsonify({"success": True, "task_id": task_id,
                        "message": "补边任务已启动，请通过 /task/{task_id} 查询进度"})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"启动补边失败: {e}")
        return jsonify({"success": False, "error": f"启动补边失败: {e}"}), 500


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


@world_bp.route('/<project_id>/conflicts/<conflict_id>/history', methods=['GET'])
def get_conflict_history(project_id: str, conflict_id: str):
    """获取单条冲突的完整多轮辩解历史（含每轮 effect 与聚合后的 follow_up_effect）。

    返回结构：
    {
      success: true,
      conflict: {
        conflict_id, topic, status, effective, follow_up_effect,
        defense_rounds: [ { round_id, role, content, verdict, effect, created_at }, ... ]
      }
    }
    """
    conflict = load_conflict(project_id, conflict_id)
    if conflict is None:
        return jsonify({"success": False, "error": "冲突不存在"}), 404

    data = conflict.to_dict()
    if data.get("defense_rounds"):
        for r in data["defense_rounds"]:
            if isinstance(r, dict) and set(r) - {"round_id", "role", "content",
                                               "verdict", "effect", "created_at"}:
                data["defense_rounds"] = [
                    {k: r[k] for k in ("round_id", "role", "content",
                                       "verdict", "effect", "created_at") if k in r}
                    for r in data["defense_rounds"]
                ]
                break
    # 兜底：若尚未显式存储 follow_up_effect，按状态推导一份
    data["follow_up_effect"] = data.get("follow_up_effect") or conflict.derive_follow_up_effect()
    return jsonify({"success": True, "conflict": data})


# ---------------------------------------------------------------- 冲突改正文件

def _corrections_summary(result) -> dict:
    """由 CorrectionSet 计算前端反馈所需的计数/空因/注解摘要。"""
    annotations = [e.to_dict() for e in result.corrections if not e.patch]
    n = len(result.corrections)
    p = len(result.patches)
    empty_reason = None
    if n == 0:
        empty_reason = "empty_no_rulings"   # 无任何已生效裁定
    elif p == 0:
        empty_reason = "empty_annotations_only"  # 仅有注解，无文本补丁
    return {
        "correction_count": n,
        "patch_count": p,
        "patches": result.patches,
        "corrections": [e.to_dict() for e in result.corrections],
        "annotations": annotations,
        "empty_reason": empty_reason,
    }


@world_bp.route('/<project_id>/conflicts/<conflict_id>/corrections', methods=['POST'])
def generate_conflict_corrections(project_id: str, conflict_id: str):
    """确定性重算本项目全部生效冲突的外挂补丁（不复制全文、不依赖 LLM；幂等多轮）。

    - 以 conflict_id 校验项目有该冲突；改正集按项目整份生成。
    - 只落盘 corrected_patches.md + corrections.json（外挂小补丁，不复制语料全文）。
    - 无已生效裁定或仅注解时仍写 sidecar 并返回 empty_reason 供前端说明。
    """
    if load_conflict(project_id, conflict_id) is None:
        return jsonify({"success": False, "error": "冲突不存在"}), 404
    try:
        result = ConflictCorrectionService().generate(project_id)
        resp = {
            "success": True,
            "project_id": project_id,
            "conflict_id": conflict_id,
            "has_files": True,
            "files": result.file_snapshot()["files"],
            "generated_at": result.generated_at,
        }
        resp.update(_corrections_summary(result))
        return jsonify(resp)
    except Exception as e:
        logger.error(f"生成改正补丁失败: {e}")
        return jsonify({"success": False, "error": f"生成改正补丁失败: {e}"}), 500


@world_bp.route('/<project_id>/conflicts/<conflict_id>/corrections', methods=['GET'])
def get_conflict_corrections(project_id: str, conflict_id: str):
    """读取最近一次生成的改正文件（不重算）；未生成过则返回 has_files=false。"""
    if load_conflict(project_id, conflict_id) is None:
        return jsonify({"success": False, "error": "冲突不存在"}), 404
    try:
        result = load_corrections(project_id)
        if result is None:
            return jsonify({
                "success": True,
                "project_id": project_id,
                "conflict_id": conflict_id,
                "has_files": False,
                "correction_count": 0,
                "patch_count": 0,
                "patches": [],
                "corrections": [],
                "annotations": [],
                "empty_reason": "empty_no_rulings",
                "files": {},
            })
        resp = {
            "success": True,
            "project_id": project_id,
            "conflict_id": conflict_id,
            "has_files": True,
            "files": result.file_snapshot()["files"],
            "generated_at": result.generated_at,
        }
        resp.update(_corrections_summary(result))
        return jsonify(resp)
    except Exception as e:
        logger.error(f"读取改正补丁失败: {e}")
        return jsonify({"success": False, "error": f"读取改正补丁失败: {e}"}), 500


@world_bp.route('/<project_id>/conflicts/<conflict_id>/corrections/render', methods=['GET'])
def render_corrected_corpus(project_id: str, conflict_id: str):
    """对原始语料 + 外挂补丁做确定性叠加，按需渲染合并全文（不落盘）。

    参数：?source=settings|story
    返回 {"source","text","applied","skipped"}；可接 ?download=1 直接下载 md。"""
    if load_conflict(project_id, conflict_id) is None:
        return jsonify({"success": False, "error": "冲突不存在"}), 404
    source = (request.args.get('source') or 'story').strip().lower()
    if source not in ('settings', 'story'):
        return jsonify({"success": False, "error": "source 必须是 settings 或 story"}), 400
    try:
        merged = ConflictCorrectionService().render_merged(project_id, source)
        if request.args.get('download'):
            from flask import send_file, Response
            body = f"# 改正后的{'设定' if source=='settings' else '正文'}（动态渲染）\n\n"
            if merged.get('skipped'):
                body += "> 以下补丁未能应用（已旁路）：\n" + \
                        "\n".join(f"> - {s.get('reason')}" for s in merged['skipped']) + "\n\n"
            body += (merged.get('text') or '')
            filename = "corrected_settings.md" if source == "settings" else "corrected_story.md"
            return Response(body, mimetype='text/markdown',
                            headers={"Content-Disposition": f"attachment; filename={filename}"})
        return jsonify({"success": True, **merged})
    except Exception as e:
        logger.error(f"渲染合并全文失败: {e}")
        return jsonify({"success": False, "error": f"渲染合并全文失败: {e}"}), 500


@world_bp.route('/<project_id>/conflicts/<conflict_id>/corrections/<filename>/download', methods=['GET'])
def download_conflict_correction(project_id: str, conflict_id: str, filename: str):
    """下载外挂补丁文件（corrected_patches.md / corrections.json）。

    完整合并稿用 GET .../corrections/render?source=...&download=1 动态生成下载。
    """
    if load_conflict(project_id, conflict_id) is None:
        return jsonify({"success": False, "error": "冲突不存在"}), 404
    allowed = {"corrected_patches.md", "corrections.json"}
    if filename not in allowed:
        return jsonify({"success": False, "error": "未知文件名"}), 400
    from flask import send_file
    d = ConflictCorrectionService.corrections_dir(project_id)
    path = os.path.join(d, filename)
    if not os.path.exists(path):
        return jsonify({"success": False, "error": "改正补丁尚未生成"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


def _regenerate_corrections_if_settled(project_id: str, conflict) -> bool:
    """当冲突辩驳成功生效（非 open）后，自动重算改正文件。

    返回 True 表示已重算（包括无新生效裁定时的空集重写）；失败降级返回 False，
    不阻断辩驳主流程。
    """
    if not getattr(conflict, "effective", False):
        return False
    try:
        from ..services.conflict_correction import ConflictCorrectionService
        ConflictCorrectionService().generate(project_id)
        return True
    except Exception as e:
        logger.warning(f"辩驳成功后自动生成改正文件失败: {e}")
        return False


@world_bp.route('/<project_id>/conflicts/<conflict_id>', methods=['PATCH'])
def update_conflict_status(project_id: str, conflict_id: str):
    """更新冲突处理状态（open/accepted/dismissed/justified），可附自定义辩解说明。

    body: { status: str, note?: str }
    - status=justified 时 note 必填（用户自定义辩解/裁定）。
    - accepted/dismissed 也可附带 note 作为备注。
    """
    try:
        data = request.get_json(silent=True) or {}
        status = str(data.get('status', '')).strip()
        if status not in ('open', 'accepted', 'dismissed', 'justified'):
            return jsonify({"success": False, "error": "状态必须是 open/accepted/dismissed/justified"}), 400
        note = str(data.get('note') or data.get('resolution_note') or '').strip()
        if status == 'justified' and not note:
            return jsonify({"success": False, "error": "自定义辩解必须填写说明（note）"}), 400
        if len(note) > 2000:
            return jsonify({"success": False, "error": "辩解说明过长（≤2000 字）"}), 400

        report = load_conflict_report(project_id)
        if report is None:
            return jsonify({"success": False, "error": "没有可更新的冲突报告"}), 404

        updated = False
        from datetime import datetime as _dt
        now = _dt.now().isoformat(timespec="seconds")
        for c in report.conflicts:
            if c.conflict_id == conflict_id:
                if status == "justified":
                    # 多轮辩解：记录创作者论点，再交给 LLM 评估
                    user_round = DefenseRound(
                        round_id=f"{c.conflict_id}_u{len(c.defense_rounds) + 1}",
                        role="user",
                        content=note[:2000],
                        created_at=now,
                    )
                    c.defense_rounds.append(user_round)
                    if len(c.defense_rounds) > 12:
                        del c.defense_rounds[:-12]

                    assistant_round = None
                    try:
                        detector = ConflictDetector(
                            llm_client=_build_llm_client_for_project(project_id)
                        )
                        assistant_round = detector.evaluate_defense(c, note)
                        c.defense_rounds.append(assistant_round)
                    except Exception as e:
                        logger.warning(f"LLM 辩解评估失败，按人工辩解通过处理: {e}")

                    c.resolution_note = note
                    if assistant_round and assistant_round.verdict == "defense_rejected":
                        # 没解释通：保留 open，允许继续辩解
                        c.status = "open"
                        c.effective = False
                    else:
                        # 解释通（accepted/partial）或评估降级 → 标记 justified 并生效
                        c.status = "justified"
                        c.effective = True
                elif status in ("accepted", "dismissed"):
                    c.status = status
                    c.effective = True
                    c.resolution_note = note or c.resolution_note or ""
                    if note:
                        c.defense_rounds.append(DefenseRound(
                            round_id=f"{c.conflict_id}_m{len(c.defense_rounds) + 1}",
                            role="user",
                            content=note[:2000],
                            created_at=now,
                        ))
                else:  # open
                    c.status = "open"
                    c.effective = False
                    c.resolution_note = note or c.resolution_note or ""
                # 依据最近一轮裁定与状态，聚合/更新“后续影响”（供前端展示）
                c.follow_up_effect = c.derive_follow_up_effect() or c.follow_up_effect
                updated = True
                break
        if not updated:
            return jsonify({"success": False, "error": "冲突不存在"}), 404

        save_conflict_report(project_id, report)
        # 辩驳成功生效后自动重算改正文件（确定性、幂等；失败不阻断主流程）
        correction_settled = _regenerate_corrections_if_settled(project_id, c)
        resp = {"success": True, "conflict": c.to_dict()}
        if correction_settled is True:
            resp["corrections_regenerated"] = True
        return jsonify(resp)
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
            "time_step_minutes": 30,   // 可选，每步模拟分钟数（time_mode=minutes 时生效）
            "time_mode": "minutes",    // 可选：minutes | narrative
            "time_jumps": ["数日后", "三个月后", "一年后"],  // narrative 模式必填
            "include_timeline": true,  // 可选：把当前时间线作为推演上下文
            "from_event_id": "tl_evt_xxx",  // 可选：从某个时间线事件开始推演
            "goal": "任务目标（可选）"  // 推演目标，如"推演三年后谁将统一大陆"
        }
    """
    try:
        from ..services.world_simulation import WorldSimulationService

        data = request.get_json(silent=True) or {}
        total_steps = int(data.get('total_steps', 6))
        time_step_minutes = int(data.get('time_step_minutes', 30))
        goal = str(data.get('goal') or '').strip() or None
        time_mode = str(data.get('time_mode') or 'minutes').strip() or 'minutes'
        raw_jumps = data.get('time_jumps') or []
        if isinstance(raw_jumps, str):
            raw_jumps = [s.strip() for s in raw_jumps.replace('，', ',').split(',') if s.strip()]
        time_jumps = [str(x).strip() for x in raw_jumps if str(x).strip()]
        include_timeline = bool(data.get('include_timeline', False))
        from_event_id = str(data.get('from_event_id') or '').strip() or None
        story_summary_mode = str(data.get('story_summary_mode') or 'rule').strip() or 'rule'
        try:
            max_concurrency = int(data.get('max_concurrency') or 0) or None
        except (TypeError, ValueError):
            max_concurrency = None
        agent_model_id = str(data.get('agent_model_id') or '').strip() or None
        kwargs = dict(
            project_id=project_id,
            total_steps=total_steps,
            time_step_minutes=time_step_minutes,
            goal=goal,
            time_mode=time_mode,
            time_jumps=time_jumps,
            include_timeline=include_timeline,
            from_event_id=from_event_id,
            story_summary_mode=story_summary_mode,
            max_concurrency=max_concurrency,
        )
        if agent_model_id:
            kwargs["agent_model_id"] = agent_model_id

        state = WorldSimulationService.start_simulation(**kwargs)
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


@world_bp.route('/<project_id>/simulation/<simulation_id>', methods=['DELETE'])
@world_bp.route('/<project_id>/simulations/<simulation_id>', methods=['DELETE'])
def delete_world_simulation(project_id: str, simulation_id: str):
    """删除单条世界模拟（data/world-sim/<project>/<simulation_id>），仅删该条，不动项目。"""
    try:
        from ..services.world_simulation import WorldSimulationService
        ok = WorldSimulationService.delete_simulation(project_id, simulation_id)
        if not ok:
            return jsonify({
                "success": False,
                "error": f"世界模拟不存在: {simulation_id}"
            }), 404
        return jsonify({
            "success": True,
            "project_id": project_id,
            "simulation_id": simulation_id,
        })
    except Exception as e:
        logger.error(f"删除世界模拟失败: {e}")
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


# ---------------------------------------------------------------- 世界小说续写

@world_bp.route('/<project_id>/novel', methods=['POST'])
def generate_world_novel(project_id: str):
    """基于世界模拟的最终确定内容，生成“小说续写”而不是分析报告。

    请求（JSON）：
        { "simulation_id": "xxx" }

    返回：
        { "success": true, "novel": {"text": "...", "chapters": [...]} }
    """
    try:
        from ..services.world_novel import WorldNovelService

        data = request.get_json(silent=True) or {}
        simulation_id = str(data.get('simulation_id', '')).strip()
        if not simulation_id:
            return jsonify({"success": False, "error": "simulation_id 不能为空"}), 400

        novel = WorldNovelService.generate_novel(project_id, simulation_id)
        return jsonify({"success": True, "novel": novel})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error(f"生成世界小说续写失败: {e}")
        return jsonify({"success": False, "error": f"生成小说续写失败: {e}"}), 500


@world_bp.route('/<project_id>/novel/<simulation_id>', methods=['GET'])
def get_world_novel(project_id: str, simulation_id: str):
    """读取已生成的世界小说续写"""
    try:
        from ..services.world_novel import WorldNovelService

        novel = WorldNovelService.load_novel(project_id, simulation_id)
        if novel is None:
            return jsonify({"success": False, "error": "小说续写尚未生成"}), 404
        return jsonify({"success": True, "novel": novel})
    except Exception as e:
        logger.error(f"读取世界小说续写失败: {e}")
        return jsonify({"success": False, "error": f"读取小说续写失败: {e}"}), 500


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
