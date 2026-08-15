"""
时间线归一化（timeline normalizer）

把 LLM 或启发式抽取出的原始事件字段归一化为可排序/可聚合的统一形态：
- 地点归一词典（中英别名 → 规范名 + kind）
- 事件类型枚举
- 排序键（sort_lower/sort_upper）计算
- 年龄/绝对纪年/阶段等时间锚解析

独立于存储与抽取，便于单测。
"""
import re

# ---------------------------------------------------------------------------
# 地点归一词典：别名(用 | 分隔) → (规范名, kind)
# 长别名优先匹配（罗德岛本舰 → 罗德岛）。
# ---------------------------------------------------------------------------
PLACE_DICT = {
    "泰拉|TERRA|大地": ("泰拉", "continent"),
    "维多利亚|VICTORIA": ("维多利亚", "nation"),
    "乌萨斯|URSUS": ("乌萨斯", "nation"),
    "莱塔尼亚|LEITHANIEN": ("莱塔尼亚", "nation"),
    "拉特兰|LATERANO": ("拉特兰", "nation"),
    "大炎|YAN|炎国": ("大炎", "nation"),
    "伊比利亚|IBERIA": ("伊比利亚", "nation"),
    "卡兹戴尔|KAZDEL": ("卡兹戴尔", "nation"),
    "玻利瓦尔|BOLIVAR": ("玻利瓦尔", "nation"),
    "卡西米尔|KAZIMIERZ": ("卡西米尔", "nation"),
    "萨尔贡|SARGON": ("萨尔贡", "nation"),
    "龙门|LUNGMEN": ("龙门", "city"),
    "萨米|SAMI": ("萨米", "nation"),
    "切尔诺伯格|CHERNOBOG": ("切尔诺伯格", "city"),
    "圣骏堡": ("圣骏堡", "city"),
    "东国|极东|HIGASHI": ("东国", "nation"),
    "罗德岛|本舰|罗德岛本舰|罗德岛制药": ("罗德岛", "facility"),
    "塔尔萨古镇": ("塔尔萨古镇", "site"),
    "塔卫二|星门": ("塔卫二", "site"),
    "科罗萨分布带|塔尔干分布带|璟屿分布带": ("源石矿脉分布带", "site"),
}

# 排序用的规范名 → 层级序号（大区 > 大陆 > 国家 > 城市 > 设施 > 地点，
# 仅用于同级聚合展示，不参与时间排序）
_PLACE_KIND_ORDER = {"continent": 0, "nation": 1, "region": 2, "city": 3, "facility": 4, "site": 5}


def normalize_location(text: str):
    """
    把原文地点表达归一化为 (location_name, location_kind, matched)。
    命中词典返回规范名；未命中返回 (原文, 'unspecified', False)。
    长别名优先：先按 | 分割别名，按长度降序尝试包含匹配。
    """
    if not text or not str(text).strip():
        return "", "unspecified", False
    s = str(text).strip()
    # 构建匹配项目：按别名长度降序，保证"罗德岛本舰"在"罗德岛"之前匹配
    entries = []
    for aliases, (name, kind) in PLACE_DICT.items():
        for a in aliases.split("|"):
            a = a.strip()
            if a:
                entries.append((a, name, kind))
    entries.sort(key=lambda x: -len(x[0]))
    for alias, name, kind in entries:
        if alias in s:
            return name, kind, True
    return s, "unspecified", False


# ---------------------------------------------------------------------------
# 事件类型枚举
# ---------------------------------------------------------------------------
EV_TYPES = [
    "birth", "life", "education", "duty", "task", "conflict",
    "disaster", "culture", "milestone", "farewell", "other",
]
_TIME_KINDS = ["year", "age", "phase", "period", "season", "literal", "unspecified"]


def normalize_ev_type(raw) -> str:
    if not raw:
        return "other"
    v = str(raw).strip().lower()
    return v if v in EV_TYPES else "other"


def normalize_time_kind(raw) -> str:
    if not raw:
        return "unspecified"
    v = str(raw).strip().lower()
    return v if v in _TIME_KINDS else "unspecified"


# ---------------------------------------------------------------------------
# 时间锚解析
# ---------------------------------------------------------------------------
# 绝对纪年：3-4 位数字 + 年
_RE_YEAR = re.compile(r'(\d{3,4})\s*年')
# 世纪表达：本世纪三十年代 / 三十年代
_RE_DECADE = re.compile(r'(\d{1,2}|[一二三四五六七八九十百]+)\s*0\s*年?代', re.IGNORECASE)
# 年龄锚：中文/阿拉伯数字 + 岁/岁生日
_RE_AGE = re.compile(r'([一二三四五六七八九十]+|\d{1,3})\s*岁')
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
_CN_NUM_MULT = {"十": 10, "百": 100}


def _cn_to_int(s: str):
    if s.isdigit():
        return int(s)
    # 处理 十、十五、二十、五十一 等
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十")
        a = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        b = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return a * 10 + b
    return _CN_NUM.get(s, 0)


# 年龄/阶段词表 → 年龄段区间 [low, high)
PHASE_RANGES = {
    "小时候": (0, 12),
    "童年": (0, 12),
    "上学年龄": (6, 12),
    "少年": (10, 18),
    "十多岁": (10, 18),
    "青年": (16, 35),
    "成年": (18, 50),
    "中年": (40, 65),
    "老年": (60, 220),
    "年事已高": (60, 220),
}


def parse_time_anchor(time_text: str):
    """
    解析时间表达，返回归一化字段 dict：
      {year, year_lower, year_upper, age, age_lower, age_upper,
       time_kind, sort_lower, sort_upper, seq_anchor}
    seq_anchor 用于叙述顺序兜底。
    """
    if not time_text:
        return None
    t = str(time_text)
    out = {
        "year": None, "year_lower": None, "year_upper": None,
        "age": None, "age_lower": None, "age_upper": None,
        "time_kind": "unspecified", "sort_lower": None, "sort_upper": None,
    }
    # 绝对纪年
    m = _RE_YEAR.search(t)
    if m:
        out["year"] = int(m.group(1)); out["year_lower"] = out["year"]; out["year_upper"] = out["year"]
        out["time_kind"] = "year"
        out["sort_lower"] = out["year"] * 10.0; out["sort_upper"] = out["year"] * 10.0
        return out
    # 年龄锚
    m = _RE_AGE.search(t)
    if m:
        age = _cn_to_int(m.group(1))
        out["age"] = age; out["age_lower"] = age; out["age_upper"] = age
        out["time_kind"] = "age"
        out["sort_lower"] = float(age); out["sort_upper"] = float(age)
        return out
    # 阶段词表
    for phase, (lo, hi) in PHASE_RANGES.items():
        if phase in t:
            out["age_lower"] = lo; out["age_upper"] = hi
            out["time_kind"] = "phase"
            mid = (lo + hi) / 2.0
            out["sort_lower"] = lo; out["sort_upper"] = hi
            return out
    # 世纪/年代
    dm = _RE_DECADE.search(t)
    if dm:
        decade_base = _cn_to_int(dm.group(1)) * 10
        out["year_lower"] = decade_base; out["year_upper"] = decade_base + 9
        out["time_kind"] = "period"
        out["sort_lower"] = float(decade_base) * 10.0
        out["sort_upper"] = float(decade_base + 9) * 10.0
        return out
    # 其余 → 无显式锚，kind=literal/unspecified，sort 交由调用方按 seq 赋
    out["time_kind"] = "literal" if t.strip() else "unspecified"
    return out
