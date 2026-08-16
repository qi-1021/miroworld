"""
时间线抽取服务（timeline service）

- 分块（<=2000 字符）逐块 LLM 抽取（每次至多 1 次重试），失败降级到启发式抽取器。
- 归一化（地点词典 / 时间锚 / ev_type / sort 键），写入 data/world-timeline/<pid>/timeline.json。
- 提供任务状态轮询（running/completed/partial_failed/failed）。

存储目录：
- data/world-timeline/<project_id>/timeline.json（data/ 已 gitignore）
  timeline.json = { "project_id", "source", "events": [ <TimelineEvent>... ] }
"""
import difflib
import hashlib
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
from ..utils.atomic_json import atomic_write_json
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
# 长文本走 map-reduce 分块的字符阈值：超过此值时按自然边界（空行/章节标题/时间标记）切块，
# 每个大块内再交给逐事件抽取，避免一次性把整段长文塞进单次 LLM 调用而失败/超长。
LONG_TEXT_CHUNK_CHARS = 12000
# 单块最大 LLM 调用次数（1 原始 + 1 重试）
MAX_LLM_ATTEMPTS = 2
# 单 chunk 独立抽取的额外重试次数（期望总调用 = MAX_LLM_ATTEMPTS + CHUNK_RETRIES）。
# 连续失败达到上限后，跳过该 chunk 并记录 partial（不把整个任务标记 failed）。
CHUNK_RETRIES = 2
# 线程防误拆阈值：主线程事件占比 >= 该值 且 其余线程各自事件数 <= 小线程上限 时才合并。
MAINTHREAD_DOMINANCE = 0.60
SMALL_THREAD_EVENT_MAX = 3
# 真正的平行叙事最少事件数（少于该值视为主线误拆的碎片，应并入主线）
PARALLEL_THREAD_EVENT_MIN = 4
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
        atomic_write_json(path, {"project_id": project_id, "events": events})
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
                    "canonical_name": str(it.get("canonical_name") or it.get("name") or "")[:40],
                    "aliases": _clean_aliases(it.get("aliases")),
                    "traits": str(it.get("traits") or "")[:_CHAR_TRAITS_MAX],
                    "description": str(it.get("description") or "")[:_CHAR_DESC_MAX],
                })
        return out
    except Exception as e:
        logger.warning(f"读取人物设定失败: {e}")
        return []


_CHAR_ALIASES_MAX = 20
_ALIAS_LEN_MAX = 40


def _clean_aliases(raw) -> List[str]:
    """把 aliases 规范化为去重、去空、截断的字符串列表（不含与 name 相同的项）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        # 兼容逗号/顿号分隔的字符串输入
        raw = re.split(r"[,，、;；]+", raw)
    if not isinstance(raw, list):
        return []
    seen = set()
    out = []
    for a in raw:
        s = str(a or "").strip()[:_ALIAS_LEN_MAX]
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= _CHAR_ALIASES_MAX:
            break
    return out


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
            aliases = _clean_aliases(it.get("aliases"))
            # 别名里去掉与正式名相同的项
            aliases = [a for a in aliases if a != name]
            clean.append({
                "name": name,
                "canonical_name": str(it.get("canonical_name") or name)[:40],
                "aliases": aliases,
                "traits": str(it.get("traits") or "")[:_CHAR_TRAITS_MAX],
                "description": str(it.get("description") or "")[:_CHAR_DESC_MAX],
            })
        payload = {"project_id": project_id, "characters": clean}
        atomic_write_json(path, payload)
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
        seeded.append({"name": name, "canonical_name": name, "aliases": [],
                       "traits": "", "description": ""})
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
    "confidence(0到1)、characters(人物名数组)、"
    "thread_id(可选字符串,该事件所属时间线线索id,如'乌萨斯'或'龙国'或'寓言层')、"
    "thread_name(可选字符串,线索/线程显示名,没有可省略)、"
    "dimension(可选字符串,叙事维度,默认'main';寓言/导演/高维视角等用'allegory'/'meta')、"
    "parallel_group(可选字符串,并行时间线分组名,没有可省略)。"
    "规则：只抽推动情节或事件性的内容；多国/多势力/多人物线并行时应尽量归入不同 thread_name；"
    "若文本明显是另一叙事维度（如寓言、电影、回忆嵌套、高维总结），用 dimension 区分，"
    "不要强行与主时间线排序；过长叙述拆成多个事件；保持原文简洁转述；无把握的时间锚填unspecified,year/age填null。"
)


_THREAD_SYSTEM = (
    "你是一个世界背景时间线分析师。请从给定的世界背景设定文本中，识别出并行的"
    "时间线线索（线程）。线索可以是：国家/地区历史、势力/阵营、文明、种族、"
    "人物个人线、以及不同叙事维度（如寓言层、导演层、高维总结）。"
    "仅输出一个 JSON 数组，不要多余文字。每项含字段："
    "id(字符串,短标识)、name(显示名)、dimension(默认'main';寓言/导演/高维等用'allegory'/'meta')、"
    "parallel_group(可选,并行分组名)、description(一句话说明)。"
    "最多输出 20 条；如果文本没有明显多线，可以只输出 1 条 main。"
)

_THREAD_CHUNK_CHARS = 6000
_THREAD_MAX = 20


def _normalize_thread(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一条 LLM 线索项规范化为内部 dict；非法返回 None。"""
    if not isinstance(item, dict):
        return None
    tid = str(item.get("id") or item.get("name") or "").strip()
    name = str(item.get("name") or tid or "").strip()
    if not tid and not name:
        return None
    return {
        "id": (tid or name)[:80],
        "name": name[:80],
        "dimension": str(item.get("dimension") or "main").strip()[:40] or "main",
        "parallel_group": str(item.get("parallel_group") or "").strip()[:80],
        "description": str(item.get("description") or "").strip()[:300],
    }


def _merge_thread(existing: Dict[str, Dict[str, Any]], item: Dict[str, Any]) -> None:
    """按 id 或 name 合并线索；已存在时保留更完整的 description。"""
    if not item:
        return
    key = item.get("id") or item.get("name")
    if not key:
        return
    cur = existing.get(key)
    if cur is None:
        existing[key] = item
        return
    if not cur.get("description") and item.get("description"):
        cur["description"] = item["description"]
    if not cur.get("parallel_group") and item.get("parallel_group"):
        cur["parallel_group"] = item["parallel_group"]


# 不恰当 / 占位类线程的缺陷词：合并时过滤这些“假线程”，减少误拆。
# 仅当名字“恰好等于”这些占位词（或极短且以其开头）才过滤，避免误伤含“无/未知”
# 等字眼的真实地名（如“无国界线”“未知之岛”）。
_THREAD_JUNK_WORDS = ("未知", "未命名", "无", "其他", "其它", "待定", "默认",
                      "unknown", "none", "n/a", "-")


def _thread_looks_junk(t: Dict[str, Any]) -> bool:
    """判断一条线程是否应被视为“占位/垃圾线程”而被过滤。
    - 空 id/name
    - 名字只有 1 个字符或不含任何中英文/数字（纯标点/空白）
    - 名字恰好是占位词，或 ≤2 字且以占位词开头（如“未知”“暂无”）
    """
    if not isinstance(t, dict):
        return True
    name = str(t.get("name") or t.get("id") or "").strip()
    if not name:
        return True
    if len(name) <= 1:
        return True
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", name):
        return True
    low = name.lower()
    if low in _THREAD_JUNK_WORDS:
        return True
    if len(name) <= 2:
        for w in _THREAD_JUNK_WORDS:
            if low.startswith(w) and len(w) >= 2:
                return True
    return False


def _dedupe_threads(threads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """去重 + 过滤占位线程，返回更干净的线程列表（供保存与提示词使用）。

    - 归一化 key（按 id 或 name，去空白小写）
    - 合并同 key 项（保留更完整 description）
    - 剔除 junk 线程
    - 超出上限截断
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for t in threads:
        if _thread_looks_junk(t):
            continue
        key = (t.get("id") or t.get("name") or "").strip().lower()
        if not key:
            continue
        _merge_thread(merged, t)
        if len(merged) >= _THREAD_MAX:
            break
    return list(merged.values())[:_THREAD_MAX]


def _identify_threads_chunk(llm, chunk: str, existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """对单个文本块识别线索；失败抛异常。"""
    user = f"请识别下面世界背景中的时间线线索：\n<文本>\n{chunk}\n"
    if existing:
        names = "、".join(t.get("name") or t.get("id") for t in existing[:20])
        user += f"\n已识别线索（请避免重复）：{names}\n"
    resp = llm.chat(
        messages=[
            {"role": "system", "content": _THREAD_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    arr = _extract_json_array(resp)
    if not isinstance(arr, list):
        raise ValueError("线索识别响应不是数组")
    out = []
    for item in arr:
        t = _normalize_thread(item)
        if t is not None:
            out.append(t)
        if len(out) >= _THREAD_MAX:
            break
    return out


def _identify_threads(llm, text: str) -> List[Dict[str, Any]]:
    """第一遍：识别背景文本中的时间线线索（线程）。

    对长文本做分块识别并合并，避免一次性把全部设定塞进一个 prompt 导致
    超长/失败后整段降级为普通抽取。任一分块失败只跳过该块。
    """
    if not text or not text.strip():
        return []
    chunks = chunk_text(text, _THREAD_CHUNK_CHARS)
    if not chunks:
        chunks = [text]
    merged: Dict[str, Dict[str, Any]] = {}
    for chunk in chunks:
        try:
            items = _identify_threads_chunk(llm, chunk, list(merged.values()))
            for it in items:
                _merge_thread(merged, it)
                if len(merged) >= _THREAD_MAX:
                    break
        except Exception as e:
            logger.warning(f"线索识别分块失败（跳过该块）: {e}")
        if len(merged) >= _THREAD_MAX:
            break
    return list(merged.values())[:_THREAD_MAX]


def _thread_hint_block(threads: List[Dict[str, Any]]) -> str:
    """把识别出的线索列表渲染成提示词块；空返回空串。"""
    if not threads:
        return ""
    lines = ["已知时间线线索（供归类参考）："]
    for t in threads:
        dim = t.get("dimension") or "main"
        desc = t.get("description") or ""
        lines.append(f"- {t.get('name') or t.get('id')}（{dim}）{('：' + desc) if desc else ''}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 时间线结构类型判断（抽取前“先判断类型，再按类型定制抽取策略”）
# ---------------------------------------------------------------------------
# 结构类型枚举：single=单线并行、parallel=多线并行、
#   tree=树状(分支演进)、network=网状(多线交织)、meta=元叙事/嵌套(寓言/高维/回忆嵌套)、mixed=混合复杂
STRUCTURE_TYPES = (
    "linear", "single", "parallel", "tree", "network", "meta", "mixed",
)
_STRUCTURE_LABELS = {
    "linear": "单线叙事",
    "single": "单线叙事",
    "parallel": "并行多线",
    "tree": "树状/分支演进",
    "network": "网状多线交织",
    "meta": "元叙事/嵌套",
    "mixed": "混合复杂",
}

_STRUCTURE_SYSTEM = (
    "你是一个小说时间线结构分析师。请整体判断给定文本的时间线结构类型，并输出一个 JSON 对象："
    "{\"type\": <'single'|'parallel'|'tree'|'network'|'meta'|'mixed'>, "
    "\"confidence\": <0-1 的小数>, \"reason\": <一句话理由>, "
    "\"strategy\": <简要说明应如何抽取该类型的时间线>}。"
    "类型定义：single=从头到尾一条主时间线；parallel=多条人物/势力/地区线并行走各自前后顺序；"
    "tree=由关键节点不断分支出新故事线（分叉/if线/前世今生）；network=多人多地事件相互交织、时间跳跃频繁；"
    "meta=存在寓言层/导演层/高维总结/回忆嵌套等非主叙事的叙事维度；mixed=以上多种并存、难以归为单一类型。"
    "只输出该 JSON 对象，不要多余文字。"
)


def _normalize_structure_type(raw: Any) -> str:
    """把 LLM 返回的结构类型归一化为合法枚举；非法回退 mixed。"""
    t = str(raw or "").strip().lower()
    if t in STRUCTURE_TYPES:
        return t
    # 兼容中文/别名
    for k, label in _STRUCTURE_LABELS.items():
        if label in t or k in t:
            return k
    return "mixed"


def detect_structure_type(llm, text: str) -> Optional[Dict[str, Any]]:
    """在抽取前判断文本整体时间线结构类型。

    返回 {"type","confidence","reason","strategy"}；LLM 不可用/失败返回 None
    （调用方回退为“不按类型定制，使用默认抽取策略”）。
    """
    if not text or not text.strip():
        return None
    # 控制输入规模：取前 8000 字符足够判断整体结构
    sample = text[:8000]
    try:
        resp = llm.chat(
            messages=[
                {"role": "system", "content": _STRUCTURE_SYSTEM},
                {"role": "user",
                 "content": f"请判断下面文本的时间线结构类型：\n<文本>\n{sample}\n"},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        arr = _extract_json_array(resp)
        if arr is None:
            # 兼容直接输出对象（非数组）的情况
            obj = None
            if resp.strip().startswith("{"):
                try:
                    obj = json.loads(resp.strip())
                except Exception:
                    obj = None
            if not isinstance(obj, dict):
                raise ValueError("结构判断响应不是 JSON 对象")
        else:
            # 数组里取第一条（防御：部分模型仍输出 [{type:...}]）
            obj = arr[0] if isinstance(arr, list) and arr else None
        if not isinstance(obj, dict):
            return None
        t = _normalize_structure_type(obj.get("type"))
        return {
            "type": t,
            "confidence": _float_or(obj.get("confidence"), 0.5),
            "reason": str(obj.get("reason") or "").strip()[:300],
            "strategy": str(obj.get("strategy") or "").strip()[:500],
        }
    except Exception as e:
        logger.warning(f"时间线结构类型判断失败（使用默认策略）: {e}")
        return None


# 各结构类型对应的抽取策略提示（注入到逐块抽取 prompt）
_STRUCTURE_STRATEGIES: Dict[str, str] = {
    "single": (
        "已判定为【单线叙事】：主时间线按时间推进抽取即可；不要强行拆出多线/多维度，"
        "thread_name/dimension 保持默认 main。"
    ),
    "parallel": (
        "已判定为【并行多线】：存在多条各自独立前进的故事线。请把每条线的事件归入唯一 thread_name，"
        "并为互相并行、时间上大体同步的多条线使用 parallel_group；不要把所有事件揉成一条主时间线。"
    ),
    "tree": (
        "已判定为【树状/分支演进】：由关键节点不断分支出新故事线。请为每条分支事件设置 thread_name，"
        "并给由同一母节点分出的分支相同的 parent_event_id 归属源事件；保留 branch/分支的相互关系。"
    ),
    "network": (
        "已判定为【网状多线交织】：多人多地事件相互交织、时间跳跃频繁。请为每个主要叙事线独立 thread_name，"
        "通过 linked_event_ids 标注跨线关键关联；事件较多时按线分组而不是强排全局时间线。"
    ),
    "meta": (
        "已判定为【元叙事/嵌套】：存在寓言层/导演层/高维总结/回忆嵌套等非主叙事维度。"
        "请用 dimension 区分叙事层（主叙事用 main，寓言/导演/高维用 allegory/meta）；"
        "不同维度的内容不要强行与主时间线按时间混排。"
    ),
    "mixed": (
        "已判定为【混合复杂】：多种结构并存。请以主叙事时间线为主线，并行线归入不同 thread_name 与 "
        "parallel_group，跨维度内容用 dimension 区分，彼此关联用 linked_event_ids 标注。"
    ),
}


def structure_hint_block(structure: Optional[Dict[str, Any]]) -> str:
    """把结构判断 + 对应策略渲染成提示词块；无则空串（使用默认策略）。"""
    if not structure or not structure.get("type"):
        return ""
    t = structure.get("type")
    lines = [f"时间线结构：{_STRUCTURE_LABELS.get(t, t)}（置信度 {structure.get('confidence') or '未知'}）"]
    stra = (structure.get("strategy") or "").strip()
    if stra:
        lines.append(f"结构说明：{stra}")
    guide = _STRUCTURE_STRATEGIES.get(t)
    if guide:
        lines.append(guide)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自动结构判定（deterministic，抽取后基于已落事件/线程计算，不依赖 LLM）
# ---------------------------------------------------------------------------
# 判定阈值（集中可调）
_CLASSIFY_PARALLEL_MIN = 2          # 需要至少 2 个非空线程才算 parallel
_CLASSIFY_PARALLEL_EVENTS = 4       # 每个拟判为并行的线程至少要有的事件数
_CLASSIFY_TREE_LINK_RATIO = 0.25    # parent_event_id 占比达到该值判为 tree
_CLASSIFY_NETWORK_LINK_RATIO = 0.30 # linked_event_ids 多对多密度达到该值判为 network
_CLASSIFY_META_TIMELESS_RATIO = 0.60# 无时间锚事件占比达到该值且组织松散判为 meta


def _meta_dimension_ratio(events: List[Dict[str, Any]]) -> float:
    """估算事件落在非 main 维度（寓言/高维/回忆等）的比例，用于 meta 判定。"""
    if not events:
        return 0.0
    nonmain = sum(1 for e in events
                  if str(e.get("dimension") or "main").strip() not in ("", "main"))
    return nonmain / len(events)


def _timeless_ratio(events: List[Dict[str, Any]]) -> float:
    """估算“缺乏明确时间锚”的事件占比（time_kind=unspecified 或无可推断 sort）。"""
    if not events:
        return 0.0
    timeless = 0
    for e in events:
        tk = str(e.get("time_kind") or "").strip()
        if not tk or tk == "unspecified":
            timeless += 1
    return timeless / len(events)


def _tree_ratio(events: List[Dict[str, Any]]) -> float:
    if not events:
        return 0.0
    with_parent = sum(1 for e in events if str(e.get("parent_event_id") or "").strip())
    return with_parent / len(events)


def _link_density(events: List[Dict[str, Any]]) -> float:
    """多对多跨事件链接密度：带 linked_event_ids 的事件占比 + 平均每条链接数。"""
    if not events:
        return 0.0
    linked = [e for e in events if (e.get("linked_event_ids") or [])]
    if not linked:
        return 0.0
    links = sum(len(e.get("linked_event_ids") or []) for e in events)
    return (len(linked) / len(events)) + min(1.0, links / max(1, len(events)))


def classify_structure(events: List[Dict[str, Any]],
                       threads: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """基于已抽事件/线程，确定性判结构类型（linear/parallel/tree/network/meta）。

    规则（优先级从高到低，先判特殊结构，再判并行/单线）：
    - meta   ：非 main 维度占比高 且 事件组织松散（缺时间锚比例高）；
    - tree   ：parent_event_id 占比较高，存在父->子分支层级；
    - network：linked_event_ids 高密度多对多（且 links 平均 ≥3）；
    - parallel：至少 2 个非空线程，每个足够多事件（持续支线），且整体时间有跳变/并行；
    - linear ：单线程或全部归入 main，无跨线程边，朴素先后推进。

    返回 {"type", "confidence", "reason"}；events 为空时返回 linear（置信度 0）。
    该判定是 LLM 结构判断（detect_structure_type）的确定性补充：抽取后据实计算，
    与 LLM 判断取“更高证据链”共同决定最终落盘结构（见 _finalize_structure）。
    """
    events = events or []
    if not events:
        return {"type": "linear", "confidence": 0.0, "reason": "无事件，默认线性"}

    reasons: List[str] = []

    # 线索/线程分布
    thread_counts: Dict[str, int] = {}
    for e in events:
        t = str(e.get("thread_id") or e.get("thread_name") or "main").strip() or "main"
        thread_counts[t] = thread_counts.get(t, 0) + 1
    non_main_threads = {k: v for k, v in thread_counts.items()
                        if _thread_norm_key(k) not in _MAINTHREAD_KEYS}

    # --- meta：存在明显非 main 维度 + 组织松散 ---
    if _meta_dimension_ratio(events) >= 0.30 and _timeless_ratio(events) >= _CLASSIFY_META_TIMELESS_RATIO:
        reasons.append("存在寓言/高维/回忆等非主维度且时间锚稀疏")
        return {"type": "meta", "confidence": 0.85, "reason": "；".join(reasons)}

    # --- tree：父->子分支层级 ---
    tr = _tree_ratio(events)
    if tr > 0 and tr >= _CLASSIFY_TREE_LINK_RATIO and len(events) >= 4:
        reasons.append(f"parent_event_id 层级明显（占比 {tr:.0%}）")
        return {"type": "tree", "confidence": min(0.9, 0.5 + tr), "reason": "；".join(reasons)}

    # --- network：多对多链接高密度 ---
    ld = _link_density(events)
    if ld >= _CLASSIFY_NETWORK_LINK_RATIO:
        reasons.append(f"多对多事件链接密度高（score {ld:.2f}）")
        return {"type": "network", "confidence": min(0.9, 0.45 + ld),
                "reason": "；".join(reasons)}

    # --- parallel：至少 2 个非空线程，每个足够多事件，且有并行跳变 ---
    if len(non_main_threads) >= _CLASSIFY_PARALLEL_MIN:
        sustained = [k for k, v in non_main_threads.items() if v >= _CLASSIFY_PARALLEL_EVENTS]
        if len(sustained) >= _CLASSIFY_PARALLEL_MIN:
            reasons.append(
                f"{len(sustained)} 条持续线程（各≥{_CLASSIFY_PARALLEL_EVENTS} 事件）")
            # 若存在 parallel_group 或维度区分，进一步佐证并行
            groups = set(str(e.get("parallel_group") or "").strip() for e in events)
            dims = set(str(e.get("dimension") or "main").strip() for e in events)
            conf = 0.7
            if len(groups - {""}) > 1:
                conf = min(0.9, conf + 0.1)
                reasons.append("存在并行分组")
            if len(dims - {"main"}) > 0:
                conf = min(0.9, conf + 0.1)
                reasons.append("多维度")
            return {"type": "parallel", "confidence": conf, "reason": "；".join(reasons)}

    # --- linear：单线程 / 或虽有碎片但主线主导 ---
    ratio_main = (len(events) - sum(non_main_threads.values())) / len(events)
    if len(non_main_threads) == 0 or ratio_main >= MAINTHREAD_DOMINANCE:
        conf = 0.9 if len(non_main_threads) == 0 else min(0.8, ratio_main)
        reasons.append(
            f"单主线主导（主线占比 {ratio_main:.0%}，非主线线程 {len(non_main_threads)} 条）")
        return {"type": "linear", "confidence": conf, "reason": "；".join(reasons)}

    reasons.append("多线程但证据不足，保守判为 linear")
    return {"type": "linear", "confidence": 0.55, "reason": "；".join(reasons)}


def finalize_structure(events: List[Dict[str, Any]],
                       threads: Optional[List[Dict[str, Any]]] = None,
                       llm_structure: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把抽取后据实计算的确定性判定与 LLM 预判合并，得出最终落盘结构。

    - deterministic = classify_structure(events, threads)：证据链来自真实事件；
    - llm_structure = detect_structure_type 的预判（可能缺失）。
    - 当二者不一致且 deterministic 置信度更高时，以 deterministic 为准；
      否则保留 llm 预判（LLM 能看到整体叙事上下文，可补充确定性判据漏掉的语义）。
    """
    det = classify_structure(events, threads)
    if llm_structure and isinstance(llm_structure, dict):
        llm_type = _normalize_structure_type(llm_structure.get("type"))
        llm_conf = _float_or(llm_structure.get("confidence"), 0.5)
        det_type = det.get("type")
        if det_type == llm_type:
            det["confidence"] = max(det.get("confidence", 0.0), llm_conf)
            det["reason"] = (det.get("reason") or "") + "；与 LLM 预判一致"
            det["method"] = "deterministic+llm"
            return det
        if det_type == "linear" and llm_type == "single":
            # single ↔ linear 等价命名，归一化为 linear
            det["confidence"] = max(det.get("confidence", 0.0), llm_conf)
            det["reason"] = (det.get("reason") or "") + "；LLM 预判 single（等价线性）"
            det["method"] = "deterministic+llm"
            return det
        # 与 LLM 冲突：以更高置信度为准
        if det.get("confidence", 0.0) >= llm_conf:
            det["reason"] = (det.get("reason") or "") + f"；覆盖 LLM 预判 {llm_type}"
            det["method"] = "deterministic"
            return det
        return {
            "type": llm_type,
            "confidence": llm_conf,
            "reason": (str(llm_structure.get("reason") or "") or f"LLM 预判 {llm_type}"),
            "strategy": str(llm_structure.get("strategy") or ""),
            "method": "llm",
        }
    det["method"] = "deterministic"
    return det


# ---------------------------------------------------------------------------
# 线程/时间线归一化合并
# ---------------------------------------------------------------------------
# 主线/占位名的归一化目标
_MAINTHREAD_KEYS = {"", "main", "主线", "主时间线", "全部", "all", "default", "默认"}

# 常见线程名后缀/噪音词，归一化时去掉，避免“乌萨斯主线”“乌萨斯线”“乌萨斯-线”被拆成多条。
_THREAD_SUFFIXES = (
    "时间线", "故事线", "剧情线", "叙事线", "主线", "支线", "线", "历史",
    "timeline", "thread", "storyline", "line",
)


def _thread_norm_key(label: Any) -> str:
    """把线程名/ID 归一化为稳定的比较键：小写、去空白/标点、去常见后缀。"""
    s = str(label or "").strip().lower()
    s = re.sub(r"[\s_\-—－:：,，。.、;；!！?？()（）\[\]【】/\\|]+", "", s)
    # 去掉常见后缀（保留至少 1 个字符）
    changed = True
    while changed and len(s) > 1:
        changed = False
        for suf in _THREAD_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[:-len(suf)]
                changed = True
    return s


def _thread_similarity(a: str, b: str) -> float:
    """两个归一化线程键的相似度：包含关系给高分，否则用 difflib。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 2 and len(b) >= 2 and (a in b or b in a):
        return 0.92
    return difflib.SequenceMatcher(None, a, b).ratio()


def _reconcile_threads(
    events: List[Dict[str, Any]],
    structure: Optional[Dict[str, Any]],
    threads: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把抽取事件按“真实时间线线索”归一化合并，避免同一条主线被拆成多段。

    - single（或明确无多线） → 全部归入 main；
    - 多线结构 → 把同一条线索的不同命名（“乌萨斯”/“乌萨斯主线”）合并到同一条，
      但保留真正并行的不同 thread（国家/势力/维度等）。
    """
    if not events:
        return events

    structure_type = (structure or {}).get("type") if structure else None
    if structure_type == "single":
        for e in events:
            e["thread_id"] = ""
            e["thread_name"] = ""
            e["parallel_group"] = ""
            e["dimension"] = "main"
        return events

    canon_map: Dict[str, Dict[str, Any]] = {}

    def add_canon(c: Dict[str, Any]) -> None:
        if not c:
            return
        name_key = _thread_norm_key(c.get("name") or c.get("id"))
        if name_key and name_key not in canon_map:
            canon_map[name_key] = c
        id_key = _thread_norm_key(c.get("id"))
        if id_key and id_key not in canon_map:
            canon_map[id_key] = c

    for t in threads or []:
        add_canon({
            "id": str(t.get("id") or t.get("name") or "").strip(),
            "name": str(t.get("name") or t.get("id") or "").strip(),
            "dimension": str(t.get("dimension") or "main").strip() or "main",
            "parallel_group": str(t.get("parallel_group") or "").strip(),
        })

    # 保证存在一条 main 归并目标
    if not any(k in _MAINTHREAD_KEYS or _thread_norm_key(k) in _MAINTHREAD_KEYS for k in canon_map):
        add_canon({"id": "main", "name": "main", "dimension": "main", "parallel_group": ""})

    def find_canon(norm_key: str) -> Optional[Dict[str, Any]]:
        if norm_key in canon_map:
            return canon_map[norm_key]
        best_key = None
        best_score = 0.0
        for k, c in canon_map.items():
            score = _thread_similarity(norm_key, k)
            if score > best_score:
                best_key, best_score = k, score
        if best_key and best_score >= 0.72:
            return canon_map[best_key]
        return None

    def assign(e: Dict[str, Any], c: Dict[str, Any]) -> None:
        e["thread_id"] = str(c.get("id") or "").strip()
        e["thread_name"] = str(c.get("name") or c.get("id") or "").strip()
        e["parallel_group"] = str(c.get("parallel_group") or "").strip()
        if not str(e.get("dimension") or "").strip() or e.get("dimension") == "main":
            e["dimension"] = str(c.get("dimension") or "main").strip() or "main"

    for e in events:
        label = str(e.get("thread_name") or e.get("thread_id") or "").strip()
        norm = _thread_norm_key(label)
        if norm in _MAINTHREAD_KEYS:
            c = find_canon("main") or {"id": "", "name": "", "dimension": "main", "parallel_group": ""}
            assign(e, c)
            continue
        c = find_canon(norm)
        if c is None:
            c = {
                "id": str(e.get("thread_id") or label or norm),
                "name": label or norm,
                "dimension": str(e.get("dimension") or "main").strip() or "main",
                "parallel_group": str(e.get("parallel_group") or "").strip(),
            }
            add_canon(c)
        assign(e, c)

    # 主线防误拆合并：主线程占比 ≥ 60% 且其余线程事件数 ≤ 3 时，把这些“碎片线程”
    # 并入主线，并把原线程名保留为 event 的 thread_aliases，避免把同一条主线前后段
    # 误拆成多个 thread（用户核心痛点）。仅当这些线程不是“真正平行叙事”才并。
    # 若结构已被明确判定为 parallel（或 single 已全归 main），不在此合并——保留真正的
    # 并行叙事（既有 test_multiline_merges_aliases 期望并行线被保留）。
    if structure_type not in ("parallel", "single"):
        _merge_small_threads_to_main(events)

    return events


# 判定某事件是否来自“真正平行叙事”，不足以并入主线（保留为独立线程）。
#   明确 POV 切换 / 明确并线 / 人物支线持续 ≥ PARALLEL_THREAD_EVENT_MIN 事件 才保留。
def _is_sustained_thread(events: List[Dict[str, Any]], thread_key: str,
                         min_events: int = PARALLEL_THREAD_EVENT_MIN) -> bool:
    """判断某非主线线程是否应保留为独立平行叙事（而非主线误拆的碎片）。

    - 片段事件数 >= min_events → 持续支线，保留；
    - 非 main 维度且被显式标注 dimension（寓言/高维等）→ 独立维度，保留；
    - 其余（碎片/偶发提一句）→ 可并入主线。
    """
    count = sum(1 for e in events
                if (_thread_norm_key(str(e.get("thread_id") or "")) == thread_key)
                or (_thread_norm_key(str(e.get("thread_name") or "")) == thread_key))
    if count >= min_events:
        return True
    # 维度的独立叙事（寓言/高维/回忆层）即使片段少也应保留维度语义
    for e in events:
        if _thread_norm_key(str(e.get("thread_id") or "")) == thread_key or \
           _thread_norm_key(str(e.get("thread_name") or "")) == thread_key:
            if str(e.get("dimension") or "main").strip() not in ("", "main"):
                return True
    return False


def _merge_small_threads_to_main(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把主线程主导时的小线程并入主线，返回合并审计 dict。

    规则（幂等、可审计）：
    - 统计各线程事件数，找“主线”（显式 main 优先，否则事件最多者）；
    - 若主线占比 >= MAINTHREAD_DOMINANCE 且每条非主线线程事件数 <= SMALL_THREAD_EVENT_MAX，
      且该线程不是持续平行叙事（_is_sustained_thread 为 False）→ 并入主线；
    - 合并时保留原 thread_id/thread_name 到 event['thread_aliases']（审计轨迹）；
      event 的 thread_id/thread_name 重置为主线，parallel_group 清空，dimension 归一为 main。
    返回 {"merged": {tid: name}, "ratio": float, "count": int}，供任务日志/落盘。
    """
    if not events:
        return {"merged": {}, "ratio": 1.0, "count": 0}
    meta: Dict[str, Any] = {"merged": {}, "ratio": 1.0, "count": 0}

    # 统计线程分布（按归一化 key）
    counts: Dict[str, int] = {}
    for e in events:
        t = str(e.get("thread_id") or e.get("thread_name") or "").strip() or "main"
        counts[t] = counts.get(t, 0) + 1
    if len(counts) <= 1:
        return meta

    # 主线 = 显式 main 键，否则事件最多者
    main_key = None
    for k in counts:
        if _thread_norm_key(k) in _MAINTHREAD_KEYS:
            main_key = k
            break
    if main_key is None:
        main_key = max(counts, key=counts.get)

    main_count = counts[main_key]
    ratio = main_count / len(events)
    meta["ratio"] = ratio
    meta["main"] = main_key

    others = {k: v for k, v in counts.items() if k != main_key}
    if ratio < MAINTHREAD_DOMINANCE:
        return meta

    merged_threads: Dict[str, str] = {}
    for tkey, tcount in others.items():
        if tcount > SMALL_THREAD_EVENT_MAX:
            continue  # 不小，保留为候选平行线
        # 排除被判定为真正平行叙事的线程（持续支线/独立维度）
        if _is_sustained_thread(events, _thread_norm_key(tkey)):
            continue
        merged_threads[tkey] = tkey
        # 实际执行合并（幂等：已合并的事件 thread 已是主线则跳过）
        for e in events:
            cur = str(e.get("thread_id") or e.get("thread_name") or "").strip() or "main"
            cur_name = str(e.get("thread_name") or e.get("thread_id") or "").strip()
            if cur == tkey or _thread_norm_key(cur) == _thread_norm_key(tkey):
                aliases = e.setdefault("thread_aliases", [])
                # 审计轨迹：优先记录显示名（thread_name），其次用 thread_id；
                # 同时保留 raw thread_id 便于溯源
                alias_label = cur_name or cur
                if alias_label not in aliases:
                    aliases.append(alias_label)
                if cur and cur != alias_label and cur not in aliases:
                    aliases.append(cur)
                e["thread_id"] = main_key if _thread_norm_key(main_key) not in _MAINTHREAD_KEYS else ""
                e["thread_name"] = "" if _thread_norm_key(main_key) in _MAINTHREAD_KEYS else main_key
                e["parallel_group"] = ""
                if str(e.get("dimension") or "main").strip() in ("", "main"):
                    e["dimension"] = "main"

    meta["merged"] = merged_threads
    meta["count"] = len(merged_threads)
    return meta


# 结构类型持久化（随 threads.json 一起存 timeline metadata，供结构视图前端使用）
def _structure_path(project_id: str) -> str:
    return os.path.join(TIMELINE_ROOT, validate_project_id(project_id), "structure.json")


def save_structure(project_id: str, structure: Optional[Dict[str, Any]]) -> bool:
    try:
        path = _structure_path(project_id)
        if structure is None:
            if os.path.exists(path):
                os.remove(path)
            return True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, {
            "project_id": project_id,
            "type": structure.get("type"),
            "confidence": structure.get("confidence"),
            "reason": structure.get("reason", ""),
            "strategy": structure.get("strategy", ""),
            "method": structure.get("method", ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        return True
    except Exception as e:
        logger.warning(f"保存时间线结构类型失败: {e}")
        return False


def load_structure(project_id: str) -> Optional[Dict[str, Any]]:
    try:
        path = _structure_path(project_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _threads_path(project_id: str) -> str:
    return os.path.join(TIMELINE_ROOT, validate_project_id(project_id), "threads.json")


def save_threads(project_id: str, threads: List[Dict[str, Any]]) -> bool:
    """保存背景时间线线索清单。失败仅告警。"""
    try:
        path = _threads_path(project_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, {"project_id": project_id, "threads": threads})
        return True
    except Exception as e:
        logger.warning(f"写入时间线线索失败: {e}")
        return False


def load_threads(project_id: str) -> List[Dict[str, Any]]:
    """读取背景时间线线索清单；不存在/失败返回 []。"""
    try:
        path = _threads_path(project_id)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("threads") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [dict(t) for t in items if isinstance(t, dict) and (t.get("id") or t.get("name"))]
    except Exception as e:
        logger.warning(f"读取时间线线索失败: {e}")
        return []


def _llm_extract_chunk(llm, chunk: str, thread_hint: str = "", structure_hint: str = "") -> List[Dict[str, Any]]:
    """调用一次 LLM 抽取该块，返回原始事件列表；失败抛异常。"""
    user_msg = f"请抽取下面文本段的时间线事件，输出 JSON 数组：\n<文本段>\n{chunk}\n"
    parts = []
    if structure_hint:
        parts.append(structure_hint)
    if thread_hint:
        parts.append(thread_hint)
    if parts:
        user_msg += "\n" + "\n".join(parts) + "\n"
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
        "thread_id": str(raw.get("thread_id") or "").strip()[:80],
        "thread_name": str(raw.get("thread_name") or "").strip()[:80],
        "dimension": str(raw.get("dimension") or "main").strip()[:40] or "main",
        "parallel_group": str(raw.get("parallel_group") or "").strip()[:80],
        "parent_event_id": str(raw.get("parent_event_id") or "").strip()[:80],
        "linked_event_ids": _str_list(raw.get("linked_event_ids"))[:_CHAR_ALIASES_MAX],
        "structure_type": str(raw.get("structure_type") or "linear").strip()[:40] or "linear",
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


# 长文本 map-reduce：自然的章节/时间标记边界。用于把超长文本切成“有语义边界”的大块，
# 避免在一个 chunk 中间硬切导致跨块事件被腰斩。匹配：年份/纪年、章节标题、分区标题。
_LONG_BOUNDARY_RE = re.compile(
    r'^(?:第[一二三四五六七八九十百千万0-9]+[章节卷回部分篇集]'
    r'|(?:\d{2,4}年|\d+[-/]\d+|泰历[\d]+|[\d]{2,4}\s*(?:年|纪元)|\d+-\d+年)'
    r'|[-—–]{3,}|[=*]{3,}|\bCHAPTER\b|\bChapter\b|\bPART\b)',
    re.MULTILINE,
)


def split_long_blocks(text: str, max_chars: int = LONG_TEXT_CHUNK_CHARS) -> List[str]:
    """把超长文本按自然边界（章节标题/时间标记/空行分隔段）切成 blocks。

    与 chunk_text 的区别：chunk_text 面向“每条事件抽取单元”做精细断句（<=2000）；
    本函数面向“map-reduce 的分块”——尽量在语义边界处切，避免在事件中间腰斩。
    若文本不超长则返回单块整篇（不做切分语义损失）。
    """
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    # 先按章节标题/时间标记/分隔线把文本切成“自然段”。
    marker_positions = []
    for m in _LONG_BOUNDARY_RE.finditer(text):
        # 找到该行行首
        line_start = text.rfind("\n", 0, m.start()) + 1
        marker_positions.append(line_start)
    marker_positions = sorted(set(marker_positions))

    if not marker_positions:
        # 无自然边界：退化用空行分段，仍无则按 max 硬切
        para_positions = []
        prev = 0
        for m in re.finditer(r'\n\s*\n', text):
            para_positions.append(m.end())
        breaks = [p for p in para_positions if p < len(text)]
        if not breaks:
            return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
        breaks = sorted(set(breaks + [len(text)]))
        blocks = []
        start = 0
        for b in breaks:
            if b - start >= max_chars:
                blocks.append(text[start:b].strip())
                start = b
        if start < len(text) and text[start:].strip():
            blocks.append(text[start:].strip())
        return [b for b in blocks if b]

    breaks = [p for p in marker_positions if p < len(text)]
    breaks = sorted(set(breaks + [len(text)]))
    blocks = []
    start = 0
    for b in breaks:
        # 只在与前一段累计超过上限处打断，避免过多细碎块
        if b - start >= max_chars:
            blocks.append(text[start:b].strip())
            start = b
    if start < len(text) and text[start:].strip():
        blocks.append(text[start:].strip())
    return [b for b in blocks if b]


def chunk_text_for_extract(text: str) -> List[str]:
    """抽取用分块入口：长文本（> LONG_TEXT_CHUNK_CHARS）走 map-reduce 语义分块，
    否则用既有的逐事件 chunk_text。返回块列表（顺序化，hash 稳定）。
    """
    if not text or not text.strip():
        return []
    if len(text) > LONG_TEXT_CHUNK_CHARS:
        blocks = split_long_blocks(text)
        # 每个大块内部再按逐事件上限切成小 chunk，保持逐块 LLM 抽取粒度稳定
        out: List[str] = []
        for b in blocks:
            out.extend(chunk_text(b))
        return out
    return chunk_text(text)


def _cross_chunk_merge(events: List[Dict[str, Any]],
                       threads: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """map-reduce 的跨块合并：把分块各自抽取的事件，按“同人物+连续时间+同主线”
    归并成稳定的事件/线程，避免相同事件在块边界被重复抽取或主线被切散。

    具体策略（确定性、幂等）：
    - 事件级去重：复用 _dedupe_key 的近义判定会把跨块重复的相同 summary 去重；
    - 线程级归并：同实体/同场景 + 时间上连续跳变 → 归一为同一线程
      （用 _reconcile_threads 的 canonical 能力做别名合并）。
    - 归一化 sort：按时间锚排序供下游复用。
    """
    if not events:
        return events
    # 先做一次跨块事件近似去重（按 summary + 人物 + 线程的相似度）
    deduped: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    for e in events:
        key = _dedupe_key(e)
        if key in seen:
            # 同 key 已存在：保留置信度更高的
            existing = seen[key]
            if _float_or(e.get("confidence"), 0.0) > _float_or(existing.get("confidence"), 0.0):
                deduped[deduped.index(existing)] = e
                seen[key] = e
            continue
        seen[key] = e
        deduped.append(e)
    # 线程别名归一（依赖 _reconcile_threads 的 canonical 合并能力；structure=None 走通用路径）
    try:
        _reconcile_threads(deduped, None, threads)
    except Exception:
        pass
    deduped.sort(key=lambda e: (e.get("sort_lower") or 0))
    return deduped
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

# 时间线写锁：防止同一项目上「读→改→写」的并发操作互相覆盖丢事件。
# 锁粒度到项目（RLock），LLM 调用期间不持锁，只在最终读改写临界区持锁。
_timeline_locks_guard = threading.Lock()
_timeline_locks: Dict[str, threading.RLock] = {}


def _timeline_lock_for(project_id: str) -> threading.RLock:
    with _timeline_locks_guard:
        return _timeline_locks.setdefault(project_id, threading.RLock())

_TASKS_DIR = os.path.join(TIMELINE_ROOT, "tasks")


def _task_file_path(task_id: str) -> str:
    return os.path.join(_TASKS_DIR, f"{task_id}.json")


def _persist_task(task_id: str) -> None:
    """在带锁取副本、锁外原子写文件。写失败仅警告（不阻断任务主流程）。"""
    if not task_id:
        return
    with _task_lock:
        if task_id not in _tasks:
            return
        snap = _tasks[task_id]
    try:
        os.makedirs(_TASKS_DIR, exist_ok=True)
        atomic_write_json(_task_file_path(task_id), snap)
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


def prune_old_task_files(retention_days: Optional[int] = None) -> int:
    """清理过旧的时间线任务状态文件，防止 data/world-timeline/tasks 无限增长。

    - 默认保留天数从环境变量 TIMELINE_TASK_RETENTION_DAYS 读取（默认 90）；
    - 只删除 status 非 running 且文件 mtime 超过保留天数的任务文件；
    - running 任务文件永远保留（可能正在执行）；
    - 返回删除数量。任何单个文件异常只告警跳过。
    """
    if retention_days is None:
        try:
            retention_days = int(os.environ.get("TIMELINE_TASK_RETENTION_DAYS", "90"))
        except (TypeError, ValueError):
            retention_days = 90
    retention_days = max(1, retention_days)
    if not os.path.isdir(_TASKS_DIR):
        return 0
    cutoff = time.time() - retention_days * 24 * 3600
    removed = 0
    for fn in os.listdir(_TASKS_DIR):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(_TASKS_DIR, fn)
        try:
            st = os.stat(path)
            if st.st_mtime > cutoff:
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("status") == "running":
                continue
            os.remove(path)
            removed += 1
        except Exception as e:
            logger.warning(f"清理旧任务文件失败（跳过）: {path}, {e}")
    if removed:
        logger.info(f"已清理 {removed} 个超过 {retention_days} 天的旧任务状态文件")
    return removed


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
# 抽取断点进度持久化
# ---------------------------------------------------------------------------
def _extract_progress_path(project_id: str, source: str) -> str:
    """抽取断点文件：data/world-timeline/<pid>/extract-progress-<source>.json"""
    return os.path.join(
        TIMELINE_ROOT,
        validate_project_id(project_id),
        f"extract-progress-{source}.json",
    )


def has_resumable_progress(project_id: str, source: str) -> bool:
    """是否存在可供续传的断点：progress 文件存在且有任一"已完成"条目。

    "已完成"判定：entry.status == "ok"（成功抽取）或 entry.events 非空。
    用于 start_extract 在未显式传 resume/force 时自动判断是否续传（页面刷新/重启后不丢进度）。
    """
    entries = _load_extract_progress(project_id, source)
    for entry in entries:
        if str(entry.get("status") or "").strip() in ("ok", "done", "completed"):
            return True
        if entry.get("events"):
            return True
    return False


def _load_extract_progress(project_id: str, source: str) -> List[Dict[str, Any]]:
    """读取抽取断点；不存在/损坏返回 []。"""
    try:
        path = _extract_progress_path(project_id, source)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        chunks = data.get("chunks") if isinstance(data, dict) else data
        if not isinstance(chunks, list):
            return []
        out = []
        for item in chunks:
            if isinstance(item, dict) and isinstance(item.get("events"), list):
                out.append(item)
        return out
    except Exception as e:
        logger.warning(f"读取时间线抽取进度失败（忽略）: {e}")
        return []


def _save_extract_progress(
    project_id: str, source: str, entries: List[Dict[str, Any]]
) -> bool:
    """原子写抽取断点。失败仅告警，不影响抽取主流程。"""
    try:
        path = _extract_progress_path(project_id, source)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, {
            "project_id": project_id,
            "source": source,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "chunks": entries,
        })
        return True
    except Exception as e:
        logger.warning(f"保存时间线抽取进度失败（忽略）: {e}")
        return False


def _chunk_hash(chunk: str) -> str:
    """chunk 文本的 sha1，用于断点续跑时判断文本是否变化。"""
    return hashlib.sha1((chunk or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 抽取主流程（后台任务体）
# ---------------------------------------------------------------------------
def _extract_task_body(project_id: str, source: str, task_id: str, resume: bool = False) -> None:
    from ..models.task import TaskStatus
    llm_ok_count = 0
    heuristic_count = 0
    skipped_chunks = 0
    # 本 run 内是否至少有一个 chunk 的 LLM 抽取成功（用于区分“网关整体可用但某块异常” vs “网关整体宕机”）
    llm_any_ok = False
    all_events: List[Dict[str, Any]] = []
    threads: List[Dict[str, Any]] = []
    structure: Optional[Dict[str, Any]] = None

    # 局部 _update：刷新 elapsed 的便捷封装
    def _update(**kw):
        _update_task(task_id, **kw)

    try:
        # 读源文本
        if source == "story":
            text = _source_text(project_id, story=True)
        else:
            text = _source_text(project_id, story=False)

        chunks = chunk_text_for_extract(text)
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

        # 第一遍：背景文本先识别时间线线索（线程），供逐块抽取归类。
        # resume=True 时优先复用已保存的 threads 缓存，跳过重复 LLM 识别；
        # 仅当尚未保存过（首跑/上次没存上）才走 LLM 识别。
        thread_hint = ""
        if source == "bg" and llm is not None:
            if resume:
                saved_threads = load_threads(project_id)
                if saved_threads:
                    threads = saved_threads
                    thread_hint = _thread_hint_block(threads)
                    _task_log(task_id, f"断点复用已保存线索 {len(threads)} 条（跳过 LLM 识别）")
                else:
                    try:
                        _task_log(task_id, "识别背景时间线线索（第一遍续跑）...")
                        _update(stage="识别线索", progress=2)
                        threads = _identify_threads(llm, text)
                        if threads:
                            threads = _dedupe_threads(threads)
                            save_threads(project_id, threads)
                            thread_hint = _thread_hint_block(threads)
                            _task_log(task_id, f"识别到 {len(threads)} 条时间线线索")
                        else:
                            _task_log(task_id, "未识别到独立线索，按单线抽取")
                    except Exception as e:
                        logger.warning(f"[{task_id}] 背景线索识别失败，继续普通抽取: {e}")
                        _task_log(task_id, "线索识别失败，继续普通抽取")
            else:
                try:
                    _task_log(task_id, "识别背景时间线线索（第一遍）...")
                    _update(stage="识别线索", progress=2)
                    threads = _identify_threads(llm, text)
                    if threads:
                        threads = _dedupe_threads(threads)
                        save_threads(project_id, threads)
                        thread_hint = _thread_hint_block(threads)
                        _task_log(task_id, f"识别到 {len(threads)} 条时间线线索")
                    else:
                        _task_log(task_id, "未识别到独立线索，按单线抽取")
                except Exception as e:
                    logger.warning(f"[{task_id}] 背景线索识别失败，继续普通抽取: {e}")
                    _task_log(task_id, "线索识别失败，继续普通抽取")

        # 结构类型判断：抽取前先判断整体是单线/并行/树状/网状/元叙事/混合，
        # 再按类型注入抽取策略（复杂多线/嵌套时提示词更聚焦，减少不当线程与乱排）。
        # resume=True 时复用已保存的 structure 缓存，跳过重复 LLM 识别。
        structure_hint = ""
        if llm is not None:
            if resume:
                saved_structure = load_structure(project_id)
                if saved_structure and saved_structure.get("type"):
                    structure = saved_structure
                    structure_hint = structure_hint_block(structure)
                    _task_log(
                        task_id,
                        f"断点复用已保存结构：{_STRUCTURE_LABELS.get(structure.get('type'), structure.get('type'))}"
                        f"（跳过 LLM 识别）",
                    )
                else:
                    try:
                        _task_log(task_id, "判断时间线结构类型（续跑）...")
                        _update(stage="判断结构", progress=1)
                        structure = detect_structure_type(llm, text)
                        if structure:
                            save_structure(project_id, structure)
                            structure_hint = structure_hint_block(structure)
                            _task_log(
                                task_id,
                                f"时间线结构：{_STRUCTURE_LABELS.get(structure.get('type'), structure.get('type'))}"
                                f"（置信度 {structure.get('confidence') or '未知'}）",
                            )
                        else:
                            _task_log(task_id, "结构判断不可用，使用默认抽取策略")
                    except Exception as e:
                        logger.warning(f"[{task_id}] 结构判断失败，使用默认策略: {e}")
                        _task_log(task_id, "结构判断失败，使用默认策略")
            else:
                try:
                    _task_log(task_id, "判断时间线结构类型...")
                    _update(stage="判断结构", progress=1)
                    structure = detect_structure_type(llm, text)
                    if structure:
                        save_structure(project_id, structure)
                        structure_hint = structure_hint_block(structure)
                        _task_log(
                            task_id,
                            f"时间线结构：{_STRUCTURE_LABELS.get(structure.get('type'), structure.get('type'))}"
                            f"（置信度 {structure.get('confidence') or '未知'}）",
                        )
                    else:
                        _task_log(task_id, "结构判断不可用，使用默认抽取策略")
                except Exception as e:
                    logger.warning(f"[{task_id}] 结构判断失败，使用默认策略: {e}")
                    _task_log(task_id, "结构判断失败，使用默认策略")

        # ---------- 断点续跑 ----------
        progress_by_index: Dict[int, Dict[str, Any]] = {}
        if resume:
            for entry in _load_extract_progress(project_id, source):
                try:
                    idx = int(entry.get("index", -1))
                except (TypeError, ValueError):
                    continue
                if idx >= 0:
                    progress_by_index[idx] = entry
            matched = sum(
                1 for idx, entry in progress_by_index.items()
                if 0 <= idx < total
                and entry.get("hash") == _chunk_hash(chunks[idx])
                and entry.get("events")
            )
            if matched:
                _task_log(task_id, f"断点续跑：跳过 {matched} 个已完成块")

        # 先装载已完成的块，避免后续重跑
        for idx, entry in progress_by_index.items():
            if 0 <= idx < total and entry.get("hash") == _chunk_hash(chunks[idx]) and entry.get("events"):
                saved = list(entry.get("events") or [])
                if saved:
                    all_events.extend(saved)
                    used = str(entry.get("method") or "llm")
                    if used == "llm":
                        llm_ok_count += 1
                    else:
                        heuristic_count += 1
        if resume and all_events:
            _task_log(task_id, f"已从断点恢复 {len(all_events)} 个事件")

        seq = len(all_events)
        for i, chunk in enumerate(chunks):
            h = _chunk_hash(chunk)
            entry = progress_by_index.get(i)
            if resume and entry and entry.get("hash") == h and entry.get("events"):
                # 已完成块：事件已在上面的装载阶段加入，这里只推进进度
                used = str(entry.get("method") or "llm")
                pct = round((i + 1) / total * 100) if total else 0
                _update(done_chunks=i + 1, llm_ok=llm_ok_count, heuristic=heuristic_count,
                        progress=pct,
                        message=f"已处理 {i + 1}/{total} 块（断点跳过）",
                        stage=f"正在抽取 {i + 1}/{total} 块（{used}）")
                continue

            used = "heuristic"
            events = None
            chunk_error = ""
            if llm is not None:
                _task_log(task_id, f"第 {i + 1}/{total} 块开始 LLM 抽取")
                # 重试策略：MAX_LLM_ATTEMPTS 次原始尝试 + CHUNK_RETRIES 次补偿重试。
                # 若本 run 已成功过至少一个 chunk（说明网关可用、是这块异常），连续失败
                # 就把该 chunk 跳过并记 partial；若连一个 chunk 都没成功过（疑似网关宕机），
                # 则回退启发式兜底，避免整条时间线出现空洞（兼容既有 fallback 语义）。
                attempts = MAX_LLM_ATTEMPTS + CHUNK_RETRIES
                for attempt in range(attempts):
                    try:
                        events = _llm_extract_chunk(llm, chunk, thread_hint, structure_hint)
                        if events:
                            used = "llm"
                            llm_any_ok = True
                        break
                    except Exception as e:
                        chunk_error = str(e)[:200]
                        if attempt < attempts - 1:
                            logger.warning(f"[{task_id}] chunk {i} LLM 失败，重试 {attempt + 1}: {e}")
                            _task_log(task_id, f"第 {i + 1} 块 LLM 失败，重试（{attempt + 1}/{attempts}）")
                if events is None and chunk_error and llm_any_ok:
                    # 网关可用但该块连续失败：跳过并记录 partial，不把整个任务标记失败
                    skipped_chunks += 1
                    logger.warning(f"[{task_id}] chunk {i} 多次失败，跳过并记 partial: {chunk_error}")
                    _task_log(task_id, f"第 {i + 1} 块连续失败（{attempts} 次），跳过该块（partial）")
                    progress_by_index[i] = {
                        "index": i,
                        "hash": h,
                        "method": "llm",
                        "status": "skipped",
                        "error": chunk_error,
                        "events": [],
                    }
                    _save_extract_progress(
                        project_id,
                        source,
                        [progress_by_index[k] for k in sorted(progress_by_index) if k >= 0],
                    )
                    pct = round((i + 1) / total * 100) if total else 0
                    _update(done_chunks=i + 1, llm_ok=llm_ok_count, heuristic=heuristic_count,
                            progress=pct, skipped=skipped_chunks,
                            message=f"已处理 {i + 1}/{total} 块（跳过失败块）",
                            stage=f"第 {i + 1} 块失败已跳过（partial）")
                    continue
            if events is None:
                # 网关整体不可用（llm None）或疑似宕机（无任何 LLM 成功）→ 启发式兜底
                events = _heuristic_extract_chunk(chunk, i, source)
                used = "heuristic"

            normalized_events: List[Dict[str, Any]] = []
            if events:
                for raw in events:
                    ev = _normalize_event(raw, project_id, source, i, used, seq)
                    normalized_events.append(ev)
                    all_events.append(ev)
                    seq += 1

            progress_by_index[i] = {
                "index": i,
                "hash": h,
                "method": used,
                "status": "ok" if events else "skipped",
                "error": "",
                "events": normalized_events,
            }
            # 每块完成后立即落盘断点，失败后也可从已成功块续跑
            _save_extract_progress(
                project_id,
                source,
                [progress_by_index[k] for k in sorted(progress_by_index) if k >= 0],
            )

            if used == "llm":
                llm_ok_count += 1
            else:
                heuristic_count += 1
            pct = round((i + 1) / total * 100) if total else 0
            _update(done_chunks=i + 1, llm_ok=llm_ok_count, heuristic=heuristic_count,
                    progress=pct,
                    message=f"已处理 {i + 1}/{total} 块",
                    stage=f"正在抽取 {i + 1}/{total} 块（{'LLM' if used == 'llm' else '启发式'}）")

        # 线程/时间线合并：修复同一主时间线前后段被拆成不同线程的问题。
        # _reconcile_threads 内部会做 canon 归一 + 主线防误拆合并（parallel 结构下不并）。
        _task_log(task_id, "合并同名/同主线时间线分段...")
        _reconcile_threads(all_events, structure, threads)
        merged_events = sum(1 for e in all_events if (e.get("thread_aliases") or []))
        if merged_events:
            _task_log(task_id, f"已并入主线 {merged_events} 条事件（原线程名记入 thread_aliases）")

        # 自动结构判定：抽取后据实计算，与 LLM 预判合并后落盘（供结构视图 deterministc 展示）
        final_structure = finalize_structure(all_events, threads, structure)
        save_structure(project_id, final_structure)
        _task_log(
            task_id,
            f"时间线结构判定：{_STRUCTURE_LABELS.get(final_structure.get('type'), final_structure.get('type'))}"
            f"（method={final_structure.get('method')}, 置信度 {final_structure.get('confidence') or 0:.0f}）",
        )

        # 跨块/跨线程合并（map-reduce 后的事件近似去重 + 别名归一）
        all_events = _cross_chunk_merge(all_events, threads)
        # 再次按结构定制（cross-chunk 可能引入新线程名）
        _reconcile_threads(all_events, structure, threads)

        # 排序 + 合并去重 + 写库（项目级锁内重读最新时间线，避免与并行任务互相覆盖）
        _task_log(task_id, "归一化并排序事件")
        _update(stage="写入时间线", progress=98)
        all_events.sort(key=lambda e: (e.get("sort_lower") or 0))
        with _timeline_lock_for(project_id):
            existing = load_timeline(project_id, None).get("events", [])
            existing_merged = _merge_events(existing, all_events)
            _save_timeline(project_id, existing_merged)

        if total == 0:
            _task_log(task_id, "源文本为空，未抽取到事件")
            _update(status="completed", done_chunks=0, llm_ok=0, heuristic=0, progress=100,
                    stage="完成", message="源文本为空，未抽取到事件")
        elif skipped_chunks > 0:
            _task_log(
                task_id,
                f"完成（partial）：{skipped_chunks} 块失败已跳过，"
                f"{llm_ok_count} 块 LLM、{heuristic_count} 块启发式（共 {len(all_events)} 事件）",
            )
            _update(status="partial_failed", progress=100, stage="完成（部分跳过）",
                    skipped=skipped_chunks,
                    message=f"完成，{skipped_chunks} 块失败已跳过，其余正常抽取")
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
    return (f"{e.get('source')}|{e.get('summary')}|{e.get('location_name')}|"
            f"{e.get('thread_id') or ''}|{e.get('dimension') or 'main'}")


def _source_text(project_id: str, story: bool) -> str:
    from .world_bible import WorldBibleService
    bible = WorldBibleService.get_bible(project_id)
    if bible is None:
        return ""
    return bible.story_text if story else bible.background_text


# ---------------------------------------------------------------------------
# 对外启动接口
# ---------------------------------------------------------------------------
def start_extract(project_id: str, source: str, resume: Optional[bool] = None,
                  force: bool = False) -> str:
    """校验 project_id/source，创建后台任务并返回 task_id。

    语义（三态 resume：None=未指定 | True=强制续传 | False=强制全新）：
    - force=True        : 强制全新抽取，忽略已有断点。
    - resume=True       : 强制续传，读取 extract-progress-<source>.json，跳过已完成且
                          源文本 hash 未变的 chunk，从失败/未处理处续跑。
    - resume=False      : 强制全新抽取（显式不发 resume，供"重抽"语义）。
    - resume=None(未传)  : 自动续传 —— 若存在已有断点且有已完成条目则续传，
                          否则全新抽取（页面刷新/重启后不发 resume 也能自动续上，不丢进度）。
    """
    validate_project_id(project_id)
    if source not in ("story", "bg"):
        raise ValueError("source 必须是 story 或 bg")

    # 解析最终是否续传：force 优先全新建；resume 三态；None → 自动检测。
    if force:
        eff_resume = False
    elif resume is True:
        eff_resume = True
    elif resume is False:
        eff_resume = False
    else:  # resume is None → 自动检测
        eff_resume = has_resumable_progress(project_id, source)
        if eff_resume:
            logger.info(
                f"[{project_id}/{source}] 检测到已有断点，自动续传（未显式传 resume）")

    task_id = _new_task("tl_task", "任务已创建")
    threading.Thread(target=_extract_task_body,
                     args=(project_id, source, task_id, eff_resume),
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
        with _timeline_lock_for(project_id):
            latest = load_timeline(project_id, None).get("events", [])
            merged = _merge_events(latest, new_events)
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
        with _timeline_lock_for(project_id):
            latest = load_timeline(project_id, None).get("events", [])
            merged = _merge_events(latest, all_new)
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
        with _timeline_lock_for(project_id):
            latest = load_timeline(project_id, None).get("events", [])
            merged = _merge_events(latest, new_events)
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
    with _timeline_lock_for(project_id):
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
    with _timeline_lock_for(project_id):
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
                elif k == "linked_event_ids":
                    target[k] = _str_list(v)[:_CHAR_ALIASES_MAX]
                elif k == "parent_event_id":
                    target[k] = str(v)[:80] if v else ""
                elif k == "structure_type":
                    target[k] = str(v)[:40] or "linear"
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
    with _timeline_lock_for(project_id):
        data = load_timeline(project_id, None)
        events = data.get("events", [])
        before = len(events)
        events = [e for e in events if e.get("id") != event_id]
        if len(events) == before:
            return False
        events.sort(key=lambda e: e.get("sort_lower") or 0)
        _save_timeline(project_id, events)
        return True


def _apply_event_patch(target: Dict[str, Any], patch: Dict[str, Any]) -> None:
    """把 patch 中的白名单字段应用到单个事件（不持久化）。"""
    for k, v in (patch or {}).items():
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
        elif k == "linked_event_ids":
            target[k] = _str_list(v)[:_CHAR_ALIASES_MAX]
        elif k == "parent_event_id":
            target[k] = str(v)[:80] if v else ""
        elif k == "structure_type":
            target[k] = str(v)[:40] or "linear"
        elif k == "confidence":
            target[k] = _float_or(v, 0.5)


def batch_events(project_id: str, action: str, event_ids: List[str],
                 patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """批量操作时间线事件。

    action:
      - "delete": 删除 event_ids 对应事件（不级联删除分支事件）
      - "update": 用 patch 更新 event_ids 对应事件（白名单字段）
      - "move": 把 event_ids 事件整体移动到 sort_lower 之后（相对重排）

    返回 {"action", "deleted", "updated": [事件...]}。
    """
    action = str(action or "").strip()
    if action not in ("delete", "update", "move"):
        raise ValueError("action 必须是 delete/update/move")
    ids = [str(x).strip() for x in (event_ids or []) if str(x).strip()]
    if not ids:
        raise ValueError("event_ids 不能为空")
    if action == "update" and (not isinstance(patch, dict) or not patch):
        raise ValueError("update 操作需要 patch 对象")
    if action == "move":
        raise ValueError("move 暂未开放，请使用 update 的 sort_lower 批量重排")

    with _timeline_lock_for(project_id):
        data = load_timeline(project_id, None)
        events = data.get("events", [])
        id_set = set(ids)
        if action == "delete":
            before = len(events)
            events = [e for e in events if e.get("id") not in id_set]
            removed = before - len(events)
            if removed:
                events.sort(key=lambda e: e.get("sort_lower") or 0)
                _save_timeline(project_id, events)
            return {"action": action, "deleted": removed, "updated": []}
        # action == "update"
        updated = []
        for e in events:
            if e.get("id") in id_set:
                _apply_event_patch(e, patch)
                e["updated_at"] = datetime.now().isoformat(timespec="seconds")
                updated.append(dict(e))
        if updated:
            events.sort(key=lambda e: e.get("sort_lower") or 0)
            _save_timeline(project_id, events)
        return {"action": action, "deleted": 0, "updated": updated}


def merge_events(project_id: str, target_id: str, source_ids: List[str]) -> Optional[Dict[str, Any]]:
    """项目级锁内合并事件，避免与并行抽取/推演写互相覆盖。"""
    with _timeline_lock_for(project_id):
        return _merge_events_impl(project_id, target_id, source_ids)


def _merge_events_impl(project_id: str, target_id: str, source_ids: List[str]) -> Optional[Dict[str, Any]]:
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
