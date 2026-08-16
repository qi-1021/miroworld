
import pytest

from app.services.text_patch import (
    CorrectionPatch, apply_patches, patches_to_markdown, parse_patches_md,
    PATCH_OPS,
)

TEXT = ("第一章 相遇\n"
        "他在村口救下女孩，他们一路向北。\n"
        "第二章 分离\n"
        "女孩被带走，他发誓复仇。\n")


def _p(**kw):
    base = {"id": "c1", "operation": "replace", "anchor": "", "content": ""}
    base.update(kw)
    return CorrectionPatch(**base)


# ---------------------------------------------------------------------------
# 四种操作
# ---------------------------------------------------------------------------
class TestOps:
    def test_replace(self):
        r, rep = apply_patches(TEXT, [_p(anchor="一路向北", content="一路向南")])
        assert "一路向南" in r and "一路向北" not in r
        assert len(rep["applied"]) == 1

    def test_delete(self):
        r, rep = apply_patches(TEXT, [_p(operation="delete", anchor="女孩被带走，")])
        assert "女孩被带走，" not in r
        assert "他发誓复仇" in r

    def test_insert_after(self):
        r, rep = apply_patches(TEXT, [_p(operation="insert_after",
                                         anchor="一路向北", content="，且心怀故乡")])
        assert "一路向北，且心怀故乡" in r

    def test_append(self):
        r, rep = apply_patches(TEXT, [_p(operation="append", content="尾声：他在北方定居。")])
        assert r.endswith("尾声：他在北方定居。")

    def test_empty_anchor_means_append(self):
        # 任意 op，anchor 为空 → 追加
        r, rep = apply_patches(TEXT, [_p(operation="replace", anchor="", content="补充：终章。")])
        assert r.endswith("补充：终章。")


# ---------------------------------------------------------------------------
# anchor 唯一 / 多义 + context 消歧
# ---------------------------------------------------------------------------
class TestAnchorDisambiguation:
    def test_unique_anchor(self):
        r, rep = apply_patches("甲乙丙", [_p(anchor="乙", operation="replace", content="X")])
        assert r == "甲X丙"

    def test_ambiguous_without_context_fallback(self):
        r, rep = apply_patches("乙乙乙", [_p(anchor="乙", operation="replace", content="X")])
        assert len(rep["skipped"]) == 1
        assert "定位不中" in rep["skipped"][0]["reason"]

    def test_context_after_disambiguates(self):
        r, rep = apply_patches("乙A。乙B。", [
            _p(anchor="乙", operation="replace", content="X", context_after="B")])
        assert r == "乙A。XB。"
        assert len(rep["applied"]) == 1

    def test_context_before_disambiguates(self):
        r, rep = apply_patches("A乙。B乙。", [
            _p(anchor="乙", operation="replace", content="X", context_before="B")])
        assert r == "A乙。BX。"
        assert len(rep["applied"]) == 1


# ---------------------------------------------------------------------------
# 定位失败回落
# ---------------------------------------------------------------------------
class TestFallback:
    def test_fallback_append_default(self):
        r, rep = apply_patches("正文。", [_p(anchor="不存在的锚点", operation="replace",
                                            content="补")])
        assert r.endswith("补")
        assert len(rep["skipped"]) == 1
        assert "fallback" in rep["skipped"][0]["reason"]

    def test_fallback_skip_when_not_append(self):
        r, rep = apply_patches("正文。", [_p(anchor="不存在的锚点", operation="replace",
                                            content="补")], fallback="skip")
        assert r == "正文。"
        assert len(rep["skipped"]) == 1
        assert "跳过" in rep["skipped"][0]["reason"]


# ---------------------------------------------------------------------------
# 冲突检测（同位置后者覆盖）
# ---------------------------------------------------------------------------
class TestConflict:
    def test_same_anchor_later_overrides_with_warning(self):
        r, rep = apply_patches("他拥有一把剑。", [
            _p(anchor="剑", operation="replace", content="刀"),
            _p(anchor="剑", operation="replace", content="枪"),
        ])
        # 两次都作用于 "剑"；第二次（后者）覆盖前者 → 枪
        assert "枪" in r
        assert "刀" not in r
        assert len(rep["conflicts"]) >= 1
        assert any("覆盖" in c["reason"] for c in rep["conflicts"])

    def test_different_anchors_no_conflict(self):
        r, rep = apply_patches(TEXT, [
            _p(anchor="一路向北", operation="replace", content="一路向南"),
            _p(anchor="他发誓复仇", operation="insert_after", content="，多年后"),
        ])
        assert len(rep["conflicts"]) == 0


# ---------------------------------------------------------------------------
# 非法输入 / 稳健性（不抛异常）
# ---------------------------------------------------------------------------
class TestRobustness:
    def test_unknown_op_skipped(self):
        r, rep = apply_patches(TEXT, [_p(operation="nonsense", anchor="一路向北")])
        assert r == TEXT
        assert rep["skipped"][0]["reason"].startswith("未知 operation")

    def test_from_dict_and_empty_patches(self):
        r, rep = apply_patches(TEXT, [])
        assert r == TEXT and rep == {"applied": [], "skipped": [], "conflicts": []}

    def test_never_raises(self):
        for patches in [None, [None], [{}], [{"operation": "replace"}], [123], ["x"]]:
            if not isinstance(patches, list):
                continue
            r, rep = apply_patches(TEXT, patches)
            assert isinstance(r, str)
            assert set(rep.keys()) >= {"applied", "skipped", "conflicts"}

    def test_return_type_is_tuple(self):
        out = apply_patches(TEXT, [_p(anchor="一路向北", content="x")])
        assert isinstance(out, tuple) and len(out) == 2


# ---------------------------------------------------------------------------
# Markdown 往返（幂等）
# ---------------------------------------------------------------------------
class TestMarkdownRoundtrip:
    def test_roundtrip_preserves_all_fields(self):
        patches = [
            CorrectionPatch(id="p1", anchor="一路向北", operation="replace",
                            content="一路向南", context_before="他们", context_after="。",
                            round=2, created_at="2026-01-01"),
            CorrectionPatch(id="p2", operation="append", content="尾声。", round=1),
        ]
        md = patches_to_markdown(patches)
        assert "## 补丁 p1" in md
        parsed = parse_patches_md(md)
        assert len(parsed) == 2
        a, b = parsed
        assert a.id == "p1" and a.anchor == "一路向北" and a.operation == "replace"
        assert a.content == "一路向南" and a.context_before == "他们" and a.context_after == "。"
        assert a.round == 2 and a.created_at == "2026-01-01"
        assert b.id == "p2" and b.operation == "append" and b.content == "尾声。"

    def test_content_with_newline_escaped(self):
        patches = [CorrectionPatch(id="p", anchor="a", operation="replace",
                                   content="第一段\n第二段")]
        md = patches_to_markdown(patches)
        back = parse_patches_md(md)[0]
        assert back.content == "第一段\n第二段"

    def test_parse_empty_returns_empty(self):
        assert parse_patches_md("") == []
        assert parse_patches_md(None) == []

    def test_from_dict_rounding_anchor_max(self):
        p = CorrectionPatch.from_dict({"id": "x", "anchor": "长" * 90, "operation": "replace"})
        assert len(p.anchor) <= 80


# ---------------------------------------------------------------------------
# 集成形状：驱动 corrected_story 渲染
# ---------------------------------------------------------------------------
class TestRenderIntegration:
    def test_render_corrected_document(self):
        corpus = ("第一章 相遇\n"
                  "他在村口救下女孩，他们一路向北。\n"
                  "第二章 分离\n"
                  "女孩被带走，他发誓复仇。\n")
        patches = [
            CorrectionPatch(id="c1", anchor="一路向北", operation="replace",
                            content="一路向南"),
            CorrectionPatch(id="c2", anchor="他发誓复仇", operation="insert_after",
                            content="，多年后实现"),
        ]
        r, rep = apply_patches(corpus, patches)
        assert "一路向南" in r and "一路向北" not in r
        assert "他发誓复仇，多年后实现" in r
        assert len(rep["applied"]) == 2
        assert rep["skipped"] == []
