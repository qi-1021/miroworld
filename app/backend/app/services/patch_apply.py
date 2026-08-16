"""兼容层：旧补丁接口 → 文本外挂补丁引擎（text_patch）。

历史背景：早期给 conflict_correction 定过一组旧补丁 dict（op replace/insert_after/delete
+ locator/old_text/new_text + source），返回形状 {"text","applied","skipped"}、带 source 过滤。
经 t13 收口，规范引擎落在 app/services/text_patch.py（CorrectionPatch，返回 (text, report)）。
本模块保留了旧调用方（conflict_correction.render_merged 等）所需签名/形状，把旧补丁 dict
翻译为 CorrectionPatch 后委托给 text_patch 引擎，避免 t13/t15 两半拼不上。
"""

from typing import Any, Dict, List, Optional

from .text_patch import CorrectionPatch, apply_patches as _engine_apply


_LEGACY_OP_MAP = {"replace": "replace", "insert_after": "insert_after",
                  "delete": "delete", "append": "append"}


def _to_correction_patch(old: Dict[str, Any]) -> CorrectionPatch:
    """把旧补丁 dict 翻译为 CorrectionPatch。

    - old_text 存在 → 用它作 anchor（replace/delete 更精确）；否则回落 locator/anchor。
    - source 不进入 CorrectionPatch（由外层 source 过滤处理）。
    """
    op = _LEGACY_OP_MAP.get(str((old.get("op") or old.get("operation") or "replace")).strip(),
                            "replace")
    anchor = str(old.get("old_text") or "").strip() or \
        str(old.get("anchor") or "").strip() or str(old.get("locator") or "").strip()
    return CorrectionPatch(
        id=str(old.get("id") or old.get("conflict_id") or "").strip() or "patch",
        anchor=anchor,
        operation=op,
        content=str(old.get("new_text") or old.get("content") or ""),
        context_before=str(old.get("context_before") or ""),
        context_after=str(old.get("context_after") or ""),
        round=int(old.get("round") or 1),
    )


def apply_patches(text: str,
                  patches: List[Any],
                  source: Optional[str] = None) -> Dict[str, Any]:
    """旧接口形态的 apply_patches：字典返回 + source 过滤。

    返回 {"text","applied","skipped"}：
    - text    : 叠加后全文。
    - applied : [{id, operation, anchor, ...}]。
    - skipped : [{id, reason}]。
    指定 source 时，patch.source 与 source 不一致 → 记 skipped("source 不匹配")，不参与叠加。
    """
    corr_patches: List[CorrectionPatch] = []
    base_skipped: List[Dict[str, Any]] = []
    for i, patch in enumerate(patches or []):
        if isinstance(patch, CorrectionPatch):
            p_source = ""
        elif isinstance(patch, dict):
            p_source = str(patch.get("source") or "")
        else:
            base_skipped.append({"id": f"p{i}", "reason": "不是 dict"})
            continue
        if source is not None and p_source and p_source != source:
            base_skipped.append({"id": str(patch.get("conflict_id") or patch.get("id") or f"p{i}"),
                                 "reason": "source 不匹配"})
            continue
        cp = patch if isinstance(patch, CorrectionPatch) else _to_correction_patch(patch)
        corr_patches.append(cp)

    merged, report = _engine_apply(text or "", corr_patches, fallback="append")

    skipped = base_skipped + list(report["skipped"])
    for c in report["conflicts"]:
        skipped.append({"id": c["id"], "reason": c["reason"]})

    return {"text": merged,
            "applied": list(report["applied"]),
            "skipped": skipped}
