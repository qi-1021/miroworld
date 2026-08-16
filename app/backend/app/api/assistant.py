"""内置项目助手 API。

助手读取当前项目上下文（项目状态、设定库、时间线、人物、冲突、图谱），
用项目绑定的 LLM 回答“哪里不对劲、应该去哪个栏目改、下一步做什么”。

端点：
- POST /api/assistant/ask   body: { project_id, question }
"""

import json

from flask import jsonify, request

from . import assistant_bp
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger("mirofish.assistant")


def _build_llm_client_for_project(project_id: str) -> LLMClient:
    """优先项目绑定模型，其次注册表第一个已验证 chat，最后回退默认。"""
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
        logger.warning(f"项目绑定模型解析失败，尝试回退: {e}")

    try:
        from ..services.zep_graphiti_impl import GraphitiClient
        resolved = GraphitiClient._resolve_registry_chat_model()
        if resolved:
            api_key, base_url, model = resolved
            return LLMClient(api_key=api_key, base_url=base_url, model=model)
    except Exception as e:
        logger.warning(f"注册表模型回退失败: {e}")
    return LLMClient()


def _build_project_context(project_id: str) -> str:
    """汇总项目当前状态，供助手参考。"""
    from ..models.project import ProjectManager
    from ..services import timeline_service
    from ..services.world_bible import WorldBibleService
    from ..services.conflict_detector import load_conflict_report

    lines = []
    project = ProjectManager.get_project(project_id)
    if project is None:
        return "项目不存在。"

    lines.append(f"项目：{project.name}（{project.project_id}）")
    lines.append(f"状态：{project.status.value if hasattr(project.status, 'value') else project.status}")
    lines.append(f"本体实体类型：{len((project.ontology or {}).get('entity_types', []))}，关系类型：{len((project.ontology or {}).get('edge_types', []))}")
    lines.append(f"图谱 graph_id：{project.graph_id or '未构建'}")

    bible = WorldBibleService.get_bible(project_id)
    if bible is not None:
        lines.append(f"设定库：背景 {len(bible.background_text)} 字 / 正文 {len(bible.story_text)} 字，分块 {len(bible.chunks)}")
    else:
        lines.append("设定库：无")

    timeline = timeline_service.load_timeline(project_id, None)
    events = timeline.get("events", [])
    threads = sorted({e.get("thread_name") or e.get("thread_id") for e in events if e.get("thread_name") or e.get("thread_id")})
    dims = sorted({e.get("dimension") for e in events if e.get("dimension") and e.get("dimension") != "main"})
    lines.append(f"时间线事件：{len(events)}；线程：{threads or '无'}；非主线维度：{dims or '无'}")

    chars = timeline_service.load_characters(project_id)
    lines.append(f"人物档案：{len(chars)} 人" + (f"，含别名 {sum(len(c.get('aliases') or []) for c in chars)} 个" if chars else ""))

    report = load_conflict_report(project_id)
    if report is not None:
        statuses = {}
        for c in report.conflicts:
            statuses[c.status] = statuses.get(c.status, 0) + 1
        lines.append(f"冲突报告：{len(report.conflicts)} 条，状态 {statuses}")
    else:
        lines.append("冲突报告：无")

    return "\n".join(lines)


def _execute_assistant_action(project_id: str, action: str, params: dict):
    """执行助手请求的具体项目操作。返回结果 dict；未知操作抛 ValueError。"""
    from ..services import timeline_service
    from ..services.world_bible import WorldBibleService
    from ..services.project_snapshot import export_project_snapshot

    action = str(action or "").strip()
    params = params or {}

    if action == "update_timeline_event":
        event_id = str(params.get("event_id") or "").strip()
        patch = params.get("patch") or {}
        if not event_id or not isinstance(patch, dict):
            raise ValueError("update_timeline_event 需要 event_id 和 patch")
        updated = timeline_service.patch_event(project_id, event_id, patch)
        if updated is None:
            raise ValueError("事件不存在")
        return {"updated": updated}

    if action == "batch_delete_events":
        event_ids = params.get("event_ids") or []
        if not isinstance(event_ids, list) or not event_ids:
            raise ValueError("batch_delete_events 需要 event_ids 数组")
        return timeline_service.batch_events(project_id, "delete", event_ids)

    if action == "batch_update_events":
        event_ids = params.get("event_ids") or []
        patch = params.get("patch") or {}
        if not isinstance(event_ids, list) or not event_ids:
            raise ValueError("batch_update_events 需要 event_ids 数组")
        if not isinstance(patch, dict) or not patch:
            raise ValueError("batch_update_events 需要 patch 对象")
        return timeline_service.batch_events(project_id, "update", event_ids, patch)

    if action == "save_characters":
        characters = params.get("characters") or []
        if not isinstance(characters, list) or not characters:
            raise ValueError("save_characters 需要 characters 数组")
        ok = timeline_service.save_characters(project_id, characters)
        if not ok:
            raise ValueError("保存人物档案失败")
        return {"saved": len(timeline_service.load_characters(project_id))}

    if action == "save_world_input":
        background = str(params.get("background") or "")
        story = str(params.get("story") or "")
        if not background.strip() and not story.strip():
            raise ValueError("save_world_input 需要 background 或 story")
        bible = WorldBibleService.save_input(
            project_id=project_id,
            background=background,
            story=story,
            embed=False,
        )
        return {"chunks": len(bible.chunks)}

    if action == "save_threads":
        threads = params.get("threads") or []
        if not isinstance(threads, list):
            raise ValueError("save_threads 需要 threads 数组")
        ok = timeline_service.save_threads(project_id, threads)
        if not ok:
            raise ValueError("保存线索失败")
        return {"saved": len(timeline_service.load_threads(project_id))}

    if action == "export_snapshot":
        snapshot = export_project_snapshot(project_id)
        return {"snapshot": snapshot}

    if action == "update_conflict_status":
        conflict_id = str(params.get("conflict_id") or "").strip()
        status = str(params.get("status") or "").strip()
        note = str(params.get("note") or params.get("resolution_note") or "").strip()
        if not conflict_id or status not in ("open", "accepted", "dismissed", "justified"):
            raise ValueError("update_conflict_status 需要 conflict_id 和 status(open/accepted/dismissed/justified)")
        from ..services.conflict_detector import (
            ConflictDetector, DefenseRound, load_conflict_report, save_conflict_report,
        )
        from datetime import datetime as _dt
        report = load_conflict_report(project_id)
        if report is None:
            raise ValueError("没有可更新的冲突报告")
        now = _dt.now().isoformat(timespec="seconds")
        updated = None
        for c in report.conflicts:
            if c.conflict_id != conflict_id:
                continue
            updated = c
            if status == "justified":
                if not note:
                    raise ValueError("辩解必须填写 note")
                c.defense_rounds.append(DefenseRound(
                    round_id=f"{c.conflict_id}_u{len(c.defense_rounds) + 1}",
                    role="user", content=note[:2000], created_at=now,
                ))
                if len(c.defense_rounds) > 12:
                    del c.defense_rounds[:-12]
                assistant_round = None
                try:
                    assistant_round = ConflictDetector(
                        llm_client=_build_llm_client_for_project(project_id)
                    ).evaluate_defense(c, note)
                    c.defense_rounds.append(assistant_round)
                except Exception:
                    logger.warning("助手自动辩解评估失败，按人工辩解通过处理")
                c.resolution_note = note
                if assistant_round and assistant_round.verdict == "defense_rejected":
                    c.status = "open"
                    c.effective = False
                else:
                    c.status = "justified"
                    c.effective = True
            else:
                c.status = status
                c.effective = status in ("accepted", "dismissed")
                c.resolution_note = note or c.resolution_note or ""
                if note and status in ("accepted", "dismissed"):
                    c.defense_rounds.append(DefenseRound(
                        round_id=f"{c.conflict_id}_m{len(c.defense_rounds) + 1}",
                        role="user", content=note[:2000], created_at=now,
                    ))
            c.follow_up_effect = c.derive_follow_up_effect() or c.follow_up_effect
            break
        if updated is None:
            raise ValueError("冲突不存在")
        save_conflict_report(project_id, report)
        # 辩驳成功生效后自动重算改正文件（确定性、幂等；失败不阻断）
        if getattr(updated, "effective", False):
            try:
                from ..services.conflict_correction import ConflictCorrectionService
                ConflictCorrectionService().generate(project_id)
            except Exception as e:
                logger.warning(f"助手自动生成改正文件失败: {e}")
        return {"conflict_id": conflict_id, "status": updated.status,
                "effective": updated.effective, "last_verdict": updated.last_verdict}

    if action == "start_world_simulation":
        from ..services.world_simulation import WorldSimulationService
        raw_jumps = params.get("time_jumps") or []
        if isinstance(raw_jumps, str):
            raw_jumps = [s.strip() for s in raw_jumps.replace("，", ",").split(",") if s.strip()]
        try:
            total_steps = int(params.get("total_steps", 6))
        except (TypeError, ValueError):
            total_steps = 6
        state = WorldSimulationService.start_simulation(
            project_id=project_id,
            total_steps=total_steps,
            time_step_minutes=int(params.get("time_step_minutes", 30) or 30),
            goal=str(params.get("goal") or params.get("simulation_requirement") or "").strip() or None,
            time_mode=str(params.get("time_mode") or "minutes").strip(),
            time_jumps=[str(x).strip() for x in raw_jumps if str(x).strip()],
            include_timeline=bool(params.get("include_timeline", False)),
            from_event_id=str(params.get("from_event_id") or "").strip() or None,
        )
        return {"simulation_id": state.simulation_id, "status": state.status}

    if action == "generate_novel":
        sim_id = str(params.get("simulation_id") or "").strip()
        if not sim_id:
            raise ValueError("generate_novel 需要 simulation_id")
        from ..services.world_novel import WorldNovelService
        novel = WorldNovelService.generate_novel(project_id, sim_id)
        return {
            "simulation_id": sim_id,
            "chapters": len(novel.get("chapters") or []),
            "text_preview": str(novel.get("text") or "")[:200],
        }

    if action == "start_timeline_extraction":
        from ..services import timeline_service
        source = str(params.get("source") or "bg").strip()
        resume = params.get("resume")
        force = bool(params.get("force", False))
        task_id = timeline_service.start_extract(
            project_id,
            source=source,
            resume=resume,
            force=force,
        )
        return {"task_id": task_id, "source": source}

    if action == "generate_final_report":
        from ..services.timeline_report import generate_report
        report = generate_report(project_id, regenerate=bool(params.get("regenerate", True)))
        return {
            "project_id": project_id,
            "has_report": bool(report),
            "events_count": (report or {}).get("events_count"),
            "generated_at": (report or {}).get("generated_at"),
        }

    if action == "build_world_graph":
        from flask import current_app
        client = current_app.test_client()
        try:
            batch_size = int(params.get("batch_size", 4) or 4)
        except (TypeError, ValueError):
            batch_size = 4
        try:
            max_workers = int(params.get("max_workers", 1) or 1)
        except (TypeError, ValueError):
            max_workers = 1
        payload = {
            "goal": str(params.get("goal") or "").strip() or None,
            "force": bool(params.get("force", False)),
            "resume": bool(params.get("resume", True)),
            "batch_size": batch_size,
            "max_workers": max_workers,
        }
        resp = client.post(f"/api/world/{project_id}/graph/build", json=payload)
        data = resp.get_json() or {}
        if not data.get("success"):
            raise ValueError(data.get("error") or "建图失败")
        return data

    if action == "list_simulations":
        from ..services.world_simulation import WorldSimulationService
        sims = WorldSimulationService.list_simulations(project_id, limit=int(params.get("limit", 20) or 20))
        return {"simulations": sims}

    if action == "continue_world_simulation":
        from ..services.world_simulation import WorldSimulationService
        base_id = str(params.get("simulation_id") or params.get("base_simulation_id") or "").strip()
        if not base_id:
            raise ValueError("continue_world_simulation 需要 simulation_id")
        try:
            additional_steps = int(params.get("additional_steps", 3) or 3)
        except (TypeError, ValueError):
            additional_steps = 3
        state = WorldSimulationService.continue_simulation(
            base_id,
            additional_steps=additional_steps,
            goal=str(params.get("goal") or "").strip() or None,
        )
        return {
            "simulation_id": state.simulation_id,
            "status": state.status,
            "continue_base": base_id,
        }

    if action == "get_worldline_summary":
        from ..services.world_simulation import WorldSimulationService
        sim_id = str(params.get("simulation_id") or "").strip()
        if not sim_id:
            raise ValueError("get_worldline_summary 需要 simulation_id")
        state = WorldSimulationService.get_state(sim_id)
        if state is None:
            raise ValueError("模拟不存在")
        events = (state.result or {}).get("events") or []
        by_step = {}
        for e in events:
            by_step.setdefault(e.get("step"), []).append(e)
        steps = []
        for step in sorted(by_step):
            evs = by_step[step]
            steps.append({
                "step": step,
                "time": evs[0].get("time"),
                "summary": "；".join(
                    f"{e.get('character_name')}{e.get('action_desc', '')[:30]}" for e in evs[:6]
                )[:240],
                "event_count": len(evs),
            })
        return {
            "simulation_id": sim_id,
            "status": state.status,
            "event_count": len(events),
            "steps": steps,
            "meta": (state.result or {}).get("meta") or {},
        }

    if action == "list_world_tree":
        from ..services.world_simulation import WorldSimulationService
        sims = WorldSimulationService.list_simulations(project_id, limit=100)
        by_id = {s["simulation_id"]: {**s, "children": []} for s in sims}
        roots = []
        for sid, node in by_id.items():
            meta = (node.get("result") or {}).get("meta") or {}
            base = meta.get("whatif_base")
            if base and base in by_id:
                by_id[base]["children"].append(node)
            else:
                roots.append(node)
        return {"roots": roots}

    if action == "get_project_status":
        context = _build_project_context(project_id)
        return {"context": context}

    raise ValueError(f"未知操作: {action}")


_SYSTEM_PROMPT = (
    "你是 Miroworld 的内置项目助手。你非常了解这个工具的功能分区："
    "「世界设定库」负责输入背景/正文、冲突检测、图谱、时间线、模拟；"
    "「时间线」负责抽取/修正/分叉/批量编辑；「模型设置」负责模型接入与向量；"
    "「图谱」负责本体与 Graphiti/Neo4j 建图。"
    "用户会给你当前项目上下文和一个问题。请判断问题属于哪个栏目、应该修改哪个具体对象，"
    "并给出可操作步骤。若信息不足，明确说明还需要什么。"
    "如果你确定用户要求直接执行某个操作，且操作可通过以下动作完成，"
    "请只输出一个 JSON 对象（不要 Markdown）："
    '{"action": "<动作名>", "params": {...}}。'
    "可用动作："
    "update_timeline_event(event_id, patch)、"
    "batch_delete_events(event_ids)、"
    "batch_update_events(event_ids, patch)、"
    "save_characters(characters)、"
    "save_world_input(background, story)、"
    "save_threads(threads)、"
    "export_snapshot()、"
    "update_conflict_status(conflict_id, status, note)、"
    "start_world_simulation(goal, total_steps, time_mode, time_jumps, include_timeline, from_event_id)、"
    "generate_novel(simulation_id)、"
    "start_timeline_extraction(source, resume, force)、"
    "build_world_graph(goal, force, resume, batch_size, max_workers)、"
    "generate_final_report(regenerate)、"
    "list_simulations(limit)、"
    "list_world_tree()、"
    "continue_world_simulation(simulation_id, additional_steps, goal)、"
    "get_worldline_summary(simulation_id)、"
    "get_project_status()。"
    "否则输出普通中文回答，简洁、分点，不超过 400 字。"
)


@assistant_bp.route("/ask", methods=["POST"])
def ask():
    """根据项目上下文回答用户问题。"""
    try:
        data = request.get_json(silent=True) or {}
        project_id = str(data.get("project_id") or "").strip()
        question = str(data.get("question") or "").strip()
        direct_action = str(data.get("direct_action") or "").strip()
        direct_params = data.get("params") or {}
        if not project_id:
            return jsonify({"success": False, "error": "缺少 project_id"}), 400
        if not question and not direct_action:
            return jsonify({"success": False, "error": "缺少 question"}), 400

        context = _build_project_context(project_id)
        if context == "项目不存在。":
            return jsonify({"success": False, "error": "项目不存在"}), 404

        # 直接执行指定动作（前端快捷操作/Agent 工具调用，不经过 LLM 决策）
        if direct_action:
            action_result = _execute_assistant_action(project_id, direct_action, direct_params)
            return jsonify({
                "success": True,
                "data": {
                    "answer": f"已执行操作：{direct_action}",
                    "action": direct_action,
                    "action_result": action_result,
                    "context": context,
                },
            })

        llm = _build_llm_client_for_project(project_id)
        user = f"项目上下文：\n{context}\n\n用户问题：{question}"
        answer = llm.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        # 若 LLM 返回的是动作 JSON，则执行实际项目操作
        action_payload = None
        try:
            parsed = json.loads(answer)
            if isinstance(parsed, dict) and parsed.get("action"):
                action_payload = parsed
        except Exception:
            action_payload = None

        if action_payload is not None:
            action_result = _execute_assistant_action(
                project_id,
                str(action_payload.get("action") or ""),
                action_payload.get("params") or {},
            )
            return jsonify({
                "success": True,
                "data": {
                    "answer": f"已执行操作：{action_payload.get('action')}",
                    "action": str(action_payload.get("action") or ""),
                    "action_result": action_result,
                    "context": context,
                },
            })

        return jsonify({"success": True, "data": {"answer": answer, "context": context}})
    except ValueError as e:
        return jsonify({"success": False, "error": f"助手操作失败: {e}"}), 400
    except Exception as e:
        logger.error(f"项目助手调用失败: {e}")
        return jsonify({"success": False, "error": f"助手调用失败: {e}"}), 500
