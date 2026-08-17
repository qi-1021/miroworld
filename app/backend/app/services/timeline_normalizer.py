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
# 时间锚解析（全面支持小说架空纪年、修仙/科幻历法、相对时间与精确排序）
# ---------------------------------------------------------------------------
# 绝对与架空纪年：公元/星历/天元/神武/新历/创世历/西历/泰拉历 + 数字 + 年
_RE_ERA_YEAR = re.compile(r'(?:公元|星历|天元|神武|新历|创世历|西历|泰拉历|圣历|光和|元和|建安|永徽|贞观|开元|洪武|万历|天启|崇祯)?\s*(\d{1,5})\s*年')
# 汉字纪年（如：三年、二十五年、一百二十年）
_RE_CN_YEAR = re.compile(r'([一二两三四五六七八九十百千]+)\s*年')
# 世纪表达：本世纪三十年代 / 三十年代 / 20世纪
_RE_DECADE = re.compile(r'(\d{1,2}|[一二三四五六七八九十百]+)\s*0\s*年?代', re.IGNORECASE)
# 年龄锚：中文/阿拉伯数字 + 岁/岁生日
_RE_AGE = re.compile(r'([一二三四五六七八九十]+|\d{1,3})\s*岁')
# 相对时间偏移：X年后 / X个月后 / X天后 / 次年 / 翌年 / 数月后 / 数年后 / 半年后
_RE_REL_YEAR_AFTER = re.compile(r'([一二两三四五六七八九十\d]+)\s*年\s*(?:之?后|以后|后)')
_RE_REL_YEAR_BEFORE = re.compile(r'([一二两三四五六七八九十\d]+)\s*年\s*(?:之?前|以前|前)')
_RE_REL_MONTH_AFTER = re.compile(r'([一二两三四五六七八九十\d]+)\s*(?:个)?月\s*(?:之?后|以后|后)')
_RE_REL_DAYS_AFTER = re.compile(r'([一二两三四五六七八九十\d]+)\s*天\s*(?:之?后|以后|后)')

_CN_NUM = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000
}

def _cn_to_int(s: str) -> int:
    if not s:
        return 0
    s = str(s).strip()
    if s.isdigit():
        return int(s)
    # 处理千、百、十复合汉字数字（如 一百二十五、三千五百、二十三）
    total = 0
    curr = 0
    for char in s:
        if char in ("千", "百", "十"):
            mult = 1000 if char == "千" else (100 if char == "百" else 10)
            if curr == 0:
                curr = 1
            total += curr * mult
            curr = 0
        elif char in _CN_NUM:
            curr = _CN_NUM[char]
    total += curr
    return total if total > 0 else _CN_NUM.get(s, 0)


# 年龄/阶段词表 → 年龄段区间 [low, high)
PHASE_RANGES = {
    "幼年": (0, 6),
    "小时候": (0, 12),
    "童年": (0, 12),
    "上学年龄": (6, 12),
    "少年": (10, 18),
    "十多岁": (10, 18),
    "青年": (16, 35),
    "及冠": (20, 25),
    "弱冠": (20, 25),
    "而立": (30, 35),
    "成年": (18, 50),
    "不惑": (40, 45),
    "中年": (40, 65),
    "知天命": (50, 55),
    "花甲": (60, 65),
    "古稀": (70, 75),
    "耄耋": (80, 90),
    "老年": (60, 220),
    "暮年": (70, 220),
    "年事已高": (60, 220),
}


def parse_time_anchor(time_text: str):
    """
    解析时间表达，返回归一化字段 dict：
      {year, year_lower, year_upper, age, age_lower, age_upper,
       time_kind, sort_lower, sort_upper, seq_anchor}
    """
    if not time_text:
        return None
    t = str(time_text).strip()
    out = {
        "year": None, "year_lower": None, "year_upper": None,
        "age": None, "age_lower": None, "age_upper": None,
        "time_kind": "unspecified", "sort_lower": None, "sort_upper": None,
    }

    # 1. 绝对纪年与架空小说历法（星历2045年 / 1098年 / 神武三年）
    m_era = _RE_ERA_YEAR.search(t)
    if m_era:
        yr = int(m_era.group(1))
        out["year"] = yr; out["year_lower"] = yr; out["year_upper"] = yr
        out["time_kind"] = "year"
        out["sort_lower"] = yr * 10.0; out["sort_upper"] = yr * 10.0
        return out

    # 2. 汉字纪年（如 建安三年、光和五年）
    m_cn_yr = _RE_CN_YEAR.search(t)
    if m_cn_yr:
        yr = _cn_to_int(m_cn_yr.group(1))
        if yr > 0:
            out["year"] = yr; out["year_lower"] = yr; out["year_upper"] = yr
            out["time_kind"] = "year"
            out["sort_lower"] = yr * 10.0; out["sort_upper"] = yr * 10.0
            return out

    # 3. 相对时间跨度（三年后 / 次年 / 翌年 / 两年训练后 / 数年经历后 / 半年后 / 5天后）
    if "次年" in t or "翌年" in t or "第二年" in t:
        out["time_kind"] = "period"
        out["sort_lower"] = 1.0 * 10.0
        out["sort_upper"] = 1.0 * 10.0
        return out
    if "数月后" in t or "数日后" in t or "几天后" in t or "不久后" in t or "片刻后" in t:
        out["time_kind"] = "literal"
        return out

    # 匹配：两年后 / 经过两年训练和数年医疗经历后 / 两年训练后
    m_rya = _RE_REL_YEAR_AFTER.search(t)
    if m_rya:
        delta_y = _cn_to_int(m_rya.group(1)) or 1
        # 如果句中还包含"数年"或多段经历，累加跨度
        if "数年" in t and delta_y < 10:
            delta_y += 3
        out["time_kind"] = "period"
        out["sort_lower"] = float(delta_y) * 10.0
        out["sort_upper"] = float(delta_y) * 10.0
        return out

    # 匹配单独的"数年后"或"多年后"
    if "数年后" in t or "多年后" in t or "数年" in t:
        out["time_kind"] = "period"
        out["sort_lower"] = 30.0
        out["sort_upper"] = 30.0
        return out

    # 4. 年龄锚
    m_age = _RE_AGE.search(t)
    if m_age:
        age = _cn_to_int(m_age.group(1))
        out["age"] = age; out["age_lower"] = age; out["age_upper"] = age
        out["time_kind"] = "age"
        out["sort_lower"] = float(age); out["sort_upper"] = float(age)
        return out

    # 5. 阶段词表
    for phase, (lo, hi) in PHASE_RANGES.items():
        if phase in t:
            out["age_lower"] = lo; out["age_upper"] = hi
            out["time_kind"] = "phase"
            out["sort_lower"] = float(lo); out["sort_upper"] = float(hi)
            return out

    # 6. 世纪/年代
    dm = _RE_DECADE.search(t)
    if dm:
        decade_base = _cn_to_int(dm.group(1)) * 10
        out["year_lower"] = decade_base; out["year_upper"] = decade_base + 9
        out["time_kind"] = "period"
        out["sort_lower"] = float(decade_base) * 10.0
        out["sort_upper"] = float(decade_base + 9) * 10.0
        return out

    out["time_kind"] = "literal" if t else "unspecified"
    return out
