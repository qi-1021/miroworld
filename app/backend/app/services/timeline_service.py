"""
时间线抽取服务（timeline service）

- 分块（<=2000 字符）逐块 LLM 抽取（每次至多 1 次重试），失败降级到启发式抽取器。
- 归一化（地点词典 / 时间锚 / ev_type / sort 键），写入 data/world-timeline/<pid>/timeline.json。
- 提供任务状态轮询（running/completed/partial_failed/failed）。

存储目录：
- data/world-timeline/<project_id>/timeline.json（data/ 已 gitignore）
  timeline.json = { "project_id", "source", "events": [ <TimelineEvent>... ] }
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from . import timeline_normalizer as norm

logger = get_logger('mirofish.timeline')

# 数据根目录（app/backend/data，已 gitignore）
_APP_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data',
)
TIMELINE_ROOT = os.path.join(_APP_DATA, 'world-timeline')

# 单块文本上限
MAX_CHUNK_CHARS = 2000
# 单块最大 LLM 调用次数（1 原始 + 1 重试）
MAX_LLM_ATTEMPTS = 2

# project_id 白名单（与 ProjectManager.create_project 的 proj_+12hex 一致）
_PROJECT_ID_RE = re.compile(r'^proj_[0-9a-f]{12}$')


def validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(f"非法 project_id: {project_id!r}")
    return project_id


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def _timeline_path(project_id: str) -> str:
    return os.path.join(TIMELINE_ROOT, validate_project_id(project_id), 'timeline.json')


def load_timeline(project_id: str, source: Optional[str] = None) -> Dict[str, Any]:
    """读取某项目的时间线文件；不存在返回 {project_id, events:[]}。"""
    try:
        path = _timeline_path(project_id)
        if not os.path.exists(path):
            return {"project_id": project_id, "source": source, "events": []}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"project_id": project_id, "events": []}
        if source:
            events = [e for e in data.get("events", []) if e.get("source") == source]
        else:
            events = data.get("events", [])
        # 兼容旧数据：source=='future' 回填 kind；未来事件强制排在"现在"之后
        if events:
            past_max = max(
                (e.get('sort_lower') or 0.0)
                for e in events if e.get('source') != 'future' and e.get('kind') != 'future'
            )
            fut = [e for e in events
                   if e.get('source') == 'future' or e.get('kind') == 'future']
            for i, e in enumerate(fut):
                if e.get('source') == 'future' and not e.get('kind'):
                    e['kind'] = 'future'
                if (e.get('sort_lower') or 0.0) <= past_max:
                    e['sort_lower'] = past_max + 1.0 + i
                    e['sort_upper'] = e['sort_lower']
        return {"project_id": project_id, "source": source, "events": events}
    except Exception as e:
        logger.warning(f"读取时间线失败: {e}")
        return {"project_id": project_id, "source": source, "events": []}


def _save_timeline(project_id: str, events: List[Dict[str, Any]]) -> bool:
    try:
        path = _timeline_path(project_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({"project_id": project_id, "events": events}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning(f"写入时间线失败: {e}")
        return False


# ---------------------------------------------------------------------------
# LLM 客户端构造（复用现有模型凭据 + iter 候选回退，不改 graphiti_patch）
# ---------------------------------------------------------------------------
def _build_llm_client():
    """构造 OpenAI-compatible LLM 客户端，返回 LLMClient。

    优先从模型注册表解析候选（iter_chat_model_candidates）；
    无候选则回退到默认配置 LLMClient()。仅供测试 mock。
    """
    from ..utils.llm_client import LLMClient
    try:
        from .graphiti_patch import iter_chat_model_candidates
        cands = iter_chat_model_candidates()
        if cands:
            api_key, base_url, model = cands[0]
            if api_key and base_url and model:
                return LLMClient(api_key=api_key, base_url=base_url, model=model)
    except Exception as e:
        logger.warning(f"从注册表解析 LLM 凭据失败，回退默认: {e}")
    return LLMClient()


# ---------------------------------------------------------------------------
# JSON 数组解析（兼容 Markdown 围栏 / 前后说明文本）
# ---------------------------------------------------------------------------
def _extract_json_array(text: str):
    """从 LLM 响应中解析 JSON 数组；失败返回 None。"""
    if not text or not text.strip():
        return None
    raw = text.strip()
    candidates = [raw]
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("[") or part.startswith("{"):
                candidates.append(part)
    # 取第一个平衡 [ ... ] 块
    start = raw.find("[")
    if start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "[":
                depth += 1
            elif raw[i] == "]":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start:i + 1])
                    break
    for cand in candidates:
        try:
            val = json.loads(cand)
            return val if isinstance(val, list) else None
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 启发式降级抽取器
# ---------------------------------------------------------------------------
# 有强时间词的行视为候选事件
_TIME_TRIGGER = re.compile(r'[岁年|小时候|少年|青年|成年|中年|老年|次日|次年|后来|之后|从此|那些晚上|一天晚上|深夜|清晨|随后的|过程中|期间]')
# 句子切割：按 。！？； 以及换行分句
_SENT_SPLIT = re.compile('[。！？；\n]+')


def _heuristic_extract_chunk(chunk: str, chunk_index: int, source: str) -> List[Dict[str, Any]]:
    """启发式抽取：按时间/地点触发词切事件，标注低置信度。"""
    raw_events: List[Dict[str, Any]] = []
    sentences = [s.strip() for s in _SENT_SPLIT.split(chunk) if s and s.strip()]
    seq = 0
    for sent in sentences:
        if not _TIME_TRIGGER.search(sent):
            continue
        if len(sent) > 40:
            sent = sent[:40]
        seq += 1
        loc_name, loc_kind, _ = norm.normalize_location(sent)
        raw_events.append({
            "summary": sent,
            "time_text": "",
            "location_text": loc_name or "",
            "location_name": loc_name,
            "confidence": 0.3,
            "ev_type": "other",
            "time_kind": "unspecified",
            "_heuristic_seq": seq,
        })
    return raw_events


# ---------------------------------------------------------------------------
# LLM 抽取 prompt
# ---------------------------------------------------------------------------
_LLM_SYSTEM = (
    "你是一个文本时间线抽取引擎。从给定文本段中，抽取所有有明确时空或叙事推进的事件。"
    "仅输出一个 JSON 数组，不要任何多余文字或 Markdown。每事件含字段："
    "summary(一句话中文摘要)、time_text(原文中的时间表达,没有则空串)、"
    "time_kind(枚举:year/age/phase/period/season/literal/unspecified)、"
    "year(泰拉纪年整数,推测不出填null)、age(人物年龄整数,推测不出填null)、"
    "location_text(原文地点表达)、location_name(归一后地点名,没有则保留原文)、"
    "ev_type(枚举:birth/life/education/duty/task/conflict/disaster/culture/milestone/farewell/other)、"
    "confidence(0到1)、characters(人物名数组)。规则：只抽推动情节或事件性的内容；"
    "过长叙述拆成多个事件；保持原文简洁转述；无把握的时间锚填unspecified,year/age填null。"
)


def _llm_extract_chunk(llm, chunk: str) -> List[Dict[str, Any]]:
    """调用一次 LLM 抽取该块，返回原始事件列表；失败抛异常。"""
    user_msg = f"请抽取下面文本段的时间线事件，输出 JSON 数组：\n<文本段>\n{chunk}\n"
    resp = llm.chat(
        messages=[
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    arr = _extract_json_array(resp)
    if arr is None:
        raise ValueError("LLM 响应不是 JSON 数组")
    return [e for e in arr if isinstance(e, dict)]


# ---------------------------------------------------------------------------
# 事件归一化
# ---------------------------------------------------------------------------
def _normalize_event(raw: Dict[str, Any], project_id: str, source: str,
                     chunk_index: int, extract_method: str, seq: int) -> Dict[str, Any]:
    ev = {
        "id": f"tl_evt_{uuid.uuid4().hex[:12]}",
        "project_id": project_id,
        "source": source,
        "kind": "future" if source == "future" else "past",
        "chunk_index": int(chunk_index),
        "extract_method": extract_method,
        "ev_type": norm.normalize_ev_type(raw.get("ev_type")),
        "summary": str(raw.get("summary") or "").strip()[:120],
        "time_text": str(raw.get("time_text") or "").strip(),
        "time_kind": norm.normalize_time_kind(raw.get("time_kind")),
        "year": _int_or_none(raw.get("year")),
        "year_lower": _int_or_none(raw.get("year_lower")),
        "year_upper": _int_or_none(raw.get("year_upper")),
        "age": _int_or_none(raw.get("age")),
        "age_lower": _int_or_none(raw.get("age_lower")),
        "age_upper": _int_or_none(raw.get("age_upper")),
        "location_text": str(raw.get("location_text") or "").strip(),
        "location_name": str(raw.get("location_name") or "").strip(),
        "location_kind": str(raw.get("location_kind") or "unspecified"),
        "characters": _str_list(raw.get("characters")),
        "entities": _str_list(raw.get("entities")),
        "confidence": _float_or(raw.get("confidence"), 0.5),
        "raw_source": str(raw.get("raw_source") or "").strip(),
        "extract_seq": seq,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # 归一化地点
    if not ev["location_name"] and ev["location_text"]:
        name, kind, _ = norm.normalize_location(ev["location_text"])
        ev["location_name"] = name
        ev["location_kind"] = kind if kind != "unspecified" else ev["location_kind"]
    elif not ev["location_name"]:
        ev["location_name"] = ""
    # 归一化时间 → 计算 sort 键
    anchor = norm.parse_time_anchor(ev["time_text"])
    if anchor:
        for k in ("year", "year_lower", "year_upper", "age", "age_lower", "age_upper", "time_kind"):
            if anchor.get(k) is not None:
                ev[k] = anchor[k]
        sl = anchor.get("sort_lower")
        su = anchor.get("sort_upper")
        if sl is not None:
            ev["sort_lower"] = float(sl)
            ev["sort_upper"] = float(su if su is not None else sl)
        else:
            ev["sort_lower"] = float(seq)
            ev["sort_upper"] = float(seq)
    else:
        # 无时间表达：用年龄（若 LLM 给了）或叙述序 seq
        if ev["age"] is not None:
            ev["sort_lower"] = float(ev["age"]); ev["sort_upper"] = float(ev["age"])
        elif ev["year"] is not None:
            ev["sort_lower"] = float(ev["year"]) * 10.0
            ev["sort_upper"] = float(ev["year"]) * 10.0
        else:
            ev["sort_lower"] = float(seq); ev["sort_upper"] = float(seq)
    return ev


def _int_or_none(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or(v, default):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _str_list(v):
    if not v:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        return [v] if v.strip() else []
    return []


# ---------------------------------------------------------------------------
# 分块
# ---------------------------------------------------------------------------
def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """把文本切成 <=max_chars 的块，尽量在句号/换行/句号边界断句。"""
    if not text:
        return []
    chunks: List[str] = []
    cur = ""
    for line in text.split("\n"):
        if not line.strip():
            continue
        # 行内过长再按句号切
        segments = re.split(r'(?<=[。！？！])', line)
        for seg in segments:
            if not seg.strip():
                continue
            if len(seg) > max_chars:
                # 超长段硬切
                for i in range(0, len(seg), max_chars):
                    piece = seg[i:i + max_chars]
                    if len(cur) + len(piece) > max_chars and cur:
                        chunks.append(cur)
                        cur = ""
                    cur += piece
            elif len(cur) + len(seg) <= max_chars:
                cur += seg
            else:
                if cur:
                    chunks.append(cur)
                cur = seg
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------
# 任务状态管理（进程内存）
# ---------------------------------------------------------------------------
_tasks: Dict[str, Dict[str, Any]] = {}
_task_lock = threading.Lock()


def get_status(task_id: str) -> Optional[Dict[str, Any]]:
    with _task_lock:
        return dict(_tasks.get(task_id, {}))


# ---------------------------------------------------------------------------
# 抽取主流程（后台任务体）
# ---------------------------------------------------------------------------
def _extract_task_body(project_id: str, source: str, task_id: str) -> None:
    from ..models.task import TaskStatus
    llm_ok_count = 0
    heuristic_count = 0
    all_events: List[Dict[str, Any]] = []

    def _update(**kw):
        with _task_lock:
            if task_id in _tasks:
                _tasks[task_id].update(kw)

    try:
        # 读源文本
        if source == "story":
            text = _source_text(project_id, story=True)
        else:
            text = _source_text(project_id, story=False)

        chunks = chunk_text(text)
        total = len(chunks)
        _update(total_chunks=total, done_chunks=0, status="running", message="开始抽取")

        llm = None
        try:
            llm = _build_llm_client()
        except Exception as e:
            logger.warning(f"构造 LLM 客户端失败，全部走启发式: {e}")
            llm = None

        seq = 0
        for i, chunk in enumerate(chunks):
            used = "heuristic"
            events = None
            if llm is not None:
                for attempt in range(MAX_LLM_ATTEMPTS):
                    try:
                        events = _llm_extract_chunk(llm, chunk)
                        if events:
                            used = "llm"
                        break
                    except Exception:
                        if attempt == 0:
                            logger.warning(f"[{task_id}] chunk {i} LLM 失败，重试 {attempt+1}")
                        else:
                            logger.warning(f"[{task_id}] chunk {i} 重试仍失败，走启发式")
            if events is None:
                events = _heuristic_extract_chunk(chunk, i, source)
                used = "heuristic"
            if events:
                for raw in events:
                    ev = _normalize_event(raw, project_id, source, i, used, seq)
                    all_events.append(ev)
                    seq += 1
            if used == "llm":
                llm_ok_count += 1
            else:
                heuristic_count += 1
            _update(done_chunks=i + 1, llm_ok=llm_ok_count, heuristic=heuristic_count,
                    message=f"已处理 {i + 1}/{total} 块")

        # 排序 + 合并去重 + 写库
        all_events.sort(key=lambda e: (e.get("sort_lower") or 0))
        existing = load_timeline(project_id, None).get("events", [])
        existing_merged = _merge_events(existing, all_events)
        _save_timeline(project_id, existing_merged)

        if total == 0:
            _update(status="completed", done_chunks=0, llm_ok=0, heuristic=0,
                    message="源文本为空，未抽取到事件")
        elif heuristic_count > 0:
            _update(status="partial_failed", message=f"完成，{llm_ok_count} 块 LLM 抽取、{heuristic_count} 块启发式降级")
        else:
            _update(status="completed", message=f"抽取完成，共 {len(all_events)} 个事件")
    except ValueError as e:
        _update(status="failed", message=str(e))
    except Exception as e:
        logger.error(f"[{task_id}] 抽取失败: {e}")
        _update(status="failed", message=str(e))


def _merge_events(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把新抽事件并入现有事件，按 summary+location 近似去重（保留已有、跳过重复新事件）。"""
    seen = set()
    for e in existing:
        seen.add(_dedupe_key(e))
    for e in new:
        key = _dedupe_key(e)
        if key not in seen:
            seen.add(key)
            existing.append(e)
    return existing


def _dedupe_key(e: Dict[str, Any]) -> str:
    return f"{e.get('source')}|{e.get('summary')}|{e.get('location_name')}"


def _source_text(project_id: str, story: bool) -> str:
    from .world_bible import WorldBibleService
    bible = WorldBibleService.get_bible(project_id)
    if bible is None:
        return ""
    return bible.story_text if story else bible.background_text


# ---------------------------------------------------------------------------
# 对外启动接口
# ---------------------------------------------------------------------------
def start_extract(project_id: str, source: str) -> str:
    """校验 project_id/source，创建后台任务并返回 task_id。"""
    validate_project_id(project_id)
    if source not in ("story", "bg"):
        raise ValueError("source 必须是 story 或 bg")
    task_id = f"tl_task_{uuid.uuid4().hex[:12]}"
    with _task_lock:
        _tasks[task_id] = {
            "status": "running", "total_chunks": 0, "done_chunks": 0,
            "llm_ok": 0, "heuristic": 0, "message": "任务已创建",
        }
    threading.Thread(target=_extract_task_body, args=(project_id, source, task_id),
                     daemon=True).start()
    return task_id


# 供 /api/timeline 端点在后台线程调用（兼容 task_manager 风格的 run 函数签名）
run_extract = _extract_task_body


# ---------------------------------------------------------------------------
# future 事件（队长新增契约）：LLM 生成 kind='future' 事件追加到时间线
# ---------------------------------------------------------------------------
_FUTURE_SYSTEM = (
    "你是一名世界推演作者。请基于给定的任务目标与时间线上下文，生成若干条未来的事件。"
    "仅输出一个 JSON 数组。每事件含字段：summary(一句话)、time_text(相对未来时间表达如'五年后')、"
    "time_kind(枚举:year/phase/period/unspecified)、year(可推测填整数否则null)、"
    "location_text、location_name、ev_type(枚举同前)、confidence(0-1)、characters。"
)


def _future_extract_body(project_id: str, task_id: str, goal: str, horizon: Optional[int]) -> None:
    from ..models.task import TaskStatus
    with _task_lock:
        _tasks[task_id]["status"] = "running"
    try:
        llm = _build_llm_client()
        context = load_timeline(project_id, None)
        events = context.get("events", [])
        ctx_summary = "\n".join([f"- {e.get('summary')}" for e in events[:40]]) or "（无）"
        horizon_n = horizon or 5
        user = (
            f"任务目标：{goal or '无'}\n时间跨度（年）：{horizon_n}\n"
            f"当前时间线事件：\n{ctx_summary}\n请生成 3-6 条未来事件，输出 JSON 数组。"
        )
        resp = llm.chat(
            messages=[
                {"role": "system", "content": _FUTURE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.6, max_tokens=4096,
        )
        arr = _extract_json_array(resp)
        if not arr:
            raise ValueError("future 事件生成失败：LLM 未返回数组")
        seq = len(events)
        past_max = max(
            (e.get('sort_lower') or 0.0)
            for e in events if e.get('kind') != 'future' and e.get('source') != 'future'
        ) if events else 0.0
        new_events = []
        for raw in arr:
            if not isinstance(raw, dict):
                continue
            ev = _normalize_event(raw, project_id, "future", 0, "llm", seq)
            ev["ev_type"] = "future" if raw.get("ev_type") in (None, "", "other") else norm.normalize_ev_type(raw.get("ev_type"))
            new_events.append(ev)
            seq += 1
        # 未来事件必须排在"现在"之后（时间条虚线区）
        for i, ev in enumerate(new_events):
            ev["sort_lower"] = past_max + 1.0 + i
            ev["sort_upper"] = ev["sort_lower"]
        merged = _merge_events(events, new_events)
        _save_timeline(project_id, merged)
        with _task_lock:
            _tasks[task_id].update(status="completed", message=f"已追加 {len(new_events)} 条未来事件")
    except Exception as e:
        logger.error(f"[{task_id}] future 生成失败: {e}")
        with _task_lock:
            _tasks[task_id].update(status="failed", message=str(e))


def start_future(project_id: str, goal: str, horizon: Optional[int]) -> str:
    validate_project_id(project_id)
    task_id = f"tl_future_{uuid.uuid4().hex[:12]}"
    with _task_lock:
        _tasks[task_id] = {
            "status": "running", "total_chunks": 0, "done_chunks": 0,
            "llm_ok": 0, "heuristic": 0, "message": "生成未来事件中",
        }
    threading.Thread(target=_future_extract_body,
                     args=(project_id, task_id, goal or "", horizon),
                     daemon=True).start()
    return task_id


# ---------------------------------------------------------------------------
# 事件 PATCH
# ---------------------------------------------------------------------------
def patch_event(project_id: str, event_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按 event_id 更新某项目时间线中的事件，持久化。返回更新后事件；不存在返回 None。"""
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    target = next((e for e in events if e.get("id") == event_id), None)
    if target is None:
        return None
    if isinstance(patch, dict):
        for k, v in patch.items():
            if k == "sort_lower":
                target["sort_lower"] = float(v)
            elif k == "sort_upper":
                target["sort_upper"] = float(v)
            elif k == "year":
                target["year"] = _int_or_none(v)
                if v is not None and v != "":
                    target["sort_lower"] = float(v) * 10.0
                    target["sort_upper"] = float(v) * 10.0
            elif k == "age":
                target["age"] = _int_or_none(v)
                if v is not None and v != "":
                    target["sort_lower"] = float(v)
                    target["sort_upper"] = float(v)
            elif k in ("summary", "time_kind", "time_text", "location_text", "location_name",
                       "location_kind", "ev_type", "raw_source", "source", "extract_method"):
                if k == "time_kind":
                    target[k] = norm.normalize_time_kind(v)
                elif k == "ev_type":
                    target[k] = norm.normalize_ev_type(v)
                else:
                    target[k] = str(v) if v is not None else ""
            elif k == "characters":
                target[k] = _str_list(v)
            elif k == "confidence":
                target[k] = _float_or(v, 0.5)
            # 其余未知字段忽略，保持向前兼容
    target["updated_at"] = datetime.now().isoformat(timespec="seconds")
    events.sort(key=lambda e: (e.get("sort_lower") or 0))
    _save_timeline(project_id, events)
    return dict(target)
