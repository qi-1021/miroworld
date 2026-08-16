"""
冲突改正文件生成服务（确定性实现，不依赖 LLM）

在创作流程里，冲突辩驳"成功生效"后，创作者需要一个可落地的产出：
- corrected_settings.md   改正后的设定文档（以原始背景设定为基础 + 生效裁定说明）
- corrected_story.md      改正后的正文文档（以原始正文为基础 + 生效裁定说明）
- corrections.json        机器可读的改正清单（供程序消费）

本服务完全确定性：直接根据冲突报告中的"已生效裁定"（effective=true）与
每条冲突的 status / last_verdict / suggestion / resolution_note 生成，不调用 LLM。

幂等与多轮：
- 以 conflict_id 为键去重；对同一冲突多次生成不会产生重复条目。
- 多次调用（辩驳每轮成功后再生成）都是幂等的重算：读取最新生效裁定并重写三个文件。
- 未生效（open / 被驳回待继续辩解）的冲突不会进入改正清单。

存储位置：<WORLD_DATA_ROOT>/<project_id>/corrections/
  - corrections.json
  - corrected_settings.md
  - corrected_story.md
"""

import os
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json, atomic_write_text
from .conflict_detector import (
    ConflictItem,
    ConflictReport,
    load_conflict_report,
)
from .world_bible import WORLD_DATA_ROOT

logger = get_logger('mirofish.correction')

# 单词条说明上限
MAX_NOTE_LEN = 800


# ---------------------------------------------------------------- 数据模型

@dataclass
class CorrectionEntry:
    """一条已生效冲突对应的改正指令（机器可读）。"""
    conflict_id: str
    topic: str
    conflict_type: str
    status: str            # accepted | dismissed | justified
    verdict: str           # '' | defense_accepted | defense_partial
    action: str            # correct_story | waive_story | canonical_note | partial_correction
    target_file: str       # corrected_story.md | corrected_settings.md
    note: str              # 面向创作者/下游的说明（可直接合入文档）
    applied_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CorrectionEntry':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CorrectionSet:
    """一次改正生成的结果：三个文件的完整内容。"""
    project_id: str
    corrections: List[CorrectionEntry] = field(default_factory=list)
    corrections_json: str = ""       # corrections.json 的文本内容
    corrected_settings_md: str = ""  # corrected_settings.md 的文本内容
    corrected_story_md: str = ""     # corrected_story.md 的文本内容
    generated_at: str = ""

    def file_snapshot(self) -> Dict[str, Any]:
        """返回可用于接口响应的三个文件 + metadata。"""
        return {
            "generated_at": self.generated_at,
            "correction_count": len(self.corrections),
            "files": {
                "corrections.json": {
                    "filename": "corrections.json",
                    "mime": "application/json",
                    "content": self.corrections_json,
                },
                "corrected_settings.md": {
                    "filename": "corrected_settings.md",
                    "mime": "text/markdown",
                    "content": self.corrected_settings_md,
                },
                "corrected_story.md": {
                    "filename": "corrected_story.md",
                    "mime": "text/markdown",
                    "content": self.corrected_story_md,
                },
            },
        }


# ---------------------------------------------------------------- 服务

class ConflictCorrectionService:
    """从已生效的冲突裁定确定性生成改正文件。"""

    @staticmethod
    def corrections_dir(project_id: str) -> str:
        return os.path.join(WORLD_DATA_ROOT, project_id, "corrections")

    # ---------------- 生成 ----------------

    def generate(self, project_id: str) -> CorrectionSet:
        """读取最新冲突报告 + 背景/正文原文，重算三个改正文件（幂等）并落盘。

        返回 CorrectionSet；若项目无冲突报告或无可生效裁定，corrections 为空，
        但仍会生成仅含"未发现需改正项"说明的三个文件。
        """
        now = datetime.now().isoformat(timespec="seconds")
        report = load_conflict_report(project_id)
        iterations = self._collect_entries(project_id, report)
        # 以 conflict_id 去重，保证多轮幂等（后写覆盖先写，无重复条目）
        deduped: Dict[str, CorrectionEntry] = {}
        for e in iterations:
            deduped[e.conflict_id] = e
        entries = sorted(deduped.values(), key=lambda e: (e.applied_at, e.conflict_id))

        # 加载基础语料（background→settings 底本，story→正文底本）
        from .world_bible import WorldBibleService
        bible = WorldBibleService.get_bible(project_id)
        corrector = CorpusCorrector()
        corrector.set_corpus(
            settings_text=bible.background_text if bible else "",
            story_text=bible.story_text if bible else "",
        )
        corrector.apply_entries(entries)

        corrections_json = self._render_corrections_json(project_id, entries, now)
        settings_md = self._render_settings_md(
            project_id, corrector, now,
        )
        story_md = self._render_story_md(
            project_id, corrector, now,
        )

        result = CorrectionSet(
            project_id=project_id,
            corrections=entries,
            corrections_json=corrections_json,
            corrected_settings_md=settings_md,
            corrected_story_md=story_md,
            generated_at=now,
        )
        self._persist(project_id, result)
        return result

    # ---------------- 数据收集与行动判定 ----------------

    @staticmethod
    def _collect_entries(
        project_id: str,
        report: Optional[ConflictReport],
    ) -> List[CorrectionEntry]:
        """遍历冲突报告，仅收集"已生效"裁定的冲突并推导改正指令。"""
        entries: List[CorrectionEntry] = []
        if report is None:
            return entries
        for c in report.conflicts:
            entry = ConflictCorrectionService._entry_for_conflict(c)
            if entry is not None:
                entries.append(entry)
        return entries

    @staticmethod
    def _entry_for_conflict(c: ConflictItem) -> Optional[CorrectionEntry]:
        """把一条冲突转成改正指令；未生效（open/被驳回）返回 None。"""
        if not getattr(c, "effective", False) or c.status == "open":
            return None
        status = c.status  # accepted | dismissed | justified
        verdict = c.last_verdict or ""
        note = ConflictCorrectionService._compose_note(c, status, verdict)
        if status == "accepted":
            action = "correct_story"
            target = "corrected_story.md"
        elif status == "dismissed":
            action = "waive_story"
            target = "corrected_story.md"
        elif status == "justified":
            if verdict == "defense_rejected":
                # 理论不到达（rejected 会回退 open，不 effective），防御性跳过
                return None
            if verdict == "defense_partial":
                action = "partial_correction"
                target = "corrected_story.md" if c.suggestion else "corrected_settings.md"
            else:
                action = "canonical_note"
                target = "corrected_settings.md"
        else:  # 未知状态，防御性跳过
            return None
        return CorrectionEntry(
            conflict_id=c.conflict_id,
            topic=c.topic,
            conflict_type=c.conflict_type,
            status=status,
            verdict=verdict,
            action=action,
            target_file=target,
            note=(note or "")[:MAX_NOTE_LEN],
            applied_at=datetime.now().isoformat(timespec="seconds"),
        )

    @staticmethod
    def _compose_note(c: ConflictItem, status: str, verdict: str) -> str:
        """生成一条面向创作者的说明文本。"""
        if status == "accepted":
            base = c.suggestion or (
                f"该处正文与设定冲突，以设定为准，按建议调整正文：{c.story_fact or ''} → {c.background_fact or ''}"
            )
            return f"【以设定为准】{c.topic}。{base}"
        if status == "dismissed":
            reason = c.resolution_note or "认定为不影响整体设定的例外"
            return f"【忽略例外】{c.topic}。正文保持既有写法，忽略此矛盾（{reason}）。"
        # justified
        reason = c.resolution_note or "创作者给出了合理辩解"
        if verdict == "defense_partial":
            residual = c.suggestion or "仍有残留问题需按建议处理"
            return f"【部分成立】{c.topic}。接受辩解，但仍有残留：{residual}。说明：{reason}"
        return f"【辩解成立】{c.topic}。此矛盾经由 {reason} 获得合理解释，视为设定内的合理写法，不再作为错误。{c.suggestion or ''}"

    # ---------------- 渲染 ----------------

    def _render_corrections_json(self, project_id: str, entries, now: str) -> str:
        payload = {
            "project_id": project_id,
            "generated_at": now,
            "source": "conflict_correction",
            "corrections": [e.to_dict() for e in entries],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _render_settings_md(self, project_id: str, corrector: 'CorpusCorrector', now: str) -> str:
        lines = [
            f"# 改正后的设定文档（corrected_settings）",
            "",
            f"> 依据冲突裁定确定性生成 · {now}",
            "",
            "## 基础设定",
            "",
            corrector.settings_text or "（无背景设定原文）",
            "",
            "## 生效裁定说明（改正记录）",
            "",
        ]
        if corrector.settings_log:
            for item in corrector.settings_log:
                lines.append(f"- {item}")
        else:
            lines.append("- 未发现需要改正的生效裁定。")
        lines.append("")
        return "\n".join(lines)

    def _render_story_md(self, project_id: str, corrector: 'CorpusCorrector', now: str) -> str:
        lines = [
            f"# 改正后的正文文档（corrected_story）",
            "",
            f"> 依据冲突裁定确定性生成 · {now}",
            "",
            "## 正文",
            "",
            corrector.story_text or "（无小说正文）",
            "",
            "## 改正记录",
            "",
        ]
        for item in corrector.story_log:
            lines.append(f"- [{item['action']}] {item['topic']}: {item['note']}")
        if not corrector.story_log:
            lines.append("- 未发现需要改正的正文裁定。")
        lines.append("")
        return "\n".join(lines)

    # ---------------- 落盘 ----------------

    def _persist(self, project_id: str, result: CorrectionSet) -> None:
        d = self.corrections_dir(project_id)
        os.makedirs(d, exist_ok=True)
        atomic_write_text(os.path.join(d, "corrected_settings.md"), result.corrected_settings_md)
        atomic_write_text(os.path.join(d, "corrected_story.md"), result.corrected_story_md)
        atomic_write_text(os.path.join(d, "corrections.json"), result.corrections_json)

    # ---------------- 读取 ----------------

    @classmethod
    def load(cls, project_id: str) -> Optional[CorrectionSet]:
        """读取最近一次生成的改正文件；不存在返回 None。"""
        d = cls.corrections_dir(project_id)
        corrections_path = os.path.join(d, "corrections.json")
        if not os.path.exists(corrections_path):
            return None
        try:
            with open(corrections_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            entries = [CorrectionEntry.from_dict(e) for e in payload.get("corrections", [])]
            settings_md = _read_or("", os.path.join(d, "corrected_settings.md"))
            story_md = _read_or("", os.path.join(d, "corrected_story.md"))
            return CorrectionSet(
                project_id=project_id,
                corrections=entries,
                corrections_json=json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                corrected_settings_md=settings_md,
                corrected_story_md=story_md,
                generated_at=payload.get("generated_at", ""),
            )
        except Exception as e:
            logger.warning(f"读取改正文件失败: project={project_id}, err={e}")
            return None


class CorpusCorrector:
    """把基础语料（背景设定 / 小说正文）与改正记录合并成最终文档文本。"""

    def __init__(self):
        self.settings_text = ""
        self.story_text = ""
        self.settings_log: List[str] = []
        self.story_log: List[Dict[str, str]] = []

    def apply_entries(self, entries: List[CorrectionEntry]) -> None:
        """按改正指令分类填充 settings_log / story_log。"""
        for e in entries:
            if e.action in ("correct_story", "waive_story", "partial_correction"):
                self.story_log.append({"action": e.action, "topic": e.topic, "note": e.note})
            else:
                self.settings_log.append(e.note)

    def set_corpus(self, settings_text: str, story_text: str) -> None:
        self.settings_text = (settings_text or "").strip()
        self.story_text = (story_text or "").strip()


def _read_or(fallback: str, path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return fallback


# ---------------------------------------------------------------- 便捷函数

def generate_corrections(project_id: str) -> CorrectionSet:
    """便捷入口：生成并返回改正文件结果。"""
    svc = ConflictCorrectionService()
    return svc.generate(project_id)


def load_corrections(project_id: str) -> Optional[CorrectionSet]:
    """便捷入口：读取最近一次改正文件。"""
    return ConflictCorrectionService.load(project_id)
