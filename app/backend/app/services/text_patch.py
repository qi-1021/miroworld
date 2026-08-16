"""
文本外挂补丁引擎（通用 sidecar patch）。

用于冲突改正等场景：不复制整本、只把改正以小补丁（anchor 定位）外挂到原文，
在呈现/下载时动态叠加以得到“合并全文”。纯 stdlib、确定性、无 LLM。

数据结构 CorrectionPatch（dict/dataclass 双形态兼容）：
    id             : 补丁唯一标识
    anchor         : 定位点原文片段（≤80 字；可为空串表示“追加/文末”）
    operation      : 'replace' | 'insert_after' | 'delete' | 'append'
    content        : replace/insert_after/append 的新文本（delete 忽略）
    context_before  : 可选，用于多匹配消歧的上文片段
    context_after   : 可选，用于多匹配消歧的下文片段
    created_at     : 创建时间（字符串）
    round          : 冲突讨论轮次（int）

apply_patches(text, patches, fallback="append") -> (result_text, report)
    逐个应用，返回 (叠加后全文, report)。定位：
      - anchor 唯一精确命中 → 直接应用。
      - 多匹配 → 用 context_before/context_after 缩小（前后文都命中才唯一）。
      - 定位失败 → 按 fallback 追加到文末，并在 report 记录 patch_id + reason。
      - 同一 anchor 位置多 patch 冲突 → 按 patch 顺序后者覆盖前者，并在 report
        记录 conflict_warning（前者已应用的结果被后者改写）。
      - 绝不抛异常；失败/回落都有 report 记录。

patches_to_markdown(patches) / parse_patches_md(md)
    把补丁清单序列化为可读 markdown，并可反序列化（幂等往返）。
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 合法 operation 枚举
PATCH_OPS = {"replace", "insert_after", "delete", "append"}
# anchor 长度上限（规范：≤80）
ANCHOR_MAX = 80


@dataclass
class CorrectionPatch:
    """一条外挂改正补丁。anchor 为空表示追加/文末。"""
    id: str
    anchor: str = ""
    operation: str = "replace"
    content: str = ""
    context_before: str = ""
    context_after: str = ""
    created_at: str = ""
    round: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> "CorrectionPatch":
        if not isinstance(d, dict):
            return cls(id="")
        op = str(d.get("operation") or "replace").strip()
        if op not in PATCH_OPS:
            op = "replace"
        return cls(
            id=str(d.get("id") or "").strip(),
            anchor=str(d.get("anchor") or "")[:_ANCHOR_MAX],
            operation=op,
            content=str(d.get("content") or ""),
            context_before=str(d.get("context_before") or ""),
            context_after=str(d.get("context_after") or ""),
            created_at=str(d.get("created_at") or ""),
            round=int(d.get("round") or 1),
        )


_ANCHOR_MAX = ANCHOR_MAX


def _count_matches(text: str, needle: str) -> int:
    if not needle:
        return 0
    return len(re.findall(re.escape(needle), text))


def _first_match(text: str, needle: str) -> Optional[int]:
    idx = text.find(needle)
    return idx if idx >= 0 else None


def _match_with_context(text: str, anchor: str,
                        before: str, after: str) -> Optional[Tuple[int, int]]:
    """在 text 中找 anchor，用 before/after 上下文缩小到唯一匹配。

    返回 (start, end)（end 为 anchor 结束下标，不含 after）；无法唯一确定返回 None。
    规则：
      - 仅当 anchor 在 text 中恰好匹配 1 处 → 直接返回该处。
      - 多匹配 → 若提供了 before/after，取“紧邻 anchor 之前含 before”或“紧邻 anchor
        之后含 after”的匹配；当且仅当用上下文能缩小到唯一时返回。
      - 仍无法唯一 → None（调用方走 fallback）。
    """
    positions = [m.start() for m in re.finditer(re.escape(anchor), text)]
    if not positions:
        return None
    if len(positions) == 1:
        return (positions[0], positions[0] + len(anchor))

    candidates = positions
    if before:
        candidates = [p for p in candidates if text[max(0, p - len(before)):p].endswith(before)]
        if len(candidates) == 1:
            return (candidates[0], candidates[0] + len(anchor))
        if not candidates:
            candidates = positions
    if after:
        narrowed = [p for p in candidates
                    if text[p + len(anchor):p + len(anchor) + len(after)].startswith(after)]
        if len(narrowed) == 1:
            return (narrowed[0], narrowed[0] + len(anchor))
    return None


def _apply_single(text: str, patch: CorrectionPatch) -> Optional[str]:
    """应用单条补丁；无法定位返回 None。

    - append /（anchor 为空的各种 op）：追加 content 到文末。
    - replace：用 content 替换 anchor。
    - delete：删除 anchor（content 忽略）。
    - insert_after：在 anchor 之后插入 content。
    """
    op = patch.operation
    anchor = patch.anchor
    content = patch.content

    if op == "append" or not anchor.strip():
        # 追加语义（anchor 为空 → 文末追加）
        return text + (content if text.endswith("\n") or not text else "\n" + content)

    span = _match_with_context(text, anchor, patch.context_before, patch.context_after)
    if span is None:
        return None
    start, end = span

    if op == "replace":
        return text[:start] + content + text[end:]
    if op == "delete":
        return text[:start] + text[end:]
    if op == "insert_after":
        return text[:end] + content + text[end:]
    return None


def apply_patches(text: str,
                  patches: List[Any],
                  fallback: str = "append") -> Tuple[str, Dict[str, Any]]:
    """把补丁逐个、确定性地叠加到 text 上，动态渲染合并全文。

    Args:
        text    : 原始语料全文。
        patches : CorrectionPatch（或 dict）列表。
        fallback: 定位/操作失败的处置：
                    "append"（默认）：追加 content 到文末并记录；
                    其他值 → 跳过该 patch，不写文本，仅记录。
    Returns:
        (result_text, report)，report = {
            "applied"   : [{id, operation, anchor}],
            "skipped"   : [{id, reason}],           # 定位失败/非法
            "conflicts" : [{id, reason}],           # 同位置后被覆盖/冲突警告
        }
    """
    result = text or ""
    report: Dict[str, List[Dict[str, Any]]] = {
        "applied": [], "skipped": [], "conflicts": [],
    }

    # 同一 anchor 的 replace 覆盖链：anchor -> 最近一次替换进去的文本。
    # 当后续 replace 命中同一 anchor（前序已替换、anchor 已消失）时，
    # 用该“最近替换文本”定位并进行覆盖 → 后者覆盖前者，符合契约。
    last_replace: Dict[str, str] = {}

    for idx, patch in enumerate(patches or []):
        if isinstance(patch, CorrectionPatch):
            p = patch
        else:
            p = CorrectionPatch.from_dict(patch)
        if not p.id:
            p = CorrectionPatch(id=f"p{idx}", anchor=p.anchor, operation=p.operation,
                                content=p.content, context_before=p.context_before,
                                context_after=p.context_after, created_at=p.created_at,
                                round=p.round)
        # 非法 op
        if p.operation not in PATCH_OPS:
            report["skipped"].append({"id": p.id, "reason": f"未知 operation: {p.operation!r}"})
            continue

        # ---- 追加语义（append 或空 anchor）不受冲突检测限制 ----
        if p.operation == "append" or not p.anchor.strip():
            sep = "\n" if (result and not result.endswith("\n") and result.strip()) else ""
            result = result + sep + p.content
            report["applied"].append({"id": p.id, "operation": p.operation, "anchor": ""})
            continue

        # ---- 同一 anchor 的 replace 覆盖（后者覆盖前者） ----
        if p.operation == "replace" and p.anchor in last_replace:
            prev = last_replace[p.anchor]
            if prev in result:
                result = result.replace(prev, p.content, 1)
                last_replace[p.anchor] = p.content
                report["conflicts"].append({
                    "id": p.id,
                    "reason": "同一 anchor 已有前序 replace，按顺序后者覆盖前者",
                })
                report["applied"].append({"id": p.id, "operation": p.operation, "anchor": p.anchor})
                continue

        new_text = _apply_single(result, p)
        if new_text is None:
            # 定位失败 → fallback
            if fallback == "append":
                sep = "\n" if (result and not result.endswith("\n")) else ""
                result = result + sep + p.content
                report["skipped"].append({
                    "id": p.id,
                    "reason": f"定位不中（anchor={p.anchor!r}），已按 fallback 追加到文末",
                })
            else:
                report["skipped"].append({
                    "id": p.id,
                    "reason": f"定位不中（anchor={p.anchor!r}），fallback={fallback}，跳过未写入",
                })
            continue

        result = new_text
        if p.operation == "replace":
            last_replace[p.anchor] = p.content
        report["applied"].append({
            "id": p.id,
            "operation": p.operation,
            "anchor": p.anchor,
        })

    return result, report


# ---------------------------------------------------------------------------
# Markdown 序列化 / 反序列化（幂等往返）
# ---------------------------------------------------------------------------
_MD_BLOCK_RE = re.compile(r'^## 补丁\s+(.+)$', re.MULTILINE)
_MD_FIELD_RE = re.compile(r'^-\s+(\w+)\s*:\s?(.*)$', re.MULTILINE)
_MD_SCALAR_FIELDS = ("op", "operation", "anchor", "content", "context_before",
                     "context_after", "round", "id", "created_at")


def _md_escape(s: str) -> str:
    return (s or "").replace("\n", "\\n").replace("\\", "\\\\")


def _md_unescape(s: str) -> str:
    return (s or "").replace("\\\\", "\\").replace("\\n", "\n")


def patches_to_markdown(patches: List[Any]) -> str:
    """把补丁清单序列化为可读 markdown（幂等）。空清单返回空串。"""
    lines: List[str] = ["# 文本外挂补丁清单"]
    for patch in patches:
        p = patch if isinstance(patch, CorrectionPatch) else CorrectionPatch.from_dict(patch)
        block = ["", f"## 补丁 {p.id}",
                 f"- op: {p.operation}",
                 f"- anchor: {_md_escape(p.anchor)}",
                 f"- content: {_md_escape(p.content)}",
                 f"- context_before: {_md_escape(p.context_before)}",
                 f"- context_after: {_md_escape(p.context_after)}",
                 f"- round: {p.round}",
                 f"- created_at: {p.created_at}"]
        lines.extend(block)
    return "\n".join(lines) + ("\n" if lines else "")


def parse_patches_md(md: str) -> List[CorrectionPatch]:
    """把 patches_to_markdown 产出的 md 反序列化回补丁列表（幂等往返）。"""
    if not md or not md.strip():
        return []
    blocks = _MD_BLOCK_RE.split(md)
    # split 返回 [前导, id1, body1, id2, body2, ...]
    patches: List[CorrectionPatch] = []
    it = iter(blocks)
    next(it, None)  # 前导
    for pid in it:
        body = next(it, "")
        fields: Dict[str, str] = {"id": pid.strip()}
        for m in _MD_FIELD_RE.finditer(body):
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key in _MD_SCALAR_FIELDS:
                fields[key] = _md_unescape(val)
        if "op" in fields and "operation" not in fields:
            fields["operation"] = fields.pop("op")
        round_v = 1
        try:
            round_v = int(fields.get("round") or 1)
        except (TypeError, ValueError):
            round_v = 1
        patches.append(CorrectionPatch(
            id=fields.get("id") or "",
            anchor=fields.get("anchor") or "",
            operation=fields.get("operation") or "replace",
            content=fields.get("content") or "",
            context_before=fields.get("context_before") or "",
            context_after=fields.get("context_after") or "",
            created_at=fields.get("created_at") or "",
            round=round_v,
        ))
    return patches
