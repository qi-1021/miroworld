"""
世界设定冲突检测服务

检测"背景设定文档"与"小说正文"之间的矛盾，向创作者提醒具体冲突因素。

两阶段方法（适配大文档，控制 LLM 输入长度）：
1. 事实抽取：分别从背景与正文中抽取结构化设定事实（主体-谓词-客体 + 原文引用）
2. 冲突对比：将两份事实清单交给 LLM 对比，输出结构化冲突列表

冲突类型：
- fact_contradiction  事实矛盾（同一主体属性不一致）
- rule_violation      规则违反（正文行为违背背景规则）
- time_conflict       时间冲突（时间线/纪年矛盾）
- character_mismatch  人物设定不符（身份/关系矛盾）
- location_conflict   地点矛盾（地理/位置冲突）
- other               其他

结果存储：app/data/world/<project_id>/conflicts.json
"""

import os
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.atomic_json import atomic_write_json
from .world_bible import WORLD_DATA_ROOT

logger = get_logger('mirofish.conflict')

# 单次喂给 LLM 的文本上限（字符）
MAX_TEXT_PER_CALL = 6000
# 每来源最多抽取的事实条数
MAX_FACTS_PER_SOURCE = 40
# 对比时最多给 LLM 的事实条数（各来源）
MAX_FACTS_FOR_COMPARE = 25

# 事实抽取提示词
FACT_EXTRACT_PROMPT = """你是一名严谨的小说设定编辑。请从给定的文本中抽取**明确的设定事实**，用于后续检测"背景设定"与"正文内容"之间的矛盾。

要求：
1. 只抽取**明确的陈述**（人物身份、关系、属性、规则、时间、地点、物品归属等），不要抽取模糊的感受或修辞
2. 每个事实用 主体/谓词/客体 三元组表达，客体可以是属性值
3. 附上原文引用（quote），引用必须是原文中的连续片段，不超过 60 字
4. 按重要性排序，最多输出 {max_facts} 条
5. 只输出 JSON：{{"facts": [{{"subject": "主体", "predicate": "谓词", "object": "客体", "quote": "原文引用"}}]}}

文本内容：
{text}"""

# 冲突对比提示词
CONFLICT_COMPARE_PROMPT = """你是一名严谨的小说设定编辑，正在检查**背景设定文档**与**小说正文**之间的矛盾。

背景事实代表"世界应该是什么样的"（权威设定）；正文事实代表"故事中实际发生了什么"。

请逐条对比，找出**背景与正文相互矛盾**的地方，例如：
- 同一主体的属性不一致（背景说他是国王，正文说他是平民）
- 正文行为违反背景规则（背景规定魔法有代价，正文里主角免费施法）
- 时间线矛盾（背景说王国建于 300 年前，正文说 500 年前）
- 人物关系矛盾、地点位置矛盾等

要求：
1. 只报告真实矛盾，不要报告"正文补充了背景没有的信息"——补充不算冲突
2. 每条冲突输出：主题（topic）、冲突类型（conflict_type，取值：fact_contradiction/rule_violation/time_conflict/character_mismatch/location_conflict/other）、背景事实、正文事实、冲突原因（reason）、严重程度（severity，取值：high/medium/low）、修改建议（suggestion，指出应以哪边为准）
3. 最多输出 {max_conflicts} 条，按严重程度排序
4. 只输出 JSON：{{"conflicts": [{{"topic": "", "conflict_type": "", "background_fact": "", "story_fact": "", "background_quote": "", "story_quote": "", "reason": "", "severity": "", "suggestion": ""}}]}}

背景事实清单：
{background_facts}

正文事实清单：
{story_facts}"""


# ---------------------------------------------------------------- 数据模型

@dataclass
class FactItem:
    """一条设定事实"""
    subject: str
    predicate: str
    object: str
    quote: str = ""
    source: str = ""  # 'background' | 'story'

    def to_text(self) -> str:
        return f"{self.subject} {self.predicate} {self.object}（引：{self.quote}）"


@dataclass
class ConflictItem:
    """一条冲突"""
    conflict_id: str
    topic: str
    conflict_type: str
    background_fact: str
    story_fact: str
    background_quote: str = ""
    story_quote: str = ""
    reason: str = ""
    severity: str = "medium"
    suggestion: str = ""
    status: str = "open"  # open | accepted | dismissed | justified
    resolution_note: str = ""  # 用户自定义辩解/裁定说明（justified 时必填）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConflictItem':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ConflictReport:
    """一次冲突检测的完整结果"""
    project_id: str
    conflicts: List[ConflictItem] = field(default_factory=list)
    created_at: str = ""
    status: str = "completed"  # completed | failed
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)  # 事实数、文本规模等

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "created_at": self.created_at,
            "status": self.status,
            "error": self.error,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConflictReport':
        return cls(
            project_id=data.get('project_id', ''),
            conflicts=[ConflictItem.from_dict(c) for c in data.get('conflicts', [])],
            created_at=data.get('created_at', ''),
            status=data.get('status', 'completed'),
            error=data.get('error', ''),
            meta=data.get('meta', {}),
        )


# ---------------------------------------------------------------- 服务

class ConflictDetector:
    """世界设定冲突检测服务"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    # ---------------- 公开接口 ----------------

    def detect(self, project_id: str, background_text: str, story_text: str) -> ConflictReport:
        """
        检测背景与正文的冲突，返回报告（不落盘，由调用方决定是否保存）。
        """
        report = ConflictReport(
            project_id=project_id,
            created_at=datetime.now().isoformat(timespec='seconds'),
        )
        try:
            if not background_text.strip() or not story_text.strip():
                raise ValueError("冲突检测需要背景和正文都非空")

            # 阶段 1：抽取事实
            bg_facts = self._extract_facts(background_text, source='background')
            st_facts = self._extract_facts(story_text, source='story')
            logger.info(f"事实抽取完成: background={len(bg_facts)}, story={len(st_facts)}")

            # 阶段 2：对比
            if not bg_facts or not st_facts:
                report.meta = {"background_facts": len(bg_facts), "story_facts": len(st_facts)}
                logger.warning("某来源未抽取到事实，跳过对比")
                return report

            conflicts = self._compare_facts(bg_facts, st_facts)
            report.conflicts = conflicts
            report.meta = {
                "background_facts": len(bg_facts),
                "story_facts": len(st_facts),
                "background_chars": len(background_text),
                "story_chars": len(story_text),
            }
            return report

        except Exception as e:
            logger.error(f"冲突检测失败: {e}")
            report.status = "failed"
            report.error = str(e)
            return report

    def detect_with_progress(
        self,
        project_id: str,
        background_text: str,
        story_text: str,
        progress_cb=None,
    ) -> ConflictReport:
        """
        与 detect 相同，但通过 progress_cb(phase, progress) 汇报进度，
        供异步任务/前端使用。
        """
        report = ConflictReport(
            project_id=project_id,
            created_at=datetime.now().isoformat(timespec='seconds'),
        )
        try:
            if not background_text.strip() or not story_text.strip():
                raise ValueError("冲突检测需要背景和正文都非空")

            if progress_cb:
                progress_cb("抽取设定事实（背景）...", 10)
            bg_facts = self._extract_facts(background_text, source='background')

            if progress_cb:
                progress_cb("抽取设定事实（正文）...", 45)
            st_facts = self._extract_facts(story_text, source='story')

            if progress_cb:
                progress_cb("对比事实清单，定位冲突...", 70)
            if not bg_facts or not st_facts:
                report.meta = {"background_facts": len(bg_facts), "story_facts": len(st_facts)}
                if progress_cb:
                    progress_cb("未抽取到足够事实，跳过对比", 100)
                return report

            conflicts = self._compare_facts(bg_facts, st_facts)
            report.conflicts = conflicts
            report.meta = {
                "background_facts": len(bg_facts),
                "story_facts": len(st_facts),
                "background_chars": len(background_text),
                "story_chars": len(story_text),
            }
            if progress_cb:
                progress_cb("冲突检测完成", 100)
            return report

        except Exception as e:
            logger.error(f"冲突检测失败: {e}")
            report.status = "failed"
            report.error = str(e)
            return report

    # ---------------- 阶段 1：事实抽取 ----------------

    def _extract_facts(self, text: str, source: str) -> List[FactItem]:
        """分批抽取事实并合并去重"""
        all_facts: List[FactItem] = []
        seen: set = set()

        # 按行/段落切分，每批不超过 MAX_TEXT_PER_CALL
        batches = self._split_batches(text, MAX_TEXT_PER_CALL)
        for batch in batches:
            if len(all_facts) >= MAX_FACTS_PER_SOURCE:
                break
            prompt = FACT_EXTRACT_PROMPT.format(
                text=batch,
                max_facts=min(MAX_FACTS_PER_SOURCE - len(all_facts), 15),
            )
            try:
                result = self.llm.chat_json(
                    messages=[
                        {"role": "system", "content": "你是严谨的小说设定编辑，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                for item in result.get("facts", []) if isinstance(result, dict) else []:
                    if not isinstance(item, dict):
                        continue
                    fact = FactItem(
                        subject=str(item.get("subject", "")).strip(),
                        predicate=str(item.get("predicate", "")).strip(),
                        object=str(item.get("object", "")).strip(),
                        quote=str(item.get("quote", "")).strip(),
                        source=source,
                    )
                    key = (fact.subject, fact.predicate, fact.object)
                    if key in seen or not fact.subject:
                        continue
                    seen.add(key)
                    all_facts.append(fact)
            except Exception as e:
                logger.warning(f"事实抽取批次失败: {e}，跳过该批")
                continue

        return all_facts[:MAX_FACTS_PER_SOURCE]

    # ---------------- 阶段 2：冲突对比 ----------------

    def _compare_facts(self, bg_facts: List[FactItem], st_facts: List[FactItem]) -> List[ConflictItem]:
        """对比两份事实清单，输出冲突列表"""
        # 控制输入规模：优先保留与正文主体相关的背景事实
        bg_keep = self._prioritize_facts(bg_facts, st_facts, MAX_FACTS_FOR_COMPARE)
        st_keep = st_facts[:MAX_FACTS_FOR_COMPARE]

        bg_lines = "\n".join(f"- {f.to_text()}" for f in bg_keep)
        st_lines = "\n".join(f"- {f.to_text()}" for f in st_keep)

        prompt = CONFLICT_COMPARE_PROMPT.format(
            background_facts=bg_lines,
            story_facts=st_lines,
            max_conflicts=20,
        )
        result = self.llm.chat_json(
            messages=[
                {"role": "system", "content": "你是严谨的小说设定编辑，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        conflicts: List[ConflictItem] = []
        for item in result.get("conflicts", []) if isinstance(result, dict) else []:
            if not isinstance(item, dict):
                continue
            conflict = ConflictItem(
                conflict_id=uuid.uuid4().hex[:12],
                topic=str(item.get("topic", "")).strip(),
                conflict_type=str(item.get("conflict_type", "other")).strip() or "other",
                background_fact=str(item.get("background_fact", "")).strip(),
                story_fact=str(item.get("story_fact", "")).strip(),
                background_quote=str(item.get("background_quote", "")).strip(),
                story_quote=str(item.get("story_quote", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                severity=str(item.get("severity", "medium")).strip() or "medium",
                suggestion=str(item.get("suggestion", "")).strip(),
            )
            if conflict.topic and (conflict.background_fact or conflict.story_fact):
                conflicts.append(conflict)
        return conflicts

    # ---------------- 工具 ----------------

    @staticmethod
    def _split_batches(text: str, max_chars: int) -> List[str]:
        """按段落边界切分，每批不超过 max_chars 字符"""
        if len(text) <= max_chars:
            return [text]
        paragraphs = [p for p in text.split('\n') if p.strip()]
        batches: List[str] = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 1 > max_chars:
                if current:
                    batches.append(current)
                # 单个段落超长则硬切
                if len(para) > max_chars:
                    for i in range(0, len(para), max_chars):
                        batches.append(para[i:i + max_chars])
                    current = ""
                else:
                    current = para
            else:
                current = (current + '\n' + para) if current else para
        if current:
            batches.append(current)
        return batches

    @staticmethod
    def _prioritize_facts(bg_facts: List[FactItem], st_facts: List[FactItem], limit: int) -> List[FactItem]:
        """优先保留与正文主体相关的背景事实（主体名匹配），不足再补其余"""
        st_subjects = {f.subject for f in st_facts}
        related = [f for f in bg_facts if f.subject in st_subjects]
        rest = [f for f in bg_facts if f.subject not in st_subjects]
        ordered = related + rest
        return ordered[:limit]


# ---------------------------------------------------------------- 存储

def save_conflict_report(project_id: str, report: ConflictReport) -> None:
    """保存冲突检测报告（原子写）"""
    d = os.path.join(WORLD_DATA_ROOT, project_id)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, 'conflicts.json')
    atomic_write_json(path, report.to_dict())


def load_conflict_report(project_id: str) -> Optional[ConflictReport]:
    """读取最近一次冲突检测报告"""
    path = os.path.join(WORLD_DATA_ROOT, project_id, 'conflicts.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return ConflictReport.from_dict(json.load(f))
    except Exception as e:
        logger.error(f"读取冲突报告失败: project={project_id}, err={e}")
        return None
