"""
最终时间线报告生成服务（Final Timeline Report）

把一条已完成的时间线整理成「最终报告」：

- synopsis  ：结构化梗概（按时间顺序，逐事件一行，含时间/地点/人物，确定性生成）
- novel     ：叙事向小说正文（确定性拼接：最佳流向引子 + 按时间序的事件叙述）
- best_flow ：引用该项目的「最佳流向」（is_best_flow）作为开篇引子

设计原则：确定性优先。报告完全由本地时间线/人物/结构数据拼接而成，
不依赖 LLM、不联网，任何人任何时候生成结果一致（便于测试与离线可用）。
可选传入 llm 参数留作未来"润色"，当前实现不调用。

存储：
- data/world-timeline/<project_id>/final-report.json（结构化）
- data/world-timeline/<project_id>/final-report.md  （下载用 Markdown）

数据来源：
- 时间线事件：timeline_service.load_timeline(project_id)
- 结构类型  ：timeline_service.load_structure(project_id)
- 人物档案  ：timeline_service.load_characters(project_id)
- 任务目标  ：WorldBibleService -> metadata['goal']
- 最佳流向  ：SimulationFavoriteService.find_best_flow(project_id)
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json, atomic_write_text

logger = get_logger('mirofish.timeline_report')

# 时间线根（与 timeline_service 共用 data 目录）
_APP_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data',
)
REPORT_ROOT = os.path.join(_APP_DATA, 'world-timeline')

# 引子 / 连接语（确定性模板）
_CONNECTORS = [
    "随后，", "与此同时，", "紧接着，", "在这之后，", "不久，",
]


def _report_path(project_id: str, ext: str) -> str:
    return os.path.join(REPORT_ROOT, project_id, f"final-report.{ext}")


def _report_json_path(project_id: str) -> str:
    return _report_path(project_id, "json")


def _report_md_path(project_id: str) -> str:
    return _report_path(project_id, "md")


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------

def _load_timeline_events(project_id: str) -> List[Dict[str, Any]]:
    try:
        from ..services.timeline_service import load_timeline
        events = load_timeline(project_id, None).get("events", [])
    except Exception as e:
        logger.warning(f"读取时间线失败（设为空）: {e}")
        events = []
    events = sorted(events, key=lambda e: (e.get("sort_lower") or 0))
    return events


def _load_structure(project_id: str) -> Optional[Dict[str, Any]]:
    try:
        from ..services.timeline_service import load_structure
        return load_structure(project_id)
    except Exception:
        return None


def _load_characters(project_id: str) -> List[Dict[str, Any]]:
    try:
        from ..services.timeline_service import load_characters
        return load_characters(project_id)
    except Exception:
        return []


def _load_goal(project_id: str) -> str:
    try:
        from ..services.world_bible import WorldBibleService
        bible = WorldBibleService.get_bible(project_id)
        if bible is not None:
            return str((bible.metadata or {}).get("goal") or "").strip()
    except Exception:
        pass
    return ""


def _load_best_flow(project_id: str) -> Optional[Dict[str, Any]]:
    try:
        from ..services.simulation_favorite import SimulationFavoriteService
        return SimulationFavoriteService().find_best_flow(project_id)
    except Exception as e:
        logger.warning(f"读取最佳流向失败（忽略）: {e}")
        return None


# ---------------------------------------------------------------------------
# 确定性文本拼装
# ---------------------------------------------------------------------------

def _event_label(e: Dict[str, Any]) -> str:
    """为一条事件生成「时间 · 地点」前置标签，用于梗概与正文。"""
    parts = []
    t = str(e.get("time_text") or "").strip()
    if t:
        parts.append(t)
    loc = str(e.get("location_name") or "").strip()
    if loc:
        parts.append(loc)
    return " · ".join(parts) if parts else ""


def _is_future(e: Dict[str, Any]) -> bool:
    return e.get("kind") in ("future", "branch") or e.get("source") in ("future", "branch")


def _render_synopsis(events: List[Dict[str, Any]], structure: Optional[Dict[str, Any]]) -> str:
    """确定性梗概：按时间顺序，逐事件一行；未来/分支事件归入展望段尾。"""
    if not events:
        return "（暂无已抽取的时间线事件，无法生成梗概）"

    past = [e for e in events if not _is_future(e)]
    future = [e for e in events if _is_future(e)]

    lines: List[str] = []
    lines.append("### 主线"
                 if structure and structure.get("type") == "single"
                 else "### 事件进展")
    for e in past:
        label = _event_label(e)
        summary = str(e.get("summary") or "").strip() or "（无摘要）"
        lines.append(f"- {('[' + label + '] ') if label else ''}{summary}")

    if future:
        lines.append("")
        lines.append("### 未来展望 / 推演分支")
        for e in future:
            label = _event_label(e)
            summary = str(e.get("summary") or "").strip() or "（无摘要）"
            lines.append(f"- {('[' + label + '] ') if label else ''}{summary}")

    return "\n".join(lines)


def _render_novel(project_id: str, events: List[Dict[str, Any]]) -> str:
    """确定性小说正文：最佳流向引子 + 按时间顺序的事件叙述。"""
    if not events:
        return "（暂无已抽取的时间线事件，无法生成小说正文）"

    paras: List[str] = []

    # 引子：最佳流向
    best = _load_best_flow(project_id)
    if best:
        remark = str(best.get("remark") or "").strip()
        lead = "这一条，是本次推演中被标记为「最佳流向」的路。" \
               f"（模拟 {best.get('simulation_id')}）"
        if remark:
            lead += f"备注意见：{remark}"
        paras.append(lead)
    else:
        paras.append("这是根据当前时间线整合而成的一则推演叙事。")

    # 未来/分支事件放最后，作为"推演展望"
    past = [e for e in events if not _is_future(e)]
    future = [e for e in events if _is_future(e)]

    for idx, e in enumerate(past):
        label = _event_label(e)
        summary = str(e.get("summary") or "").strip()
        if not summary:
            continue
        connector = _CONNECTORS[(idx - 1) % len(_CONNECTORS)] if idx > 0 else ""
        sentence = (f"[{label}] " if label else "") + summary
        paras.append(f"{connector}{sentence}")

    if future:
        paras.append("")
        paras.append("在推演的更远处，还有尚未落定的可能：")
        for e in future:
            label = _event_label(e)
            summary = str(e.get("summary") or "").strip()
            if not summary:
                continue
            paras.append(f"- {(f'[{label}] ' if label else '')}{summary}")

    return "\n\n".join(paras)


def _build_meta(events: List[Dict[str, Any]], characters: List[Dict[str, Any]]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    meta["events_count"] = len(events)
    meta["future_count"] = sum(1 for e in events if _is_future(e))
    meta["characters_count"] = len(characters)
    character_names = [c.get("canonical_name") or c.get("name") for c in characters]
    meta["characters"] = [n for n in character_names if n]
    return meta


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def generate_report(project_id: str, regenerate: bool = True) -> Dict[str, Any]:
    """生成（或重新生成）某项目的最终时间线报告。确定性、不联网。

    始终现场用时间线数据拼装，保证结果一致；返回结构化报告 dict。
    """
    events = _load_timeline_events(project_id)
    structure = _load_structure(project_id)
    characters = _load_characters(project_id)
    goal = _load_goal(project_id)
    best_flow = _load_best_flow(project_id)

    synopsis = _render_synopsis(events, structure)
    novel = _render_novel(project_id, events)

    report = {
        "project_id": project_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "format": "novel+synopsis",
        "deterministic": True,
        "goal": goal,
        "structure": structure,
        "best_flow": best_flow,
        "events_count": len(events),
        "meta": _build_meta(events, characters),
        "synopsis": synopsis,
        "novel": novel,
    }

    os.makedirs(os.path.dirname(_report_json_path(project_id)), exist_ok=True)
    atomic_write_json(_report_json_path(project_id), report)
    atomic_write_text(_report_md_path(project_id), render_markdown(report))
    return report


def load_report(project_id: str) -> Optional[Dict[str, Any]]:
    """读取已生成的最终报告；不存在返回 None。"""
    path = _report_json_path(project_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"读取最终报告失败: {path}, err={e}")
        return None


def render_markdown(report: Dict[str, Any]) -> str:
    """把报告渲染成 Markdown（下载用途）。"""
    pid = report.get("project_id", "")
    goal = str(report.get("goal") or "").strip()
    best = report.get("best_flow")
    lines = [
        f"# 最终时间线报告 · {pid}",
        "",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- 事件总数：{report.get('events_count', 0)}",
    ]
    if goal:
        lines.append(f"- 任务目标：{goal}")
    if best:
        lines.append(f"- 最佳流向：{best.get('simulation_id', '')}")
    if report.get("structure") and report["structure"].get("type"):
        lines.append(f"- 时间线结构：{report['structure']['type']}")
    lines += ["", "---", ""]
    lines.append(report.get("synopsis", ""))
    lines += ["", "---", "", "## 叙事正文", "", report.get("novel", "")]
    return "\n".join(lines) + "\n"
