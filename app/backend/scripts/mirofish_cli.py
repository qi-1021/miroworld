#!/usr/bin/env python3
"""MiroFish 命令行工具（面向 AI Agent / 自动化操作）。

所有子命令支持 --json 输出，便于脚本与 Agent 解析。

示例：
  python scripts/mirofish_cli.py project list --json
  python scripts/mirofish_cli.py world save --project-id proj_xxx --background "..." --story "..."
  python scripts/mirofish_cli.py timeline extract --project-id proj_xxx --source bg --wait
  python scripts/mirofish_cli.py timeline get --project-id proj_xxx --json
  python scripts/mirofish_cli.py conflict detect --project-id proj_xxx
  python scripts/mirofish_cli.py sim start --project-id proj_xxx --steps 6 --time-mode narrative --time-jumps "数日后,三个月后"
  python scripts/mirofish_cli.py assistant ask --project-id proj_xxx --question "..."
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Optional

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
    raise ValueError(f"未知 world 动作: {args.action}")


def cmd_timeline(args) -> dict:
    from app.services import timeline_service
    if args.action == "extract":
        task_id = timeline_service.start_extract(args.project_id, args.source)
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
    raise ValueError(f"未知 timeline 动作: {args.action}")


def cmd_conflict(args) -> dict:
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
        graph_name=args.graph_name or project.name or "MiroFish Graph",
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
    return {"simulation": state.to_dict()}


def cmd_assistant(args) -> dict:
    from app.api.assistant import _build_project_context, _execute_assistant_action
    context = _build_project_context(args.project_id)
    if context == "项目不存在。":
        raise ValueError("项目不存在")
    llm = _build_llm_client(args.project_id)
    from app.api.assistant import _SYSTEM_PROMPT
    answer = llm.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"项目上下文：\n{context}\n\n用户问题：{args.question}"},
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


def cmd_health(args) -> dict:
    checks = {}
    for name, port in (("frontend", 3000), ("backend", 5001), ("neo4j", 7687)):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                checks[name] = "ok"
        except Exception:
            checks[name] = "down"
    return {"checks": checks, "all_ok": all(v == "ok" for v in checks.values())}


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
    parser = argparse.ArgumentParser(prog="mirofish", description="MiroFish CLI")
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

    t = sub.add_parser("timeline")
    ta = t.add_subparsers(dest="action", required=True)
    te = _add_json(ta.add_parser("extract"))
    te.add_argument("--project-id", required=True)
    te.add_argument("--source", choices=["story", "bg"], default="story")
    te.add_argument("--wait", action="store_true")
    te.add_argument("--timeout", type=float, default=600.0)
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

    c = sub.add_parser("conflict")
    ca = c.add_subparsers(dest="action", required=True)
    _add_json(ca.add_parser("detect")).add_argument("--project-id", required=True)

    g = sub.add_parser("graph")
    ga = g.add_subparsers(dest="action", required=True)
    gb = _add_json(ga.add_parser("build"))
    gb.add_argument("--project-id", required=True)
    gb.add_argument("--graph-name")
    gb.add_argument("--chunk-size", type=int, default=1500)
    gb.add_argument("--chunk-overlap", type=int, default=150)
    gb.add_argument("--wait", action="store_true")
    gb.add_argument("--timeout", type=float, default=1800.0)

    s = sub.add_parser("sim")
    sa = s.add_subparsers(dest="action", required=True)
    ss = _add_json(sa.add_parser("start"))
    ss.add_argument("--project-id", required=True)
    ss.add_argument("--steps", type=int, default=6)
    ss.add_argument("--time-step-minutes", type=int, default=30)
    ss.add_argument("--time-mode", choices=["minutes", "narrative"], default="minutes")
    ss.add_argument("--time-jumps", default="")
    ss.add_argument("--goal", default="")
    ss.add_argument("--include-timeline", action="store_true")
    ss.add_argument("--from-event-id", default="")

    a = sub.add_parser("assistant")
    aa = a.add_subparsers(dest="action", required=True)
    ask = _add_json(aa.add_parser("ask"))
    ask.add_argument("--project-id", required=True)
    ask.add_argument("--question", required=True)

    _add_json(sub.add_parser("health"))
    return parser


def main(argv=None) -> int:
    # 让 --json 在"顶层"和"任意子命令后"都能用：
    # 在 argparse 之前把它从 argv 中剥离并记录，否则子命令后的 --json 会被
    # 判为 unrecognized arguments 而报错；同时也规避了顶层/子命令同名 dest
    # 默认值互相覆盖的问题。
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]

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
        elif args.command == "health":
            result = cmd_health(args)
        else:
            raise ValueError(f"未知命令: {args.command}")
        _out(result, as_json)
        return 0
    except Exception as e:
        _out({"success": False, "error": str(e)}, True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
