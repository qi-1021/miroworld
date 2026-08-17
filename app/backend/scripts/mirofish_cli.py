#!/usr/bin/env python3
"""Miroworld 命令行工具（面向 AI Agent / 自动化操作）。

所有子命令支持 --json 输出，便于脚本与 Agent 解析；成功输出 {"success":true,"data":...}，
失败输出 {"success":false,"error":...}；退出码 0=成功、非 0=失败。

命令：project / models / health / world / timeline / conflict / graph / sim / assistant。
完整用法与 AI 全流程见 docs/CLI.md。

示例：
  python scripts/mirofish_cli.py models registry --json
  python scripts/mirofish_cli.py health --detailed --json
  python scripts/mirofish_cli.py project list --json
  python scripts/mirofish_cli.py world save --project-id proj_xxx --background "..." --story "..."
  python scripts/mirofish_cli.py timeline extract --project-id proj_xxx --source bg --wait
  python scripts/mirofish_cli.py timeline final-report --project-id proj_xxx --action generate --json
  python scripts/mirofish_cli.py conflict corrections --project-id proj_xxx --regenerate --json
  python scripts/mirofish_cli.py graph build-world --project-id proj_xxx --wait --json
  python scripts/mirofish_cli.py sim favorite --simulation-id sim_xxx --value 1 --json
  python scripts/mirofish_cli.py assistant ask --project-id proj_xxx --question "..."
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 解决 Windows 控制台中文输出/输入编码问题：在所有子命令执行前重配 UTF-8
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _out(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if isinstance(data, dict):
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(data)


def _build_llm_client(project_id: str):
    from app.api.assistant import _build_llm_client_for_project
    return _build_llm_client_for_project(project_id)


def _wait_task(task_id: str, timeout: float = 600.0) -> dict:
    from app.services import timeline_service
    start = time.time()
    while time.time() - start < timeout:
        st = timeline_service.get_status(task_id)
        if st and st.get("status") in ("completed", "partial_failed", "failed", "interrupted"):
            return st
        time.sleep(0.5)
    return {"status": "timeout", "task_id": task_id}


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_project(args) -> dict:
    from app.models.project import ProjectManager
    if args.action == "list":
        return {"projects": [p.to_dict() for p in ProjectManager.list_projects(limit=args.limit)]}
    if args.action == "create":
        p = ProjectManager.create_project(name=args.name or "CLI 项目")
        return {"project": p.to_dict()}
    if args.action == "delete":
        ok = ProjectManager.delete_project(args.project_id)
        if not ok:
            raise ValueError(f"项目不存在或没有可删除数据: {args.project_id}")
        return {"deleted": True, "project_id": args.project_id}
    if args.action == "export":
        from app.services.project_snapshot import export_project_snapshot
        snap = export_project_snapshot(args.project_id)
        if args.output:
            Path(args.output).write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"exported": True, "path": args.output}
        return {"snapshot": snap}
    if args.action == "import":
        from app.services.project_snapshot import import_project_snapshot
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        project = import_project_snapshot(data)
        return {"project": project}
    raise ValueError(f"未知 project 动作: {args.action}")


def cmd_world(args) -> dict:
    from app.services.world_bible import WorldBibleService
    if args.action == "save":
        background = args.background or ""
        story = args.story or ""
        if args.background_file:
            background = Path(args.background_file).read_text(encoding="utf-8")
        if args.story_file:
            story = Path(args.story_file).read_text(encoding="utf-8")
        if not background.strip() and not story.strip():
            raise ValueError("background/story 至少一个非空")
        bible = WorldBibleService.save_input(
            project_id=args.project_id,
            background=background,
            story=story,
            chunk_size=args.chunk_size,
            overlap=args.chunk_overlap,
            embed=False,
        )
        return {"stats": bible.stats()}
    if args.action == "get":
        bible = WorldBibleService.get_bible(args.project_id)
        if bible is None:
            return {"bible": None}
        return {"bible": bible.to_dict()}
    if args.action == "settings":
        return _cmd_world_settings(args.project_id)
    raise ValueError(f"未知 world 动作: {args.action}")


def cmd_timeline(args) -> dict:
    from app.services import timeline_service
    if args.action == "extract":
        task_id = timeline_service.start_extract(
            args.project_id, args.source,
            resume=getattr(args, "resume", False),
            force=getattr(args, "force", False),
        )
        if args.wait:
            st = _wait_task(task_id, timeout=args.timeout)
            st["task_id"] = task_id
            return st
        return {"task_id": task_id}
    if args.action == "get":
        data = timeline_service.load_timeline(args.project_id, None)
        return {"events": data.get("events", [])}
    if args.action == "threads":
        return {"threads": timeline_service.load_threads(args.project_id)}
    if args.action == "characters":
        return {"characters": timeline_service.load_characters(args.project_id)}
    if args.action == "structure":
        # 读取项目已保存的结构类型（若有），否则现场用 LLM 判断
        saved = timeline_service.load_structure(args.project_id)
        if saved and not args.force:
            return {"structure": saved}
        from app.services import timeline_service as ts
        from app.utils.llm_client import LLMClient
        llm = _build_llm_client(args.project_id)
        text = ts._source_text(args.project_id, story=(args.source == "story"))
        structure = ts.detect_structure_type(llm, text)
        if structure:
            ts.save_structure(args.project_id, structure)
        return {"structure": structure}
    if args.action == "structure-text":
        # 对输入的一段文本（不落项目）做结构判断，供复杂/多时间线快速验证
        from app.utils.llm_client import LLMClient
        if not (args.text or "").strip():
            raise ValueError("structure-text 需要 --text 参数提供文本内容")
        llm = _build_llm_client(args.project_id)
        structure = timeline_service.detect_structure_type(llm, args.text)
        return {"structure": structure}
    if args.action == "extract-text":
        # 对输入的一段文本做整块 LLM 抽取（含结构+线程提示），不写入项目，便于抽查
        from app.utils.llm_client import LLMClient
        if not (args.text or "").strip():
            raise ValueError("extract-text 需要 --text 参数提供文本内容")
        llm = _build_llm_client(args.project_id)
        structure = timeline_service.detect_structure_type(llm, args.text)
        struct_hint = timeline_service.structure_hint_block(structure)
        thread_hint = ""
        if args.source == "bg":
            threads = timeline_service._dedupe_threads(
                timeline_service._identify_threads(llm, args.text)
            )
            thread_hint = timeline_service._thread_hint_block(threads)
        events = timeline_service._llm_extract_chunk(
            llm, args.text, thread_hint, struct_hint
        )
        return {"structure": structure, "threads_hint": thread_hint != "",
                "event_count": len(events), "events": events}
    if args.action == "final-report":
        return _cmd_timeline_final_report(args.project_id, args.final_report_action)
    if args.action == "export":
        keys = []
        if getattr(args, "thread_keys", ""):
            keys = [s for s in args.thread_keys.replace("，", ",").split(",") if s.strip()]
        result = timeline_service.export_timeline(
            args.project_id,
            source=getattr(args, "source", None) or None,
            thread_keys=keys or None,
            include_all_threads=not bool(keys),
            format=getattr(args, "format", "md") or "md",
            include_meta=True,
        )
        output = getattr(args, "output", "") or ""
        if output:
            Path(output).write_text(result["content"], encoding="utf-8")
        return {
            "filename": result["filename"],
            "format": result["format"],
            "total_events": result["total_events"],
            "selected_threads": result["selected_threads"],
            "written_to": output or None,
        }
    raise ValueError(f"未知 timeline 动作: {args.action}")


def cmd_conflict(args) -> dict:
    if args.action == "list":
        return _cmd_conflict_list(args.project_id)
    if args.action == "history":
        return _cmd_conflict_history(args.project_id)
    if args.action == "corrections":
        return _cmd_conflict_corrections(
            args.project_id, getattr(args, "conflict_id", None),
            force=getattr(args, "force", False),
            regenerate=not getattr(args, "read", False),
        )
    from app.services.conflict_detector import ConflictDetector, save_conflict_report
    from app.services.world_bible import WorldBibleService
    bible = WorldBibleService.get_bible(args.project_id)
    if bible is None or not bible.background_text.strip() or not bible.story_text.strip():
        raise ValueError("冲突检测需要同时有背景和正文")
    detector = ConflictDetector(llm_client=_build_llm_client(args.project_id))
    report = detector.detect_with_progress(
        args.project_id,
        bible.background_text,
        bible.story_text,
    )
    if report.status == "failed":
        raise ValueError(report.error or "冲突检测失败")
    save_conflict_report(args.project_id, report)
    return {"conflict_count": len(report.conflicts), "report": report.to_dict()}


def cmd_graph(args) -> dict:
    if args.action == "status":
        return _cmd_graph_status(args.project_id)
    if args.action == "get":
        return _cmd_graph_get(args.project_id)
    if args.action == "build-world":
        return _cmd_graph_build_world(
            args.project_id,
            resume=getattr(args, "resume", True),
            skip_auto_refill=getattr(args, "skip_auto_refill", True),
            wait=getattr(args, "wait", False),
            timeout=getattr(args, "timeout", 1800.0),
        )
    from app.services.graph_builder import GraphBuilderService
    from app.services.text_processor import TextProcessor
    from app.models.project import ProjectManager
    project = ProjectManager.get_project(args.project_id)
    if project is None:
        raise ValueError(f"项目不存在: {args.project_id}")
    text = ProjectManager.get_extracted_text(args.project_id)
    if not text:
        raise ValueError("项目没有提取文本")
    if not project.ontology:
        raise ValueError("项目没有本体，请先生成本体")
    builder = GraphBuilderService()
    task_id = builder.build_graph_async(
        text=text,
        ontology=project.ontology,
        graph_name=args.graph_name or project.name or "Miroworld Graph",
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    if args.wait:
        from app.models.task import TaskManager
        start = time.time()
        while time.time() - start < args.timeout:
            task = TaskManager().get_task(task_id)
            if task and task.status.value in ("completed", "failed"):
                return {"task_id": task_id, "status": task.status.value, "result": task.result, "error": task.error}
            time.sleep(1)
        return {"task_id": task_id, "status": "timeout"}
    return {"task_id": task_id}


def cmd_sim(args) -> dict:
    if args.action == "list":
        return _cmd_sim_list(args.project_id)
    if args.action == "history":
        return _cmd_sim_history(args.project_id, favorited_only=getattr(args, "favorited_only", False))
    if args.action == "favorite":
        return _cmd_sim_favorite(args.simulation_id, bool(args.value))
    if args.action == "create":
        return _cmd_sim_create(args.project_id, getattr(args, "graph_id", None))
    if args.action == "prepare":
        return _cmd_sim_prepare(args.simulation_id, wait=getattr(args, "wait", False),
                                timeout=getattr(args, "timeout", 1800.0))
    from app.services.world_simulation import WorldSimulationService
    jumps = []
    if args.time_jumps:
        jumps = [s.strip() for s in args.time_jumps.replace("，", ",").split(",") if s.strip()]
    state = WorldSimulationService.start_simulation(
        project_id=args.project_id,
        total_steps=args.steps,
        time_step_minutes=args.time_step_minutes,
        goal=args.goal,
        time_mode=args.time_mode,
        time_jumps=jumps,
        include_timeline=args.include_timeline,
        from_event_id=args.from_event_id,
    )
    sim_id = state.simulation_id
    if getattr(args, "wait", False):
        start_t = time.time()
        timeout = getattr(args, "timeout", 1800.0)
        last_event_count = 0
        while time.time() - start_t < timeout:
            sim = WorldSimulationService.get_state(sim_id)
            if not sim:
                time.sleep(1)
                continue
            # 流式输出新事件
            events = (sim.result or {}).get("events", [])
            if len(events) > last_event_count:
                for ev in events[last_event_count:]:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [第{ev.get('round')}轮] 【{ev.get('character')}】: {ev.get('action')}", file=sys.stderr)
                last_event_count = len(events)
            if sim.status in ("completed", "failed", "stopped"):
                return {"simulation": sim.to_dict()}
            time.sleep(1)
        return {"simulation": (WorldSimulationService.get_state(sim_id) or state).to_dict(), "timeout": True}
    return {"simulation": state.to_dict()}


def cmd_assistant(args) -> dict:
    from app.api.assistant import _build_project_context, _execute_assistant_action
    context = _build_project_context(args.project_id)
    if context == "项目不存在。":
        raise ValueError("项目不存在")

    direct_action = getattr(args, "direct_action", "") or ""
    if direct_action:
        params = {}
        for kv in getattr(args, "param", []) or []:
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.strip()] = v.strip()
        result = _execute_assistant_action(args.project_id, direct_action, params)
        return {
            "answer": f"已执行操作：{direct_action}",
            "action": direct_action,
            "action_result": result,
        }

    question = getattr(args, "question", "") or ""
    if not question.strip():
        raise ValueError("缺少 --question 或 --direct-action")

    llm = _build_llm_client(args.project_id)
    from app.api.assistant import _SYSTEM_PROMPT
    answer = llm.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"项目上下文：\n{context}\n\n用户问题：{question}"},
        ],
        temperature=0.3,
        max_tokens=1000,
    )
    try:
        parsed = json.loads(answer)
        if isinstance(parsed, dict) and parsed.get("action"):
            result = _execute_assistant_action(args.project_id, parsed["action"], parsed.get("params") or {})
            return {"answer": f"已执行操作：{parsed['action']}", "action": parsed["action"], "action_result": result}
    except Exception:
        pass
    return {"answer": answer, "context": context}


def cmd_worldline(args) -> dict:
    from app.api.assistant import _execute_assistant_action
    action_map = {
        "tree": "list_world_tree",
        "continue": "continue_world_simulation",
        "summary": "get_worldline_summary",
        "export": "export_worldline",
    }
    action = action_map.get(args.action)
    if not action:
        raise ValueError(f"未知 worldline 操作: {args.action}")
    params = {}
    if args.action == "continue":
        params = {"simulation_id": args.simulation_id, "additional_steps": args.steps}
    elif args.action in ("summary", "export"):
        params = {"simulation_id": args.simulation_id}
    result = _execute_assistant_action(args.project_id, action, params)
    if args.action == "export" and getattr(args, "out", ""):
        import json as _json
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)
        return {"saved_to": args.out, "simulation_id": result.get("simulation_id")}
    return result


def cmd_backup(args) -> dict:
    """自动备份核心数据：world-sim / world / timeline / 模型注册表等。"""
    root = BACKEND_DIR.parent  # app/
    data_dirs = [
        root / "backend" / "data",
        root / "data",
    ]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(getattr(args, "output", "") or root.parent / "backups" / f"miroworld-backup-{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for d in data_dirs:
        if d.exists():
            target = out_dir / d.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(d, target)
            copied.append(str(target))
    # 配置与日志
    for f in [root / ".env.example", BACKEND_DIR / "logs"]:
        if f.exists():
            target = out_dir / f.name
            if f.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(f, target)
            else:
                shutil.copy2(f, target)
            copied.append(str(target))
    return {"backup_dir": str(out_dir), "copied": copied}


def cmd_health(args) -> dict:
    checks = {}
    for name, port in (("frontend", 3000), ("backend", 5001), ("neo4j", 7687)):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                checks[name] = "ok"
        except Exception:
            checks[name] = "down"
    result = {"checks": checks, "all_ok": all(v == "ok" for v in checks.values())}
    if getattr(args, "detailed", False):
        # 详细健康检查：Neo4j + 模型注册表 verified 数
        from app.services.model_registry import ModelRegistryService
        try:
            reg = ModelRegistryService().get_redacted_registry()
            result["models"] = {
                "verified": sum(1 for m in reg.get("models", []) if m.get("verified")),
                "connections": len(reg.get("connections", [])),
            }
            result["all_ok"] = result["all_ok"] and result["models"]["verified"] >= 1
        except Exception as e:
            result["models"] = {"error": str(e)}
            result["all_ok"] = False
    return result


# ---------------------------------------------------------------------------
# models：模型注册表（只读，供 AI/Agent 查看已验证模型与连接数）
# ---------------------------------------------------------------------------
def cmd_models(args) -> dict:
    from app.services.model_registry import ModelRegistryService
    registry = ModelRegistryService().get_redacted_registry()
    if args.action == "registry":
        return {
            "verified_count": sum(1 for m in registry.get("models", []) if m.get("verified")),
            "verified_models": [
                {"name": m.get("name") or m.get("model"), "verified": m.get("verified")}
                for m in registry.get("models", []) if m.get("verified")
            ],
            "connections": len(registry.get("connections", [])),
        }
    if args.action == "list":
        return {"models": registry.get("models", []), "connections": registry.get("connections", [])}
    raise ValueError(f"未知 models 动作: {args.action}")


# ---------------------------------------------------------------------------
# world 补充：settings（设定库统计 + 图谱状态）
# ---------------------------------------------------------------------------
def _cmd_world_settings(project_id: str) -> dict:
    from app.services.world_bible import WorldBibleService
    from app.models.project import ProjectManager
    stats = WorldBibleService.get_stats(project_id)
    project = ProjectManager.get_project(project_id)
    return {
        "stats": stats,
        "graph_id": project.graph_id if project else None,
        "graph_status": (project.status.value if project and project.status else None),
        "graph_build_task_id": project.graph_build_task_id if project else None,
    }


# ---------------------------------------------------------------------------
# conflict 补充：list / history / corrections（生成+读取）
# ---------------------------------------------------------------------------
def _load_conflict_report(project_id: str):
    from app.services.conflict_detector import load_conflict_report
    return load_conflict_report(project_id)


def _cmd_conflict_list(project_id: str) -> dict:
    report = _load_conflict_report(project_id)
    if report is None:
        return {"conflicts": [], "report": None}
    return {"conflict_count": len(report.conflicts), "report": report.to_dict()}


def _cmd_conflict_history(project_id: str) -> dict:
    from app.services.conflict_detector import load_conflict
    report = _load_conflict_report(project_id)
    if report is None or not report.conflicts:
        return {"conflicts": []}
    items = []
    for c in report.conflicts:
        history = [
            {"round": r.round, "role": r.role, "content": r.content,
             "verdict": r.verdict, "effect": r.effect,
             "created_at": r.created_at}
            for r in (c.defense_rounds or [])
        ]
        items.append({
            "conflict_id": c.conflict_id,
            "topic": c.topic,
            "status": c.status,
            "effective": c.effective,
            "follow_up_effect": c.follow_up_effect,
            "defense_rounds": history,
        })
    return {"conflicts": items}


def _cmd_conflict_corrections(project_id: str, conflict_id: Optional[str],
                              force: bool = False, regenerate: bool = True) -> dict:
    from app.services.conflict_correction import ConflictCorrectionService
    if conflict_id:
        from app.services.conflict_detector import load_conflict
        if load_conflict(project_id, conflict_id) is None:
            raise ValueError(f"冲突不存在: {conflict_id}")
    svc = ConflictCorrectionService()
    result = svc.generate(project_id) if regenerate else svc.load(project_id)
    if result is None:
        return {"has_files": False, "corrections": [], "patches": [], "files": {}}
    return {
        "has_files": True,
        "correction_count": len(result.corrections),
        "patch_count": len(result.patches),
        "corrections": [e.to_dict() for e in result.corrections],
        "patches": result.patches,
        "files": result.file_snapshot()["files"],
        "generated_at": getattr(result, "generated_at", ""),
    }


# ---------------------------------------------------------------------------
# timeline 补充：final-report（生成/读取/下载 md）
# ---------------------------------------------------------------------------
def _cmd_timeline_final_report(project_id: str, action: str) -> dict:
    from app.services import timeline_report
    if action in ("generate", "regenerate"):
        report = timeline_report.generate_report(project_id, regenerate=True)
        return {"has_report": True, "report": report}
    if action in ("get", "read"):
        report = timeline_report.load_report(project_id)
        if report is None:
            return {"has_report": False, "report": None}
        return {"has_report": True, "report": report}
    if action == "download":
        import os
        report = timeline_report.load_report(project_id)
        if report is None:
            raise ValueError("报告尚未生成，请先 generate")
        md = timeline_report.render_markdown(report)
        return {"has_report": True, "markdown": md,
                "length": len(md), "project_id": project_id}
    raise ValueError(f"未知 final-report 动作: {action}")


# ---------------------------------------------------------------------------
# graph 补充：status / get（世界图谱状态与数据）+ build-world（世界图谱构建）
# ---------------------------------------------------------------------------
def _cmd_graph_status(project_id: str) -> dict:
    from app.models.project import ProjectManager
    from app.services.graph_builder import GraphBuilderService
    project = ProjectManager.get_project(project_id)
    if project is None:
        return {"project_id": project_id, "graph_id": None, "graph_status": None}
    out = {
        "project_id": project_id,
        "graph_id": project.graph_id,
        "graph_status": project.status.value if project.status else None,
        "graph_build_task_id": project.graph_build_task_id,
    }
    if project.graph_id:
        try:
            gd = GraphBuilderService().get_graph_data(project.graph_id)
            out["node_count"] = gd.get("node_count", 0)
            out["edge_count"] = gd.get("edge_count", 0)
        except Exception as e:
            out["graph_read_error"] = str(e)
    return out


def _cmd_graph_get(project_id: str) -> dict:
    from app.models.project import ProjectManager
    from app.services.graph_builder import GraphBuilderService
    project = ProjectManager.get_project(project_id)
    if project is None or not project.graph_id:
        return {"project_id": project_id, "graph": None, "graph_id": None}
    graph = GraphBuilderService().get_graph_data(project.graph_id)
    return {"project_id": project_id, "graph_id": project.graph_id, "graph": graph}


def _cmd_graph_build_world(project_id: str, resume: bool = True,
                           skip_auto_refill: bool = True, wait: bool = False,
                           timeout: float = 1800.0) -> dict:
    """世界图谱构建（背景+正文，经本体生成 + Graphiti 建图）。

    复用后端真实管线（含同项目并发守卫与断点续构建），通过 Flask test client
    调用 POST /api/world/<pid>/graph/build，保证与网页端完全一致。
    """
    from app import create_app
    from app.models.task import TaskManager
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    TaskManager.PERSIST_DIR = os.path.join(data_dir, "task-manager")
    
    app = create_app()
    app.config["TESTING"] = True
    task_id: Optional[str] = None
    with app.test_client() as c:
        resp = c.post(
            f"/api/world/{project_id}/graph/build",
            json={"resume": resume, "skip_auto_refill": skip_auto_refill},
        )
        data = resp.get_json() or {}
        if resp.status_code == 400 and data.get("graph_id"):
            # 图谱已存在且未 request 重建：返回现有状态
            return {"status": "exists", "graph_id": data.get("graph_id"),
                    "message": data.get("error", "已构建"), "already_running": False}
        if not data.get("success"):
            raise ValueError(f"图谱构建失败: {data.get('error', resp.status_code)}")
        task_id = data.get("task_id")
        graph_id = data.get("graph_id")
        already = bool(data.get("already_running"))
    if wait and task_id:
        st = _wait_task_by_tm(task_id, timeout)
        return {"task_id": task_id, "graph_id": graph_id,
                "already_running": already, "status": st}
    return {"task_id": task_id, "graph_id": graph_id, "already_running": already}


def _wait_task_by_tm(task_id: str, timeout: float) -> dict:
    from app.models.task import TaskManager, Task
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    TaskManager.PERSIST_DIR = os.path.join(data_dir, "task-manager")
    tm = TaskManager()
    start = time.time()
    last_log_count = 0
    while time.time() - start < timeout:
        task = tm.get_task(task_id)
        if not task and TaskManager.PERSIST_DIR:
            task_file = os.path.join(TaskManager.PERSIST_DIR, f"{task_id}.json")
            if os.path.isfile(task_file):
                try:
                    with open(task_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        task = Task.from_dict(data)
                except Exception:
                    pass
        if task:
            # 实时流式输出新增日志
            logs = task.logs or []
            if len(logs) > last_log_count:
                for l in logs[last_log_count:]:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {l}", file=sys.stderr)
                last_log_count = len(logs)
            if task.status.value in ("completed", "failed"):
                return {"status": task.status.value, "progress": task.progress, "result": task.result, "error": task.error}
        time.sleep(1)
    return {"status": "timeout", "task_id": task_id}


# ---------------------------------------------------------------------------
# sim 补充：list / history / favorite
# ---------------------------------------------------------------------------
def _cmd_sim_list(project_id: Optional[str]) -> dict:
    from app.services.world_simulation import WorldSimulationService
    sims = WorldSimulationService.list_simulations(project_id, limit=100)
    return {"simulations": sims}


def _cmd_sim_history(project_id: Optional[str] = None, favorited_only: bool = False) -> dict:
    from app.services.world_simulation import WorldSimulationService
    sims = WorldSimulationService.list_simulations(project_id, limit=100)
    items = [s for s in sims]
    if favorited_only:
        from app.services.simulation_favorite import SimulationFavoriteService
        fav = SimulationFavoriteService()
        fav_ids = set(fav.list_favorited())
        items = [s for s in items if s.get("simulation_id") in fav_ids]
    return {"simulations": items}


def _cmd_sim_favorite(simulation_id: str, value: bool) -> dict:
    from app.services.simulation_favorite import SimulationFavoriteService
    fav = SimulationFavoriteService()
    entry = fav.set_favorite(simulation_id, value)
    return {"simulation_id": simulation_id, "favorite": value, "entry": entry}


def _cmd_sim_create(project_id: str, graph_id: Optional[str]) -> dict:
    from app.services.simulation_manager import SimulationManager
    from app.models.project import ProjectManager
    gid = graph_id or (ProjectManager.get_project(project_id).graph_id
                       if ProjectManager.get_project(project_id) else None)
    if not gid:
        raise ValueError("项目尚未构建图谱，请先 graph build-world")
    state = SimulationManager().create_simulation(project_id=project_id, graph_id=gid)
    return {"simulation_id": state.simulation_id, "project_id": project_id,
            "graph_id": gid, "status": state.status.value}


def _cmd_sim_prepare(simulation_id: str, wait: bool = False, timeout: float = 1800.0) -> dict:
    """提交世界模拟准备（生成智能体人设 + 配置），复用后端真实管线。"""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    task_id: Optional[str] = None
    status: str = ""
    with app.test_client() as c:
        resp = c.post("/api/simulation/prepare", json={"simulation_id": simulation_id})
        data = resp.get_json() or {}
        d = data.get("data") or {}
        status = d.get("status", "")
        task_id = d.get("task_id")
        if not data.get("success"):
            return {"simulation_id": simulation_id, "success": False,
                    "error": d.get("message") or data.get("error") or "准备接口失败"}
    if status in ("ready", "completed"):
        return {"simulation_id": simulation_id, "status": "ready"}
    if wait and task_id:
        st = _wait_task_by_tm(task_id, timeout)
        return {"simulation_id": simulation_id, "task_id": task_id, **st}
    return {"simulation_id": simulation_id, "status": status, "task_id": task_id}


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def _add_json(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """给 parser 加上 --json 选项。

    主要供各子命令的 --help 展示使用；实际生效逻辑见 main() 里的 argv 预处理，
    它保证 --json 在顶层或任意子命令后都能用。
    """
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="以 JSON 输出")
    return parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mirofish", description="Miroworld CLI")
    _add_json(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("project")
    pa = p.add_subparsers(dest="action", required=True)
    _add_json(pa.add_parser("list")).add_argument("--limit", type=int, default=50)
    _add_json(pa.add_parser("create")).add_argument("--name", default="CLI 项目")
    _add_json(pa.add_parser("delete")).add_argument("--project-id", required=True)
    pe = _add_json(pa.add_parser("export"))
    pe.add_argument("--project-id", required=True)
    pe.add_argument("--output")
    pi = _add_json(pa.add_parser("import"))
    pi.add_argument("--file", required=True)

    w = sub.add_parser("world")
    wa = w.add_subparsers(dest="action", required=True)
    ws = _add_json(wa.add_parser("save"))
    ws.add_argument("--project-id", required=True)
    ws.add_argument("--background", default="")
    ws.add_argument("--story", default="")
    ws.add_argument("--background-file")
    ws.add_argument("--story-file")
    ws.add_argument("--chunk-size", type=int, default=1500)
    ws.add_argument("--chunk-overlap", type=int, default=150)
    _add_json(wa.add_parser("get")).add_argument("--project-id", required=True)
    _add_json(wa.add_parser("settings")).add_argument("--project-id", required=True)

    t = sub.add_parser("timeline")
    ta = t.add_subparsers(dest="action", required=True)
    te = _add_json(ta.add_parser("extract"))
    te.add_argument("--project-id", required=True)
    te.add_argument("--source", choices=["story", "bg"], default="story")
    te.add_argument("--wait", action="store_true")
    te.add_argument("--timeout", type=float, default=600.0)
    te.add_argument("--resume", action="store_true", help="强制从已有断点续传")
    te.add_argument("--force", action="store_true", help="忽略已有断点强制全新抽取")
    _add_json(ta.add_parser("get")).add_argument("--project-id", required=True)
    _add_json(ta.add_parser("threads")).add_argument("--project-id", required=True)
    _add_json(ta.add_parser("characters")).add_argument("--project-id", required=True)
    tstruct = _add_json(ta.add_parser("structure"))
    tstruct.add_argument("--project-id", required=True)
    tstruct.add_argument("--source", choices=["story", "bg"], default="story")
    tstruct.add_argument("--force", action="store_true",
                         help="忽略已保存结果，强制用 LLM 重新判断")
    tstruct_text = _add_json(ta.add_parser("structure-text"))
    tstruct_text.add_argument("--text", required=True,
                              help="要判断结构的文本片段（可剪贴部分正文）")
    tstruct_text.add_argument("--project-id", default=None,
                              help="可选：用指定项目的模型凭据")
    textract = _add_json(ta.add_parser("extract-text"))
    textract.add_argument("--text", required=True,
                          help="要抽取的一段文本（可部分正文），模拟整流程抽查")
    textract.add_argument("--source", choices=["story", "bg"], default="story")
    textract.add_argument("--project-id", default=None,
                          help="可选：用指定项目的模型凭据")
    tfr = _add_json(ta.add_parser("final-report"))
    tfr.add_argument("--project-id", required=True)
    tfr.add_argument("--action", dest="final_report_action",
                     choices=["generate", "get", "download"], default="get",
                     help="generate=重新生成并读取；get=读取已生成；download=返回 Markdown")
    texp = _add_json(ta.add_parser("export"))
    texp.add_argument("--project-id", required=True)
    texp.add_argument("--source", choices=["story", "bg"], default=None)
    texp.add_argument("--format", choices=["md", "json", "csv"], default="md")
    texp.add_argument("--output", default="", help="写出文件路径（默认仅打印 summary）")
    texp.add_argument("--thread-keys", default="", help="逗号分隔线程 key；空=全部线程")

    c = sub.add_parser("conflict")
    ca = c.add_subparsers(dest="action", required=True)
    _add_json(ca.add_parser("detect")).add_argument("--project-id", required=True)
    _add_json(ca.add_parser("list")).add_argument("--project-id", required=True)
    _add_json(ca.add_parser("history")).add_argument("--project-id", required=True)
    ccorr = _add_json(ca.add_parser("corrections"))
    ccorr.add_argument("--project-id", required=True)
    ccorr.add_argument("--conflict-id", default=None, help="可选：指定冲突 id（无冲突列表为空）")
    ccorr.add_argument("--regenerate", action="store_true", help="强制重新生成改正补丁")
    ccorr.add_argument("--read", action="store_true", help="只读取已生成的改正（不重新生成）")

    g = sub.add_parser("graph")
    ga = g.add_subparsers(dest="action", required=True)
    gb = _add_json(ga.add_parser("build"))
    gb.add_argument("--project-id", required=True)
    gb.add_argument("--graph-name")
    gb.add_argument("--chunk-size", type=int, default=1500)
    gb.add_argument("--chunk-overlap", type=int, default=150)
    gb.add_argument("--wait", action="store_true")
    gb.add_argument("--timeout", type=float, default=1800.0)
    gstatus = _add_json(ga.add_parser("status"))
    gstatus.add_argument("--project-id", required=True)
    gget = _add_json(ga.add_parser("get"))
    gget.add_argument("--project-id", required=True)
    gbw = _add_json(ga.add_parser("build-world"))
    gbw.add_argument("--project-id", required=True)
    gbw.add_argument("--no-resume", dest="resume", action="store_false", default=True)
    gbw.add_argument("--no-skip-refill", dest="skip_auto_refill", action="store_false", default=True)
    gbw.add_argument("--wait", action="store_true")
    gbw.add_argument("--timeout", type=float, default=1800.0)

    s = sub.add_parser("sim")
    sa = s.add_subparsers(dest="action", required=True)
    _add_json(sa.add_parser("list")).add_argument("--project-id", required=True)
    sh = _add_json(sa.add_parser("history"))
    sh.add_argument("--project-id", required=True)
    sh.add_argument("--favorited-only", action="store_true")
    sfav = _add_json(sa.add_parser("favorite"))
    sfav.add_argument("--simulation-id", required=True)
    sfav.add_argument("--value", type=int, choices=[0, 1], default=1,
                      help="1=标记收藏，0=取消收藏")
    screate = _add_json(sa.add_parser("create"))
    screate.add_argument("--project-id", required=True)
    screate.add_argument("--graph-id", default=None)
    spre = _add_json(sa.add_parser("prepare"))
    spre.add_argument("--simulation-id", required=True)
    spre.add_argument("--wait", action="store_true")
    spre.add_argument("--timeout", type=float, default=1800.0)
    ss = _add_json(sa.add_parser("start"))
    ss.add_argument("--project-id", required=True)
    ss.add_argument("--steps", type=int, default=6)
    ss.add_argument("--time-step-minutes", type=int, default=30)
    ss.add_argument("--time-mode", choices=["minutes", "narrative"], default="minutes")
    ss.add_argument("--time-jumps", default="")
    ss.add_argument("--goal", default="")
    ss.add_argument("--include-timeline", action="store_true")
    ss.add_argument("--from-event-id", default="")
    ss.add_argument("--wait", action="store_true")
    ss.add_argument("--timeout", type=float, default=1800.0)

    a = sub.add_parser("assistant")
    aa = a.add_subparsers(dest="action", required=True)
    ask = _add_json(aa.add_parser("ask"))
    ask.add_argument("--project-id", required=True)
    ask.add_argument("--question", default="", help="自然语言问题")
    ask.add_argument("--direct-action", default="", help="直接执行动作名，跳过 LLM 决策")
    ask.add_argument("--param", action="append", default=[], help="动作参数 key=value，可多次")

    wl = sub.add_parser("worldline")
    wla = wl.add_subparsers(dest="action", required=True)
    wl_tree = _add_json(wla.add_parser("tree"))
    wl_tree.add_argument("--project-id", required=True)
    wl_cont = _add_json(wla.add_parser("continue"))
    wl_cont.add_argument("--project-id", required=True)
    wl_cont.add_argument("--simulation-id", required=True)
    wl_cont.add_argument("--steps", type=int, default=3)
    wl_sum = _add_json(wla.add_parser("summary"))
    wl_sum.add_argument("--project-id", required=True)
    wl_sum.add_argument("--simulation-id", required=True)
    wl_exp = _add_json(wla.add_parser("export"))
    wl_exp.add_argument("--project-id", required=True)
    wl_exp.add_argument("--simulation-id", required=True)
    wl_exp.add_argument("--out", default="", help="导出 JSON 文件路径")

    m = sub.add_parser("models")
    ma = m.add_subparsers(dest="action", required=True)
    _add_json(ma.add_parser("registry"))
    _add_json(ma.add_parser("list"))

    h = _add_json(sub.add_parser("health"))
    h.add_argument("--detailed", action="store_true", help="附加模型注册表 verified 检查")

    bk = _add_json(sub.add_parser("backup"))
    bk.add_argument("--output", default="", help="备份输出目录（默认 backups/ 下自动命名）")
    return parser


def main(argv=None) -> int:
    # 让 --json 在"顶层"和"任意子命令后"都能用：
    # 在 argparse 之前把它从 argv 中剥离并记录，否则子命令后的 --json 会被
    # 判为 unrecognized arguments 而报错；同时也规避了顶层/子命令同名 dest
    # 默认值互相覆盖的问题。
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]

    # 把所有日志压到 WARNING 级并重定向到 stderr，保证 stdout 只输出结果 JSON
    # （Graphiti 等库会打印大量 INFO 到 stdout，会污染 --json 输出）。
    import logging
    logging.disable(logging.WARNING)  # 全局禁用 <WARNING 的日志（含后续懒创建 logger）
    for _name in list(logging.root.manager.loggerDict):
        _lg = logging.getLogger(_name)
        if not hasattr(_lg, "handlers"):
            continue
        _lg.setLevel(logging.WARNING)
        for _h in list(getattr(_lg, "handlers", [])):
            if isinstance(_h, logging.StreamHandler) and getattr(_h, "stream", None) is sys.stdout:
                try:
                    _h.stream = sys.stderr
                except Exception:
                    pass

    args = _parser().parse_args(argv)
    try:
        if args.command == "project":
            result = cmd_project(args)
        elif args.command == "world":
            result = cmd_world(args)
        elif args.command == "timeline":
            result = cmd_timeline(args)
        elif args.command == "conflict":
            result = cmd_conflict(args)
        elif args.command == "graph":
            result = cmd_graph(args)
        elif args.command == "sim":
            result = cmd_sim(args)
        elif args.command == "assistant":
            result = cmd_assistant(args)
        elif args.command == "worldline":
            result = cmd_worldline(args)
        elif args.command == "models":
            result = cmd_models(args)
        elif args.command == "health":
            result = cmd_health(args)
        elif args.command == "backup":
            result = cmd_backup(args)
        else:
            raise ValueError(f"未知命令: {args.command}")
        _out({"success": True, "data": result}, as_json)
        return 0
    except Exception as e:
        _out({"success": False, "error": str(e)}, True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
