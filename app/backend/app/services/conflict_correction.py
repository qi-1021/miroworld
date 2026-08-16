"""
冲突改正文件生成服务（外挂补丁架构，确定性，不依赖 LLM）

在创作流程里，冲突辩驳"成功生效"后，创作者需要一个可落地的产出。为适配体量大的
小说/设定文本，本服务**不复制全文再改**，而是只产出【外挂小补丁】：

- corrections.json        机器可读清单：corrections（历次生效裁定）+ patches（外挂补丁）
- corrected_patches.md   人类可读的小 sidecar：仅记录「定位点 → 替换/插入/删除」，不复制正文

呈现/下载层需要完整合并稿时，再对【原始语料 + patches】做确定性叠加（见
app/services/patch_apply.py 的 apply_patches），按需动态渲染，不落盘大文件。

本服务完全确定性：直接根据冲突报告中的"已生效裁定"（effective=true）与每条冲突的
status / last_verdict / suggestion / resolution_note / quote 生成，不调用 LLM。

补丁模型（与 patch_apply.apply_patches 对齐）：
    {
      "op": "replace" | "insert_after" | "insert_before" | "delete",
      "locator": "<源语料中的锚点原文，需精确出现>",
      "old_text": "",   # replace/delete：要移除的精确文段（通常=locator 或其子串）
      "new_text": "",   # replace/insert_*：替换/插入内容
      "source": "settings" | "story",
      "conflict_id": "<触发来源>",
      "note": "<人类可读说明>"
    }

行动判定（settled 冲突 → 补丁/注解）：
- accepted(correct_story)          → replace 补丁：以 story_quote 为锚，正文改成背景说法
- dismissed(waive_story)           → 仅注解（正文保持，不产变更补丁）
- justified(defense_accepted)      → 仅注解（canonical_note，设定侧记录辩解）
- justified(defense_partial)       → 可产补丁（若落在 story 且有 quote/suggestion），否则注解
- open / 被驳回（无 effective）    → 一律不纳入

幂等与多轮：
- 以 conflict_id 为键去重，同一冲突多次生成不重复。
- generate() 每次都是幂等重算：读取最新生效裁定并仅重写两个文件。

存储位置：<WORLD_DATA_ROOT>/<project_id>/corrections/
  - corrections.json
  - corrected_patches.md

旧数据迁移：老版本 t10 曾把 corrected_settings.md / corrected_story.md（整本复制）落盘。
新版不再写这两个文件；generate() 会以最新生效裁定重建 patches，直接覆盖 corrections.json；
旧的整本副本文件若尚存，会由 _persist 清理掉（_cleanup_legacy_full_duplicates）。
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
# 合法 op
PATCH_OPS = ("replace", "delete", "insert_after", "insert_before")


# ---------------------------------------------------------------- 数据模型

@dataclass
class CorrectionEntry:
    """一条已生效冲突对应的改正指令（机器可读，注解维度）。"""
    conflict_id: str
    topic: str
    conflict_type: str
    status: str            # accepted | dismissed | justified
    verdict: str           # '' | defense_accepted | defense_partial
    action: str            # correct_story | waive_story | canonical_note | partial_correction
    target_source: str     # 'settings' | 'story'（补丁归属语料）
    note: str              # 面向创作者/下游的解释
    patch: Optional[dict] = None   # 该裁定对应的外挂补丁（None=无文本变更，仅注解）
    applied_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CorrectionEntry':
        kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)


@dataclass
class CorrectionSet:
    """一次改正生成的结果：两个文件的完整内容（不复制全文）。"""
    project_id: str
    corrections: List[CorrectionEntry] = field(default_factory=list)
    corrections_json: str = ""       # corrections.json 文本
    corrected_patches_md: str = ""   # corrected_patches.md 文本
    generated_at: str = ""

    @property
    def patches(self) -> List[dict]:
        """本次生成的外挂补丁清单（仅文本变更类）。"""
        return [e.patch for e in self.corrections if e.patch]

    def file_snapshot(self) -> Dict[str, Any]:
        """返回可用于接口响应的两个文件 + metadata。"""
        return {
            "generated_at": self.generated_at,
            "correction_count": len(self.corrections),
            "patch_count": len(self.patches),
            "files": {
                "corrections.json": {
                    "filename": "corrections.json",
                    "mime": "application/json",
                    "content": self.corrections_json,
                },
                "corrected_patches.md": {
                    "filename": "corrected_patches.md",
                    "mime": "text/markdown",
                    "content": self.corrected_patches_md,
                },
            },
        }


# ---------------------------------------------------------------- 服务

class ConflictCorrectionService:
    """从已生效的冲突裁定确定性生成外挂补丁 + 注解清单。"""

    # 旧版整本复制文件（t10 遗留），新版不再产出，迁移时清理
    LEGACY_FULL_FILES = ("corrected_settings.md", "corrected_story.md")

    @staticmethod
    def corrections_dir(project_id: str) -> str:
        return os.path.join(WORLD_DATA_ROOT, project_id, "corrections")

    # ---------------- 生成 ----------------

    def generate(self, project_id: str) -> CorrectionSet:
        """读取最新冲突报告，重算外挂补丁+注解清单（幂等）并落盘两个文件。

        返回 CorrectionSet；若项目无冲突报告或无可生效裁定，结果为空的清单。
        """
        now = datetime.now().isoformat(timespec="seconds")
        report = load_conflict_report(project_id)
        iterations = self._collect_entries(project_id, report)
        # 以 conflict_id 去重（多轮幂等）
        deduped: Dict[str, CorrectionEntry] = {}
        for e in iterations:
            deduped[e.conflict_id] = e
        entries = sorted(deduped.values(), key=lambda e: (e.applied_at, e.conflict_id))

        corrections_json = self._render_corrections_json(project_id, entries, now)
        patches_md = self._render_patches_md(project_id, entries, now)

        result = CorrectionSet(
            project_id=project_id,
            corrections=entries,
            corrections_json=corrections_json,
            corrected_patches_md=patches_md,
            generated_at=now,
        )
        self._persist(project_id, result)
        self._cleanup_legacy_full_duplicates(project_id)
        return result

    # ---------------- 数据收集与行动判定 ----------------

    @staticmethod
    def _collect_entries(
        project_id: str,
        report: Optional[ConflictReport],
    ) -> List[CorrectionEntry]:
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
        """把一条已生效冲突转成「注解 + 可选外挂补丁」；未生效返回 None。"""
        if not getattr(c, "effective", False) or c.status == "open":
            return None
        status = c.status
        verdict = c.last_verdict or ""
        note = ConflictCorrectionService._compose_note(c, status, verdict)

        if status == "accepted":
            action = "correct_story"
            target = "story"
        elif status == "dismissed":
            action = "waive_story"
            target = "story"
        elif status == "justified":
            if verdict == "defense_rejected":
                return None  # 防御性（实际 rejected 会回退 open）
            if verdict == "defense_partial":
                action = "partial_correction"
                target = "story" if c.suggestion else "settings"
            else:
                action = "canonical_note"
                target = "settings"
        else:
            return None

        patch = ConflictCorrectionService._build_patch(c, action, target)
        return CorrectionEntry(
            conflict_id=c.conflict_id,
            topic=c.topic,
            conflict_type=c.conflict_type,
            status=status,
            verdict=verdict,
            action=action,
            target_source=target,
            note=(note or "")[:MAX_NOTE_LEN],
            patch=patch,
            applied_at=datetime.now().isoformat(timespec="seconds"),
        )

    @staticmethod
    def _compose_note(c: ConflictItem, status: str, verdict: str) -> str:
        if status == "accepted":
            base = c.suggestion or (
                f"以设定为准，按建议调整正文：{c.story_fact or ''} → {c.background_fact or ''}"
            )
            return f"【以设定为准】{c.topic}。{base}"
        if status == "dismissed":
            reason = c.resolution_note or "认定为不影响整体设定的例外"
            return f"【忽略例外】{c.topic}。正文保持既有写法，忽略此矛盾（{reason}）。"
        reason = c.resolution_note or "创作者给出了合理辩解"
        if verdict == "defense_partial":
            residual = c.suggestion or "仍有残留问题需按建议处理"
            return f"【部分成立】{c.topic}。接受辩解，但仍有残留：{residual}。说明：{reason}"
        return f"【辩解成立】{c.topic}。此矛盾经由 {reason} 获得合理解释，视为设定内的合理写法，不再作为错误。{c.suggestion or ''}"

    @staticmethod
    def _build_patch(c: ConflictItem, action: str, target: str) -> Optional[dict]:
        """为文本变更类裁定构造外挂补丁；无可靠定位或纯注解则返回 None。

        定位基准优先取正文的原文引用（story_quote 精确在正文中），退化用 story_fact。
        """
        # 只有“要改 story 文本”的动作才产补丁；waive/canonical 纯注解，不产。
        if action not in ("correct_story", "partial_correction") or target != "story":
            return None

        locator = (c.story_quote or "").strip()
        old_text = (c.story_quote or "").strip()
        if not locator and c.story_fact:
            # 退化：用事实文本作 locator（可能在正文中不精确出现 → apply 时跳过）
            old_text = (c.story_fact or "").strip()
            locator = old_text
        if not locator:
            return None

        new_text = (c.background_fact or c.suggestion or "").strip()
        if new_text and not new_text.endswith(("。", "！", "？", "；", ";")):
            new_text = new_text + "。"
        return {
            "op": "replace",
            "locator": locator,
            "old_text": old_text,
            "new_text": new_text,
            "source": "story",
            "conflict_id": c.conflict_id,
            "note": f"{c.topic}：以设定为准，正文 '{old_text}' → '{new_text or '...'}'",
        }

    # ---------------- 渲染 ----------------

    def _render_corrections_json(self, project_id: str, entries, now: str) -> str:
        payload = {
            "project_id": project_id,
            "generated_at": now,
            "source": "conflict_correction",
            "mode": "patch_sidecar",
            "corrections": [e.to_dict() for e in entries],
            "patches": [e.patch for e in entries if e.patch],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _render_patches_md(self, project_id: str, entries, now: str) -> str:
        lines = [
            "# 改正补丁（corrected_patches）",
            "",
            f"> 外挂小补丁，不复制全文。呈现时以原始语料叠加这些补丁动态渲染。生成于 {now}",
            "",
            "## 文本补丁",
            "",
        ]
        mutated = [e for e in entries if e.patch]
        if mutated:
            for e in mutated:
                p = e.patch
                lines.append(f"### [{e.status}/{e.action}] {e.topic}")
                lines.append(f"- 语料: `{p['source']}`")
                lines.append(f"- 操作: `{p['op']}`")
                lines.append(f"- 定位点: `{p['locator']}`")
                if p.get("old_text") and p["old_text"] != p["locator"]:
                    lines.append(f"- 移除: `{p['old_text']}`")
                if p.get("new_text"):
                    lines.append(f"- 替换为: `{p['new_text']}`")
                if p.get("note"):
                    lines.append(f"- 说明: {p['note']}")
                lines.append("")
        else:
            lines.append("- 无需要文本变更的生效裁定。")
            lines.append("")

        lines.append("## 仅注解（不修改文本）")
        lines.append("")
        notes = [e for e in entries if not e.patch]
        if notes:
            for e in notes:
                lines.append(f"- [{e.status}/{e.action}] {e.topic}: {e.note}")
        else:
            lines.append("- 无。")
        lines.append("")
        return "\n".join(lines)

    # ---------------- 动态渲染合并全文（按需，不落盘） ----------------

    def render_merged(self, project_id: str, source: str) -> Dict[str, Any]:
        """对原始语料 + 外挂补丁做确定性叠加，返回合并全文（按需渲染）。

        source: 'settings' | 'story'
        返回 {"source","text","applied","skipped"}。
        """
        from .patch_apply import apply_patches

        set_ = self.load(project_id)
        corpus = self._corpus(project_id, source)
        patches = (set_.patches if set_ else [])
        if source == "settings":
            # 设定侧目前只有注解类补丁（canonical_note），不叠文本
            result = {"source": source, "text": corpus, "applied": [], "skipped": []}
            return result
        result = apply_patches(corpus, patches, source=source)
        result["source"] = source
        return result

    @staticmethod
    def _corpus(project_id: str, source: str) -> str:
        from .world_bible import WorldBibleService
        bible = WorldBibleService.get_bible(project_id)
        if bible is None:
            return ""
        return (bible.story_text if source == "story" else bible.background_text) or ""

    # ---------------- 落盘 ----------------

    def _persist(self, project_id: str, result: CorrectionSet) -> None:
        d = self.corrections_dir(project_id)
        os.makedirs(d, exist_ok=True)
        atomic_write_text(os.path.join(d, "corrections.json"), result.corrections_json)
        atomic_write_text(os.path.join(d, "corrected_patches.md"), result.corrected_patches_md)

    def _cleanup_legacy_full_duplicates(self, project_id: str) -> None:
        """清理旧版 t10 遗留的整本复制文件（新版不再产出）。"""
        d = self.corrections_dir(project_id)
        for fn in self.LEGACY_FULL_FILES:
            p = os.path.join(d, fn)
            try:
                if os.path.exists(p):
                    os.remove(p)
                    logger.info(f"移除旧版整本复制文件: {p}")
            except OSError as e:
                logger.warning(f"清理旧版文件失败 {p}: {e}")

    # ---------------- 读取 ----------------

    @classmethod
    def load(cls, project_id: str) -> Optional[CorrectionSet]:
        """读取最近一次生成的外挂补丁清单；不存在返回 None。"""
        d = cls.corrections_dir(project_id)
        corrections_path = os.path.join(d, "corrections.json")
        if not os.path.exists(corrections_path):
            return None
        try:
            with open(corrections_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            entries = [CorrectionEntry.from_dict(e) for e in payload.get("corrections", [])]
            return CorrectionSet(
                project_id=project_id,
                corrections=entries,
                corrections_json=json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                corrected_patches_md=_read_or("", os.path.join(d, "corrected_patches.md")),
                generated_at=payload.get("generated_at", ""),
            )
        except Exception as e:
            logger.warning(f"读取改正补丁失败: project={project_id}, err={e}")
            return None


# ---------------------------------------------------------------- 便捷函数

def _read_or(fallback: str, path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return fallback


def generate_corrections(project_id: str) -> CorrectionSet:
    """便捷入口：生成并返回外挂补丁结果。"""
    return ConflictCorrectionService().generate(project_id)


def load_corrections(project_id: str) -> Optional[CorrectionSet]:
    """便捷入口：读取最近一次外挂补丁。"""
    return ConflictCorrectionService.load(project_id)
