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
# 分叉推演批 1 完成后等待运行中补充设定的窗口（秒）
FORK_GUIDANCE_WINDOW = 15.0

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
        # 兼容旧数据：source=='future'/'branch' 回填 kind；未来/分支事件强制排在"现在"之后
        if events:
            past_max = max(
                (e.get('sort_lower') or 0.0)
                for e in events
                if e.get('source') not in ('future', 'branch')
                and e.get('kind') not in ('future', 'branch')
            )
            fut = [e for e in events
                   if e.get('source') in ('future', 'branch')
                   or e.get('kind') in ('future', 'branch')]
            for i, e in enumerate(fut):
                if e.get('source') == 'future' and not e.get('kind'):
                    e['kind'] = 'future'
                if e.get('source') == 'branch' and not e.get('kind'):
                    e['kind'] = 'branch'
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
# 人物设定档案（characters）：data/world-timeline/<pid>/characters.json
# 存储格式：{"project_id": "...", "characters": [{"name","traits","description"}]}
# 供 fork/future/续推 提示词注入；_character_profiles 返回形如
# "阿米娅（罗德岛领袖；温柔坚韧）" 的注入串（合并 traits/description <=60 字）。
# ---------------------------------------------------------------------------
_CHAR_PROFILE_MAX = 60
_CHAR_INJECT_LIMIT = 12
_CHAR_SEED_LIMIT = 30
_CHAR_TRAITS_MAX = 120
_CHAR_DESC_MAX = 300


def _characters_path(project_id: str) -> str:
    return os.path.join(TIMELINE_ROOT, validate_project_id(project_id), "characters.json")


def load_characters(project_id: str) -> List[Dict[str, Any]]:
    """读取人物设定档案（存储格式 dict 列表）；不存在/失败返回 []。兼容旧版裸数组。"""
    try:
        path = _characters_path(project_id)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("characters") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("name"):
                out.append({
                    "name": str(it.get("name"))[:40],
                    "traits": str(it.get("traits") or "")[:_CHAR_TRAITS_MAX],
                    "description": str(it.get("description") or "")[:_CHAR_DESC_MAX],
                })
        return out
    except Exception as e:
        logger.warning(f"读取人物设定失败: {e}")
        return []


def save_characters(project_id: str, profiles: List[Dict[str, Any]]) -> bool:
    """保存人物设定档案到 characters.json（校验 name 非空、其余字段截断）。"""
    try:
        path = _characters_path(project_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        clean = []
        seen = set()
        for it in profiles:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            name = str(it.get("name"))[:40]
            if not name.strip() or name in seen:
                continue
            seen.add(name)
            clean.append({
                "name": name,
                "traits": str(it.get("traits") or "")[:_CHAR_TRAITS_MAX],
                "description": str(it.get("description") or "")[:_CHAR_DESC_MAX],
            })
        payload = {"project_id": project_id, "characters": clean}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning(f"写入人物设定失败: {e}")
        return False


def ensure_characters(project_id: str) -> List[Dict[str, Any]]:
    """读取人物设定；档案为空则从事件 characters 自动种子（去重、按出现次数降序、取前30，
    traits/description 为空串）并落盘。返回 dict 列表。"""
    profiles = load_characters(project_id)
    if profiles:
        return profiles
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    counts = {}
    for e in events:
        for c in (e.get("characters") or []):
            c = str(c).strip()
            if c:
                counts[c] = counts.get(c, 0) + 1
    seeded = []
    for name, _cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
        seeded.append({"name": name, "traits": "", "description": ""})
        if len(seeded) >= _CHAR_SEED_LIMIT:
            break
    if seeded:
        save_characters(project_id, seeded)
    return seeded


def _character_profiles(project_id: str, limit: int = _CHAR_INJECT_LIMIT) -> List[str]:
    """返回提示词注入用的人物设定串列表（读取或自动种子），形如
    "阿米娅（罗德岛领袖；温柔坚韧）"，traits/description 合并后 <=60 字；档案为空返回 []。"""
    profiles = ensure_characters(project_id)
    out = []
    for p in profiles[:max(1, limit)]:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        traits = str(p.get("traits") or "").strip()
        desc = str(p.get("description") or "").strip()
        if traits and desc:
            body = traits + "；" + desc
        else:
            body = traits or desc
        line = f"{name}（{body}）" if body else name
        out.append(line)
    return out


def _character_profiles_block(project_id: str, limit: int = _CHAR_INJECT_LIMIT) -> str:
    """生成 "人物设定：\n- name（traits；description）" 段，供提示词注入；空返回空串。"""
    items = _character_profiles(project_id, limit)
    if not items:
        return ""
    lines = ["人物设定："]
    for it in items:
        lines.append(f"- {it}")
    return "\n".join(lines)


def _trunc_summary(text: str, limit: int = 40) -> str:
    s = str(text or "").strip()
    return s[:limit] if len(s) > limit else s


# ---------------------------------------------------------------------------
# LLM 客户端构造（复用现有模型凭据 + iter 候选回退，不改 graphiti_patch）
# ---------------------------------------------------------------------------
def _build_llm_client(project_id: Optional[str] = None):
    """构造 OpenAI-compatible LLM 客户端，返回 LLMClient。

    1. 指定 project_id 时，优先使用该项目绑定的 primary 角色模型
       （用户在网页模型设置里为项目切换的模型立即对时间线任务生效）；
    2. 无项目绑定则走注册表候选（GRAPHITI_LLM → PRIMARY → 第一个已验证 chat）；
    3. 都没有才回退到默认环境配置 LLMClient()。
    """
    from ..utils.llm_client import LLMClient
    try:
        from .model_runtime import resolve_project_chat_config_any
        config = resolve_project_chat_config_any(project_id)
        if config:
            api_key, base_url, model = config
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
# 任务状态管理（进程内存 + 落盘持久化）
#
# 每个任务 dict 除旧字段（status/total_chunks/done_chunks/llm_ok/heuristic/
# message，保持前端兼容）外，新增：
#   stage     : str   当前阶段名（中文）
#   steps     : List[str]  最近 50 条步骤日志，形如 "[HH:MM:SS] 文本"
#   progress  : int   0-100 进度
#   started_at: str  ISO 时间串（任务创建时写入）
#   elapsed   : float 秒，每次更新时刷新 = now - started_at
#   error     : str   status=failed 时写入失败原因；正常为空
#
# 持久化：data/world-timeline/tasks/<task_id>.json（data/ 已 gitignore）
#   - _new_task 创建时 _update_task/_task_log 每次更新时落盘
#   - 落盘在带锁取副本、锁外写文件，避免持锁做 I/O
#   - 启动经 _ensure_tasks_loaded() 懒加载一次；status=running 的任务恢复为 interrupted
# ---------------------------------------------------------------------------
_tasks: Dict[str, Dict[str, Any]] = {}
_task_lock = threading.Lock()
_STEPS_MAX = 50
_tasks_loaded = False

_TASKS_DIR = os.path.join(TIMELINE_ROOT, "tasks")


def _task_file_path(task_id: str) -> str:
    return os.path.join(_TASKS_DIR, f"{task_id}.json")


def _persist_task(task_id: str) -> None:
    """在带锁取副本、锁外写文件。写失败仅警告（不阻断任务主流程）。"""
    if not task_id:
        return
    with _task_lock:
        if task_id not in _tasks:
            return
        snap = json.dumps(_tasks[task_id], ensure_ascii=False)
    try:
        os.makedirs(_TASKS_DIR, exist_ok=True)
        path = _task_file_path(task_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(snap)
    except Exception as e:
        logger.warning(f"持久化任务状态失败: {e}")


def _restore_interrupted(task: Dict[str, Any]) -> Dict[str, Any]:
    """把重启时残留的 running 任务标记为 interrupted。"""
    if task.get("status") == "running":
        task["status"] = "interrupted"
        task["stage"] = "已中断"
        task["error"] = "服务重启，任务中断"
        task["message"] = "任务已中断，请重新发起"
        steps = task.setdefault("steps", [])
        steps.append("[" + datetime.now().strftime("%H:%M:%S") + "] 服务重启，任务中断")
        if len(steps) > _STEPS_MAX:
            del steps[:-_STEPS_MAX]
        task["elapsed"] = _elapsed_seconds(task)
    return task


def _ensure_tasks_loaded() -> None:
    """懒加载一次磁盘上的任务状态；status=running → interrupted。幂等。"""
    global _tasks_loaded
    with _task_lock:
        if _tasks_loaded:
            return
        _tasks_loaded = True
        loaded = {}
        try:
            if os.path.isdir(_TASKS_DIR):
                for fn in os.listdir(_TASKS_DIR):
                    if not fn.endswith(".json"):
                        continue
                    tid = fn[:-5]
                    try:
                        with open(os.path.join(_TASKS_DIR, fn), "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict) and data.get("id"):
                            loaded[tid] = _restore_interrupted(dict(data))
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"加载任务状态失败: {e}")
        for tid, st in loaded.items():
            _tasks[tid] = st


def _new_task(prefix: str, message: str) -> str:
    """创建后台任务 dict（落盘），返回 task_id（统一打点基准）。"""
    _ensure_tasks_loaded()
    task_id = f"{prefix}_{uuid.uuid4().hex[:12]}"
    now = datetime.now()
    with _task_lock:
        _tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "total_chunks": 0, "done_chunks": 0, "llm_ok": 0, "heuristic": 0,
            "message": message,
            "stage": "任务已创建",
            "steps": [],
            "progress": 0,
            "started_at": now.isoformat(timespec="seconds"),
            "elapsed": 0.0,
            "error": "",
        }
    _persist_task(task_id)
    return task_id


def _elapsed_seconds(task: Dict[str, Any]) -> float:
    started = task.get("started_at")
    if not started:
        return 0.0
    try:
        return max(0.0, (datetime.now() - datetime.fromisoformat(str(started))).total_seconds())
    except Exception:
        return 0.0


def _update_task(task_id: str, **kw) -> None:
    """更新任务字段并刷新 elapsed（带锁），并落盘。"""
    _ensure_tasks_loaded()
    changed = False
    with _task_lock:
        if task_id not in _tasks:
            return
        task = _tasks[task_id]
        task.update(kw)
        task["elapsed"] = _elapsed_seconds(task)
        changed = True
    if changed:
        _persist_task(task_id)


def _task_log(task_id: str, text: str) -> None:
    """追加一条步骤日志（自动带 [HH:MM:SS] 时间戳，自动截断到 50 条），刷新 elapsed + 落盘。"""
    _ensure_tasks_loaded()
    changed = False
    ts = datetime.now().strftime("%H:%M:%S")
    with _task_lock:
        if task_id not in _tasks:
            return
        task = _tasks[task_id]
        steps = task.setdefault("steps", [])
        steps.append("[" + ts + "] " + text)
        if len(steps) > _STEPS_MAX:
            del steps[:-_STEPS_MAX]
        task["elapsed"] = _elapsed_seconds(task)
        changed = True
    if changed:
        _persist_task(task_id)


def get_status(task_id: str) -> Optional[Dict[str, Any]]:
    _ensure_tasks_loaded()
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

    # 局部 _update：刷新 elapsed 的便捷封装
    def _update(**kw):
        _update_task(task_id, **kw)

    try:
        # 读源文本
        if source == "story":
            text = _source_text(project_id, story=True)
        else:
            text = _source_text(project_id, story=False)

        chunks = chunk_text(text)
        total = len(chunks)
        _task_log(task_id, f"源文本已分为 {total} 块")
        _update(total_chunks=total, done_chunks=0, status="running", message="开始抽取",
                stage=f"准备源文本（共 {total} 块）", progress=0)

        llm = None
        try:
            llm = _build_llm_client(project_id)
        except Exception as e:
            logger.warning(f"构造 LLM 客户端失败，全部走启发式: {e}")
            _task_log(task_id, "LLM 客户端不可用，改用启发式抽取")

        seq = 0
        for i, chunk in enumerate(chunks):
            used = "heuristic"
            events = None
            if llm is not None:
                _task_log(task_id, f"第 {i + 1}/{total} 块开始 LLM 抽取")
                for attempt in range(MAX_LLM_ATTEMPTS):
                    try:
                        events = _llm_extract_chunk(llm, chunk)
                        if events:
                            used = "llm"
                        break
                    except Exception:
                        if attempt == 0:
                            logger.warning(f"[{task_id}] chunk {i} LLM 失败，重试 {attempt+1}")
                            _task_log(task_id, f"第 {i + 1} 块 LLM 失败，重试")
                        else:
                            logger.warning(f"[{task_id}] chunk {i} 重试仍失败，走启发式")
                            _task_log(task_id, f"第 {i + 1} 块重试仍失败，降级启发式")
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
            pct = round((i + 1) / total * 100) if total else 0
            _update(done_chunks=i + 1, llm_ok=llm_ok_count, heuristic=heuristic_count,
                    progress=pct,
                    message=f"已处理 {i + 1}/{total} 块",
                    stage=f"正在抽取 {i + 1}/{total} 块（{'LLM' if used == 'llm' else '启发式'}）")

        # 排序 + 合并去重 + 写库
        _task_log(task_id, "归一化并排序事件")
        _update(stage="写入时间线", progress=98)
        all_events.sort(key=lambda e: (e.get("sort_lower") or 0))
        existing = load_timeline(project_id, None).get("events", [])
        existing_merged = _merge_events(existing, all_events)
        _save_timeline(project_id, existing_merged)

        if total == 0:
            _task_log(task_id, "源文本为空，未抽取到事件")
            _update(status="completed", done_chunks=0, llm_ok=0, heuristic=0, progress=100,
                    stage="完成", message="源文本为空，未抽取到事件")
        elif heuristic_count > 0:
            _task_log(task_id, f"完成：{llm_ok_count} 块 LLM、{heuristic_count} 块启发式降级（共 {len(all_events)} 事件）")
            _update(status="partial_failed", progress=100, stage="完成（部分降级）",
                    message=f"完成，{llm_ok_count} 块 LLM 抽取、{heuristic_count} 块启发式降级")
        else:
            _task_log(task_id, f"抽取完成，共 {len(all_events)} 个事件")
            _update(status="completed", progress=100, stage="完成",
                    message=f"抽取完成，共 {len(all_events)} 个事件")
    except ValueError as e:
        _task_log(task_id, f"失败：{e}")
        _update(status="failed", error=str(e), stage="失败", message=str(e))
    except Exception as e:
        logger.error(f"[{task_id}] 抽取失败: {e}")
        _task_log(task_id, f"失败：{e}")
        _update(status="failed", error=str(e), stage="失败", message=str(e))


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
    task_id = _new_task("tl_task", "任务已创建")
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
        _task_log(task_id, "构建未来推演上下文")
        _update_task(task_id, stage="构建推演上下文", progress=20)
        llm = _build_llm_client(project_id)
        context = load_timeline(project_id, None)
        events = context.get("events", [])
        ctx_summary = "\n".join([f"- {_trunc_summary(e.get('summary'))}" for e in events[:40]]) or "（无）"
        horizon_n = horizon or 5
        chars_block = _inject_characters_block(project_id)
        user = (
            f"任务目标：{goal or '无'}\n时间跨度（年）：{horizon_n}\n"
            f"当前时间线事件：\n{ctx_summary}\n"
            + (chars_block + "\n" if chars_block else "")
            + "请生成 3-6 条未来事件，输出 JSON 数组。"
        )
        _task_log(task_id, "调用未来模型")
        _update_task(task_id, stage="调用推演模型", progress=50)
        resp = llm.chat(
            messages=[
                {"role": "system", "content": _FUTURE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.6, max_tokens=4096,
        )
        _task_log(task_id, "解析生成结果")
        _update_task(task_id, stage="解析生成结果", progress=75)
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
        _task_log(task_id, "写入时间线")
        _update_task(task_id, stage="写入时间线", progress=90)
        merged = _merge_events(events, new_events)
        _save_timeline(project_id, merged)
        _task_log(task_id, f"已追加 {len(new_events)} 条未来事件")
        _update_task(task_id, status="completed", progress=100, stage="完成",
                     message=f"已追加 {len(new_events)} 条未来事件")
    except Exception as e:
        logger.error(f"[{task_id}] future 生成失败: {e}")
        _task_log(task_id, f"失败：{e}")
        _update_task(task_id, status="failed", error=str(e), stage="失败", message=str(e))


def start_future(project_id: str, goal: str, horizon: Optional[int]) -> str:
    validate_project_id(project_id)
    task_id = _new_task("tl_future", "生成未来事件中")
    threading.Thread(target=_future_extract_body,
                     args=(project_id, task_id, goal or "", horizon),
                     daemon=True).start()
    return task_id


# ---------------------------------------------------------------------------
# 时间点分叉推演（fork）：在某历史事件点生成分支未来事件（分批 + guidance 注入）
# guidance 为 List[str]（每条补充设定），事件携带 branch_goal / 生效时的全部 guidance 列表。
# ---------------------------------------------------------------------------
_FORK_SYSTEM = (
    "你是一名世界推演作者。请基于给定的分叉前提与时间线上下文，生成若干条分支未来的事件。"
    "仅输出一个 JSON 数组。每事件含字段：summary(一句话)、time_text(相对时间表达)、"
    "time_kind(枚举:year/phase/period/unspecified)、year(可推测填整数否则null)、"
    "location_text、location_name、ev_type(枚举同前)、confidence(0-1)、characters。"
)
_FORK_CONT_SYSTEM = (
    "你是一名世界推演作者。请基于给定的分支前提与已生成的分支事件，续写若干条后续分支事件。"
    "仅输出一个 JSON 数组。每事件含字段：summary(一句话)、time_text(相对时间表达)、"
    "time_kind(枚举:year/phase/period/unspecified)、year(可推测填整数否则null)、"
    "location_text、location_name、ev_type(枚举同前)、confidence(0-1)、characters。"
)


def _coerce_guidance(guidance) -> List[str]:
    """把 guidance（str 或 List[str]）规范化为非空字符串列表。"""
    if guidance is None:
        return []
    if isinstance(guidance, list):
        return [str(g).strip() for g in guidance if str(g).strip()]
    s = str(guidance).strip()
    return [s] if s else []


def _render_guidance_list(guidance_list) -> str:
    """把补充设定列表渲染成逐条 "- " 文本；空返回空串。"""
    items = [str(g).strip() for g in (guidance_list or []) if str(g).strip()]
    if not items:
        return ""
    return "\n".join(f"- {it}" for it in items)


def _build_branch_events(arr, project_id, branch_id, branch_point, branch_goal,
                         guidance_list, sort_base, seq):
    """把 LLM 数组归一化为 branch 事件（带 branch_id/branch_point/branch_goal/guidance 列表，
    sort 从 sort_base 起递增）。返回 (事件列表, 新 seq)。"""
    out = []
    i = 0
    g_list = list(guidance_list or []) if guidance_list else []
    for raw in arr:
        if not isinstance(raw, dict):
            continue
        ev = _normalize_event(raw, project_id, "branch", 0, "llm", seq)
        ev["ev_type"] = "future" if raw.get("ev_type") in (None, "", "other") else norm.normalize_ev_type(raw.get("ev_type"))
        ev["kind"] = "branch"
        ev["branch_id"] = branch_id
        ev["branch_point"] = branch_point
        ev["branch_goal"] = branch_goal
        ev["guidance"] = list(g_list)
        ev["sort_lower"] = sort_base + i
        ev["sort_upper"] = sort_base + i
        out.append(ev)
        seq += 1
        i += 1
    return out, seq


def _fork_call(llm, system, user):
    """单次 fork/续推 LLM 调用（允许 1 次重试），返回事件数组或 None。"""
    for attempt in range(2):
        try:
            resp = llm.chat(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.7, max_tokens=4096,
            )
            arr = _extract_json_array(resp)
            if arr:
                return arr
        except Exception:
            if attempt == 0:
                continue
    return None


def _build_fork_context(events, branch_point):
    bp_sort = float(branch_point.get("sort_lower") or 0.0)
    after = [e for e in events if (e.get("sort_lower") or 0.0) > bp_sort]
    ctx_lines = [f"- [分叉点] {_trunc_summary(branch_point.get('summary'))}"]
    for e in after[:12]:
        ctx_lines.append(f"- {_trunc_summary(e.get('summary'))}")
    ctx = "\n".join(ctx_lines) or _trunc_summary(branch_point.get('summary', ''))
    return bp_sort, ctx


def _inject_characters_block(project_id):
    """人物设定注入段（<=2600 约束的一部分）。"""
    return _character_profiles_block(project_id, _CHAR_INJECT_LIMIT)


def _preserve_prompt_budget(user_parts):
    return user_parts


def _fork_extract_body(project_id: str, event_id: str, task_id: str,
                       goal: str, horizon: Optional[int],
                       guidance: Optional[List[str]]) -> None:
    with _task_lock:
        _tasks[task_id]["status"] = "running"
    try:
        _task_log(task_id, "构建分叉推演上下文")
        _update_task(task_id, stage="构建推演上下文", progress=10)
        llm = _build_llm_client(project_id)
        data = load_timeline(project_id, None)
        events = data.get("events", [])
        branch_point = next((e for e in events if e.get("id") == event_id), None)
        if branch_point is None:
            raise ValueError(f"分叉点事件不存在: {event_id}")
        bp_sort, ctx = _build_fork_context(events, branch_point)
        base = bp_sort + 1.0
        horizon_n = horizon or 5
        branch_goal = goal or "（自由发散）"
        chars_block = _inject_characters_block(project_id)
        branch_id = f"branch_{uuid.uuid4().hex[:12]}"
        seq = len(events)
        all_new = []

        # 初始 guidance（启动时传入）
        initial_guidance = [str(g).strip() for g in (guidance or []) if str(g).strip()]
        g_prefix = "已有的补充设定：\n" + _render_guidance_list(initial_guidance) + "\n" if initial_guidance else ""

        # ---- 批 1：前半段 2-3 条 ----
        user1 = (
            f"分叉前提事件：{_trunc_summary(branch_point.get('summary'))}\n"
            f"假设该事件走向不同：{goal or '（自由发散）'}\n"
            f"时间跨度（年）：{horizon_n}\n当前时间线（分叉点及之后）：\n{ctx}\n"
            + g_prefix
            + (chars_block + "\n" if chars_block else "")
            + "请先生成前半段 2-3 条该分支的未来事件，输出 JSON 数组。"
        )
        _task_log(task_id, "调用推演模型（第 1/2 批）")
        _update_task(task_id, stage="调用推演模型（第 1/2 批）", progress=40)
        arr1 = _fork_call(llm, _FORK_SYSTEM, user1)
        if not arr1:
            raise ValueError("分叉推演失败：前半段 LLM 未返回数组（或无法解析 JSON）")
        evs1, seq = _build_branch_events(arr1, project_id, branch_id, event_id,
                                          branch_goal, initial_guidance, base, seq)
        all_new.extend(evs1)
        consumed = len(initial_guidance)
        _task_log(task_id, f"前半段生成 {len(evs1)} 条")

        # ---- 批 2：短暂等待窗口，允许用户运行中注入补充设定 ----
        # 批 1 完成后等待 FORK_GUIDANCE_WINDOW 秒：期间用户可通过
        # POST /api/timeline/fork/guidance 注入引导；一旦检测到新增即立即续写。
        _update_task(task_id, stage="等待补充设定（约 15 秒，可在此注入）", progress=60)
        _task_log(task_id, "前半段完成，等待补充设定（约 15 秒，可注入引导）…")
        merged_guidance = list(initial_guidance)
        cur = list(merged_guidance)
        deadline = time.time() + FORK_GUIDANCE_WINDOW
        while time.time() < deadline:
            with _task_lock:
                cur = list(_tasks.get(task_id, {}).get("guidance") or [])
            if len(cur) > len(merged_guidance):
                merged_guidance = [str(g).strip() for g in cur if str(g).strip()]
                _task_log(task_id, "检测到补充设定，立即续写后半段")
                break
            time.sleep(0.5)
        else:
            merged_guidance = [str(g).strip() for g in cur if str(g).strip()]
        new_items = merged_guidance[consumed:]
        _task_log(task_id, "调用续写模型（第 2/2 批）")
        _update_task(task_id, stage="调用推演模型（第 2/2 批）", progress=70)

        ev_so_far = "\n".join([f"- {_trunc_summary(e.get('summary'))}" for e in all_new]) or "（无）"
        g_line = "补充设定：\n" + _render_guidance_list(merged_guidance) + "\n" if merged_guidance else ""
        g_new_line = ("补充设定（运行中新增）：\n" + _render_guidance_list(new_items) + "\n") if new_items else ""
        user2 = (
            f"分支前提：{_trunc_summary(branch_point.get('summary'))}\n"
            f"分支目标：{branch_goal}\n"
            f"已生成分支事件：\n{ev_so_far}\n"
            + g_line
            + g_new_line
            + (chars_block + "\n" if chars_block else "")
            + "请续写该分支的后半段 2-3 条未来事件，保持与前段连续，输出 JSON 数组。"
        )
        try:
            arr2 = _fork_call(llm, _FORK_CONT_SYSTEM, user2)
            if arr2:
                evs2, seq = _build_branch_events(arr2, project_id, branch_id, event_id,
                                                  branch_goal, merged_guidance, base + len(all_new), seq)
                all_new.extend(evs2)
                _task_log(task_id, f"后半段生成 {len(evs2)} 条")
            else:
                _task_log(task_id, "后半段结果为空或解析失败，保留前半段")
        except Exception as e2:
            _task_log(task_id, f"后半段失败：{e2}，保留前半段")

        _task_log(task_id, "写入时间线")
        _update_task(task_id, stage="写入时间线", progress=90)
        merged = _merge_events(events, all_new)
        _save_timeline(project_id, merged)
        _task_log(task_id, f"已追加 {len(all_new)} 条分支事件（branch={branch_id}）")
        # 若批 2 未产出（仅前半段），标 partial 完成
        if len(all_new) == len(evs1) and evs1:
            _update_task(task_id, status="completed", progress=100, stage="完成（前半段）",
                         branch_id=branch_id, event_count=len(all_new),
                         guidance=list(merged_guidance),
                         partial=True,
                         message="前半段已完成，可继续补充设定续推")
        else:
            _update_task(task_id, status="completed", progress=100, stage="完成",
                         branch_id=branch_id, event_count=len(all_new),
                         guidance=list(merged_guidance),
                         message=f"分叉推演完成，追加 {len(all_new)} 条分支事件（branch={branch_id}）")
    except Exception as e:
        logger.error(f"[{task_id}] fork 推演失败: {e}")
        _task_log(task_id, f"失败：{e}")
        _update_task(task_id, status="failed", error=str(e), stage="失败", message=str(e))


def start_fork(project_id: str, event_id: str, goal: str, horizon: Optional[int],
               guidance: Optional[List[str]] = None) -> str:
    """在 event_id 事件点发起分叉推演（后台任务，分批+guidance 注入），返回 task_id。"""
    validate_project_id(project_id)
    if not event_id or not str(event_id).strip():
        raise ValueError("缺少 event_id")
    g_list = _coerce_guidance(guidance)
    task_id = _new_task("tl_fork", "分叉推演中")
    with _task_lock:
        _tasks[task_id]["guidance"] = list(g_list)
        _tasks[task_id]["guidance_consumed"] = 0
    threading.Thread(target=_fork_extract_body,
                     args=(project_id, str(event_id).strip(), task_id,
                           goal or "", horizon, list(g_list)),
                     daemon=True).start()
    return task_id


def inject_fork_guidance(task_id: str, guidance: str) -> Dict[str, Any]:
    """对运行中的 fork 任务注入/追加一条 guidance（≤200 字）。"""
    guidance = str(guidance or "").strip()
    if not guidance:
        raise ValueError("guidance 不能为空")
    if len(guidance) > 200:
        raise ValueError("guidance 过长（≤200 字）")
    with _task_lock:
        task = _tasks.get(task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.get("status") != "running" or not str(task_id).startswith("tl_fork_"):
        raise ValueError("推演已结束，可在分支上继续补充设定续推")
    with _task_lock:
        cur = list(_tasks[task_id].get("guidance") or [])
        cur.append(guidance)
        _tasks[task_id]["guidance"] = cur
        _tasks[task_id]["message"] = "已收到补充设定"
        _tasks[task_id]["elapsed"] = _elapsed_seconds(_tasks[task_id])
    _task_log(task_id, f"收到补充设定：{guidance[:40]}")
    return {"accepted": "running", "guidance": list(cur)}


# ---------------------------------------------------------------------------
# 分支续推（branch continue）：从某分支当前末尾续推后续事件
# ---------------------------------------------------------------------------
def _fork_continue_body(project_id: str, branch_id: str, task_id: str,
                        guidance: Optional[List[str]], horizon: Optional[int]) -> None:
    with _task_lock:
        _tasks[task_id]["status"] = "running"
    try:
        _task_log(task_id, "构建续推上下文")
        _update_task(task_id, stage="构建续推上下文", progress=20)
        llm = _build_llm_client(project_id)
        data = load_timeline(project_id, None)
        events = data.get("events", [])
        branch_events = [e for e in events if e.get("branch_id") == branch_id]
        if not branch_events:
            raise ValueError(f"分支不存在: {branch_id}")
        max_sort = max((float(e.get("sort_lower") or 0.0)) for e in branch_events)
        base = max_sort + 1.0
        bp = branch_events[0].get("branch_point", "")
        branch_goal = branch_events[0].get("branch_goal", "")
        existing_g = list(branch_events[0].get("guidance") or []) if branch_events else []
        new_g = [str(g).strip() for g in (guidance or []) if str(g).strip()]
        merged_g = list(dict.fromkeys(existing_g + new_g))
        bp_summary = ""
        bp_ev = next((e for e in events if e.get("id") == bp), None)
        if bp_ev is not None:
            bp_summary = _trunc_summary(bp_ev.get("summary"))
        sorted_branch = sorted(branch_events, key=lambda x: x.get('sort_lower') or 0)
        ev_ctx_lines = [f"- {_trunc_summary(e.get('summary'))}" for e in sorted_branch[:12]]
        ev_ctx = "\n".join(ev_ctx_lines) if ev_ctx_lines else "（无）"
        chars_block = _inject_characters_block(project_id)
        horizon_n = horizon or 5
        g_line = "补充设定：\n" + _render_guidance_list(merged_g) + "\n" if merged_g else ""
        g_new_line = ("补充设定（新增）：\n" + _render_guidance_list(new_g) + "\n") if new_g else ""
        user = (
            f"分叉点：{bp_summary or '（未知）'}\n"
            f"分支目标：{branch_goal or ''}\n已生成分支事件：\n{ev_ctx}\n"
            f"时间跨度（年）：{horizon_n}\n"
            + g_line
            + g_new_line
            + (chars_block + "\n" if chars_block else "")
            + "请续写该分支 2-4 条后续事件，保持连续，输出 JSON 数组。"
        )
        _task_log(task_id, "调用续推模型")
        _update_task(task_id, stage="调用续推模型", progress=55)
        arr = _fork_call(llm, _FORK_CONT_SYSTEM, user)
        if not arr:
            raise ValueError("续推失败：LLM 未返回数组（或无法解析 JSON）")
        seq = len(events)
        new_events, seq = _build_branch_events(arr, project_id, branch_id, bp,
                                                branch_goal, merged_g, base, seq)
        _task_log(task_id, "写入时间线")
        _update_task(task_id, stage="写入时间线", progress=90)
        merged = _merge_events(events, new_events)
        _save_timeline(project_id, merged)
        _task_log(task_id, f"已续推 {len(new_events)} 条")
        _update_task(task_id, status="completed", progress=100, stage="完成",
                     branch_id=branch_id, event_count=len(new_events),
                     guidance=list(merged_g),
                     message=f"分支续推完成，追加 {len(new_events)} 条")
    except Exception as e:
        logger.error(f"[{task_id}] branch continue 失败: {e}")
        _task_log(task_id, f"失败：{e}")
        _update_task(task_id, status="failed", error=str(e), stage="失败", message=str(e))


def branch_exists(project_id: str, branch_id: str) -> bool:
    """判断某分支（kind='branch' 且 branch_id 匹配）是否存在事件。"""
    try:
        data = load_timeline(project_id, None)
        return any(e.get("branch_id") == branch_id for e in data.get("events", []))
    except Exception:
        return False


def compare_branch(project_id: str, branch_id: str):
    """对比某分支与主线的差异。

    读全部事件：分叉点 sort=bp_sort；before=分叉点及之前的主线事件；
    base_after=主线事件 sort>bp_sort；branch_events=该分支事件（升序）。
    贪心配对 difflib.SequenceMatcher ratio>=0.55 → changed（event=分支事件、
    base_event=主线事件）；未配对 → base_only / branch_new。
    分支不存在返回 None。返回 {branch_id, branch_point_id, branch_point_summary, entries}。
    """
    import difflib
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    branch_events = sorted([e for e in events if e.get("branch_id") == branch_id],
                           key=lambda e: e.get("sort_lower") or 0)
    if not branch_events:
        return None
    bp_id = branch_events[0].get("branch_point") or ""
    bp_ev = next((e for e in events if e.get("id") == bp_id), None)
    bp_sort = float(bp_ev.get("sort_lower") or 0.0) if bp_ev else 0.0
    bp_summary = str(bp_ev.get("summary") or "") if bp_ev else ""
    # 主线事件 = 非分支事件（不含本次分支及其它分支），用于对比
    mainline = [e for e in events if e.get("kind") != "branch"]
    before = [e for e in mainline if (e.get("sort_lower") or 0.0) <= bp_sort]
    base_after = [e for e in mainline if (e.get("sort_lower") or 0.0) > bp_sort]

    def _sim(a, b):
        return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio()

    entries = []
    for e in before:
        entries.append({"kind": "before", "event": e})
    # 贪心配对：对每个 branch_event 找一个未配对的 base_after 事件最大相似
    base_used = [False] * len(base_after)
    branch_new = []
    for be in branch_events:
        best_i = -1
        best_ratio = 0.0
        for bi, me in enumerate(base_after):
            if base_used[bi]:
                continue
            ratio = _sim(be.get("summary"), me.get("summary"))
            if ratio > best_ratio:
                best_ratio = ratio
                best_i = bi
        if best_i != -1 and best_ratio >= 0.55:
            base_used[best_i] = True
            entries.append({"kind": "changed", "event": be, "base_event": base_after[best_i]})
        else:
            branch_new.append(be)
    for bi, me in enumerate(base_after):
        if not base_used[bi]:
            entries.append({"kind": "base_only", "event": me})
    for be in branch_new:
        entries.append({"kind": "branch_new", "event": be})
    return {
        "branch_id": branch_id,
        "branch_point_id": bp_id,
        "branch_point_summary": bp_summary,
        "entries": entries,
    }


def start_branch_continue(project_id: str, branch_id: str, guidance=None,
                          horizon: Optional[int] = None) -> str:
    """从某分支当前末尾续推（后台任务 tl_forkcont_*），返回 task_id；复用 /status。"""
    validate_project_id(project_id)
    branch_id = str(branch_id or "").strip()
    if not branch_id:
        raise ValueError("缺少 branch_id")
    g_list = _coerce_guidance(guidance)
    task_id = _new_task("tl_forkcont", "分支续推中")
    threading.Thread(target=_fork_continue_body,
                     args=(project_id, branch_id, task_id, list(g_list), horizon),
                     daemon=True).start()
    return task_id


# ---------------------------------------------------------------------------
# 事件异议（objection）：直接往事件 dict 追加 objections 数组
# ---------------------------------------------------------------------------
# 异议分类枚举（与前端 objection.cat.* 一致）
_OBJECTION_CATEGORIES = ("event_attr", "classification", "time", "location", "other")


def add_objection(project_id: str, event_id: str,
                  category: str, reason: str, suggestion: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """对一条事件提交异议；persist 后返回更新后事件（含 objections）。不存在返回 None。

    校验：category 必须是 _OBJECTION_CATEGORIES 之一、reason 非空，否则抛 ValueError（路由转 400）。
    """
    category = str(category or "").strip()
    reason = str(reason or "").strip()
    if category not in _OBJECTION_CATEGORIES:
        raise ValueError(f"异议分类必须是: {'、'.join(_OBJECTION_CATEGORIES)}")
    if not reason:
        raise ValueError("异议理由不能为空")
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    target = next((e for e in events if e.get("id") == event_id), None)
    if target is None:
        return None
    if not isinstance(target.get("objections"), list):
        target["objections"] = []
    target["objections"].append({
        "id": f"obj_{uuid.uuid4().hex[:12]}",
        "category": category[:40],
        "reason": reason[:500],
        "suggestion": str(suggestion or "").strip()[:500] if suggestion else "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    target["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_timeline(project_id, events)
    return dict(target)


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
                target["sort_lower"] = _float_or(v, target.get("sort_lower", 0.0))
            elif k == "sort_upper":
                target["sort_upper"] = _float_or(v, target.get("sort_upper", 0.0))
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
    target["updated_at"] = datetime.now().isoformat(timespec="seconds")
    events.sort(key=lambda e: (e.get("sort_lower") or 0))
    _save_timeline(project_id, events)
    return dict(target)
# ---------------------------------------------------------------------------
# 事件删除（delete）与合并（merge）
# ---------------------------------------------------------------------------
def delete_event(project_id: str, event_id: str) -> bool:
    """删除指定事件并持久化（仅删该事件，不级联删分支）。存在返回 True，不存在返回 False。"""
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    before = len(events)
    events = [e for e in events if e.get("id") != event_id]
    if len(events) == before:
        return False
    events.sort(key=lambda e: e.get("sort_lower") or 0)
    _save_timeline(project_id, events)
    return True


def merge_events(project_id: str, target_id: str, source_ids: List[str]) -> Optional[Dict[str, Any]]:
    """把若干 source 事件合并进 target 事件，删除 source，持久化，返回合并后 target。

    - characters/entities 去重合并（target 在前）
    - objections 拼接
    - confidence 取 max
    - location_name 若 target 为空则取第一个非空 source
    - target 或任一 source 不存在 → 返回 None
    """
    data = load_timeline(project_id, None)
    events = data.get("events", [])
    src_ids = [s for s in (source_ids or []) if s]
    if not target_id or not src_ids:
        return None
    target = next((e for e in events if e.get("id") == target_id), None)
    if target is None:
        return None
    sources = []
    for sid in src_ids:
        src = next((e for e in events if e.get("id") == sid), None)
        if src is None:
            return None
        sources.append(src)

    # characters/entities 去重（target 在前）
    def _merge_uniq(target_list, src_list):
        seen = set()
        out = []
        for v in list(target_list or []) + list(src_list or []):
            key = str(v).strip()
            if key and key not in seen:
                seen.add(key)
                out.append(str(v))
        return out

    target["characters"] = _merge_uniq(target.get("characters"), _concat_lists([s.get("characters") for s in sources]))
    target["entities"] = _merge_uniq(target.get("entities"), _concat_lists([s.get("entities") for s in sources]))

    # objections 拼接
    objs = []
    for s in sources:
        for o in (s.get("objections") or []):
            objs.append(o)
    target["objections"] = (target.get("objections") or []) + objs

    # confidence 取 max
    c = target.get("confidence")
    for s in sources:
        sc = s.get("confidence")
        if isinstance(sc, (int, float)) and (not isinstance(c, (int, float)) or sc > c):
            c = sc
    if isinstance(c, (int, float)):
        target["confidence"] = c

    # location_name 若 target 空则取第一个非空 source
    if not str(target.get("location_name") or "").strip():
        for s in sources:
            ln = str(s.get("location_name") or "").strip()
            if ln:
                target["location_name"] = ln
                break

    target["updated_at"] = datetime.now().isoformat(timespec="seconds")
    # 删除 source
    source_set = set(s.get("id") for s in sources)
    events = [e for e in events if e.get("id") not in source_set]
    events.sort(key=lambda e: (e.get("sort_lower") or 0))
    _save_timeline(project_id, events)
    return dict(target)


def _concat_lists(lists) -> List[str]:
    out = []
    for lst in lists:
        for v in (lst or []):
            out.append(v)
    return out
_CHAR_GEN_SYSTEM = (
    "你是小说世界人物设定助手。请为给定的人物名单生成简短的 traits（性格/特质，<=120字）"
    "与 description（背景描述，<=300字）。仅输出一个 JSON 数组，每项含 name/traits/description，"
    "不要多余文字。")
_CHAR_GEN_CANDIDATE_LIMIT = 20


def _characters_generate_body(project_id: str, task_id: str) -> None:
    with _task_lock:
        if task_id in _tasks:
            _tasks[task_id]["status"] = "running"
    try:
        _task_log(task_id, "读取人物设定档案")
        _update_task(task_id, stage="构建输入", progress=15)
        profiles = ensure_characters(project_id)
        # 候选 = traits 与 description 均为空的条目（最多 20）
        candidates = [
            p for p in profiles
            if not str(p.get("traits") or "").strip() and not str(p.get("description") or "").strip()
        ][:_CHAR_GEN_CANDIDATE_LIMIT]
        if not candidates:
            _task_log(task_id, "所有人物已有设定，无需生成")
            _update_task(task_id, status="completed", progress=100, stage="完成",
                         message="所有人物已有设定，无需生成")
            return

        names = [str(p.get("name") or "") for p in candidates]
        # 输入：候选名字 + 时间线事件摘要（前 30 条，40 字截断）
        data = load_timeline(project_id, None)
        events = data.get("events", [])
        ctx_lines = []
        for e in events[:30]:
            s = _trunc_summary(e.get("summary"))
            if s:
                ctx_lines.append("- " + s)
        ctx = "\n".join(ctx_lines) if ctx_lines else "（无时间线事件）"
        user = (
            "需生成设定的人物："
            + "、".join(names)
            + "\n时间线事件（供参考）：\n"
            + ctx
            + "\n请为每个人物输出 traits 与 description，JSON 数组。"
        )

        _task_log(task_id, "调用模型生成人物设定")
        _update_task(task_id, stage="调用模型", progress=50)
        llm = _build_llm_client(project_id)
        arr = _char_gen_call(llm, user)
        _task_log(task_id, "解析生成结果")
        _update_task(task_id, stage="解析结果", progress=80)
        if not arr:
            raise ValueError("人物设定生成失败：LLM 未返回数组")

        _task_log(task_id, "合并保存（仅填空字段，不覆盖既有设定）")
        _update_task(task_id, stage="合并保存", progress=90)
        by_name = {}
        for p in profiles:
            by_name[str(p.get("name") or "").strip()] = p
        filled = 0
        for item in arr:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            target = by_name.get(name)
            if target is None:
                continue
            # 仅当 traits/description 仍为空时填入；不覆盖非空
            if not str(target.get("traits") or "").strip():
                target["traits"] = str(item.get("traits") or "").strip()[:_CHAR_TRAITS_MAX]
            if not str(target.get("description") or "").strip():
                target["description"] = str(item.get("description") or "").strip()[:_CHAR_DESC_MAX]
            if (str(target.get("traits") or "").strip() or str(target.get("description") or "").strip()):
                filled += 1
        save_characters(project_id, profiles)
        _task_log(task_id, f"已生成 {filled} 位人物设定初稿")
        _update_task(task_id, status="completed", progress=100, stage="完成",
                     message=f"已生成 {filled} 位人物设定初稿")
    except Exception as e:
        logger.error(f"[{task_id}] characters generate 失败: {e}")
        _task_log(task_id, f"失败：{e}")
        _update_task(task_id, status="failed", error=str(e), stage="失败", message=str(e))


def _char_gen_call(llm, user):
    """一次人物设定生成调用（允许 1 次重试），返回 [{name,traits,description}] 数组或 None。"""
    for attempt in range(2):
        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": _CHAR_GEN_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.6, max_tokens=4096,
            )
            arr = _extract_json_array(resp)
            if arr:
                return arr
        except Exception:
            if attempt == 0:
                continue
    return None


def start_characters_generate(project_id: str) -> str:
    """异步生成人物设定初稿（后台任务 tl_chargen_*），返回 task_id；复用 /status 轮询。"""
    validate_project_id(project_id)
    task_id = _new_task("tl_chargen", "生成人物设定中")
    threading.Thread(target=_characters_generate_body, args=(project_id, task_id),
                     daemon=True).start()
    return task_id
