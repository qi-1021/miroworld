"""冲突改正文件生成服务 + 接口测试（外挂补丁架构，确定性，不依赖 LLM）"""

import os

import pytest

from app import create_app
from app.services.conflict_correction import (
    ConflictCorrectionService,
    generate_corrections,
    load_corrections,
)


@pytest.fixture()
def client(tmp_path):
    """隔离世界数据目录的 Flask 测试客户端。"""
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc

    world_root = str(tmp_path / "world")
    orig = {
        "wb": wb.WORLD_DATA_ROOT,
        "cd": cd.WORLD_DATA_ROOT,
        "cc": cc.WORLD_DATA_ROOT,
    }
    wb.WORLD_DATA_ROOT = world_root
    cd.WORLD_DATA_ROOT = world_root
    cc.WORLD_DATA_ROOT = world_root

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._roots = orig
        yield c

    wb.WORLD_DATA_ROOT = orig["wb"]
    cd.WORLD_DATA_ROOT = orig["cd"]
    cc.WORLD_DATA_ROOT = orig["cc"]


def _seed(client, conflicts, background="龙裔王国建于三百年前。首都是龙脊城。",
          story="清晨，艾拉说：\"五百年前建立的龙裔王国，如今连城门都破了。\"法师卡尔随手施法。"):
    """落盘一份 bible + 冲突报告（含指定冲突），返回项目 id。"""
    from app.services.world_bible import WorldBibleService
    from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report

    WorldBibleService.save_input("p1", background, story)
    save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=conflicts))
    return "p1"


def _conflict(cid, story_quote="", resolution_note="", **_extra):
    from app.services.conflict_detector import ConflictItem, DefenseRound
    verdict = _extra.pop("verdict", "")
    status = _extra.get("status", "accepted")
    base = dict(
        conflict_id=cid, topic=f"T{cid}", conflict_type="time_conflict",
        background_fact="龙裔王国建于三百年前", story_fact="龙裔王国建于五百年前",
        story_quote=story_quote,
        status=status, effective=bool(_extra.get("effective", status in ("accepted", "justified", "dismissed"))),
        suggestion="以背景为准修改为三百年前", resolution_note=resolution_note,
    )
    c = ConflictItem(**base)
    if verdict:
        c.defense_rounds.append(DefenseRound(
            round_id=f"{cid}_a1", role="assistant", content="裁定",
            verdict=verdict, created_at="t"))
    return c


# ---------------------------------------------------------------- 服务层

def test_generate_patch_sidecar_not_full_copy(tmp_path):
    """accept 冲突产文本补丁，justified/dismissed 仅注解；只落盘两个文件，不复制全文。"""
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report
        # 用一段带叙事特征的正文，便于验证 sidecar 不复制整本
        bg = "龙裔王国建于三百年前，首都是龙脊城。魔法需付出代价。"
        st = "清晨的街道上，艾拉抬头望着高耸的城门，低语道：\"五百年前建立的龙裔王国，如今连城门都破了。\""
        WorldBibleService.save_input("p1", bg, st)
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[
            _conflict("c1", story_quote="五百年前建立的龙裔王国", status="accepted", effective=True),
            _conflict("c2", status="justified", effective=True,
                      resolution_note="主角为特例", verdict="defense_accepted"),
            _conflict("c3", status="dismissed", effective=True, resolution_note="视为例外"),
        ]))
        r = generate_corrections("p1")
        assert len(r.corrections) == 3
        # c1 → correct_story 且产补丁（story 侧）；c2/c3 仅注解，无补丁
        by_id = {e.conflict_id: e for e in r.corrections}
        assert by_id["c1"].action == "correct_story"
        assert by_id["c1"].target_source == "story"
        assert by_id["c1"].patch is not None
        assert by_id["c1"].patch["op"] == "replace"
        assert by_id["c1"].patch["locator"] == "五百年前建立的龙裔王国"
        assert by_id["c2"].patch is None
        assert by_id["c3"].patch is None
        assert len(r.patches) == 1

        # 幂等：再生成不翻倍
        r2 = generate_corrections("p1")
        assert len(r2.corrections) == 3
        assert len(r2.patches) == 1

        # 落盘只有两个文件；不再有整本复制文件
        d = cc.ConflictCorrectionService.corrections_dir("p1")
        assert sorted(os.listdir(d)) == ["corrected_patches.md", "corrections.json"]
        assert "五百年前建立的龙裔王国" in r.corrected_patches_md  # 补丁 sidecar 含定位点
        # 不复制整本正文：sidecar 不含叙事性正文片段（只含补丁，不含整本复制）
        assert "清晨的街道上，艾拉抬头望着" not in r.corrected_patches_md

        # load 能读回
        loaded = load_corrections("p1")
        assert loaded is not None
        assert len(loaded.corrections) == 3
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


def test_render_merged_applies_patches(tmp_path):
    """对原始语料 + 外挂补丁动态渲染合并全文（用 patch_apply.apply_patches）。"""
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report
        bg = "龙裔王国建于三百年前。首都是龙脊城。"
        st = "艾拉说：\"五百年前建立的龙裔王国，如今连城门都破了。\""
        WorldBibleService.save_input("p1", bg, st)
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[
            _conflict("c1", story_quote="五百年前建立的龙裔王国",
                      status="accepted", effective=True),
        ]))
        generate_corrections("p1")
        merged = ConflictCorrectionService().render_merged("p1", "story")
        assert merged["applied"]  # 补丁已应用
        assert "龙裔王国建于三百年前" in merged["text"]
        assert "五百年前建立的龙裔王国" not in merged["text"]
        # settings 侧无可叠补丁，原样返回
        ms = ConflictCorrectionService().render_merged("p1", "settings")
        assert ms["text"] == bg
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


def test_render_merged_skips_unlocatable_patch(tmp_path):
    """定位不中的补丁不抛异常：进 skipped，并按引擎 fallback（append）追加到文末。"""
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report
        st = "艾拉说：\"五百年前建立的龙裔王国。\""
        WorldBibleService.save_input("p1", "背景一句话。", st)
        # story_quote 与正文不完全一致 → apply 定位不中进 skipped；引擎 fallback 追加到文末
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[
            _conflict("c1", story_quote="并不存在的原文锚点", status="accepted", effective=True),
        ]))
        generate_corrections("p1")
        merged = ConflictCorrectionService().render_merged("p1", "story")
        assert merged["skipped"]  # 有 skipped（定位不中/已回退）
        # 原文保留，且改写内容按 fallback=append 追加到文末
        assert merged["text"].startswith(st)
        assert "龙裔王国建于三百年前" in merged["text"]
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


def test_open_or_rejected_conflicts_not_included(tmp_path):
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, DefenseRound, save_conflict_report
        WorldBibleService.save_input("p1", "A", "B")
        open_c = _conflict("c_open", status="open", effective=False)
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[open_c]))
        r = generate_corrections("p1")
        assert r.corrections == []
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


def test_generate_with_no_report(tmp_path):
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        r = generate_corrections("none")
        assert r is not None
        assert r.corrections == []
        assert "无需要文本变更" in r.corrected_patches_md
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


def test_legacy_full_copy_files_cleaned(tmp_path):
    """旧版 t10 的整本复制文件在生成后被清理，不残留。"""
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report
        WorldBibleService.save_input("p1", "背景一句话。", "正文一句话。")
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[
            _conflict("c1", status="accepted", effective=True),
        ]))
        d = cc.ConflictCorrectionService.corrections_dir("p1")
        os.makedirs(d, exist_ok=True)
        # 模拟旧版遗留整本复制文件
        for fn in ("corrected_settings.md", "corrected_story.md"):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write("# 旧的整本复制内容")
        generate_corrections("p1")
        assert not os.path.exists(os.path.join(d, "corrected_settings.md"))
        assert not os.path.exists(os.path.join(d, "corrected_story.md"))
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


# ---------------------------------------------------------------- 接口层

def test_corrections_endpoints_generate_and_get(client):
    _seed(client, [_conflict("c1", story_quote="五百年前建立的龙裔王国", status="accepted", effective=True)])
    # 未生成前 GET → has_files False
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    assert rv.status_code == 200
    assert rv.get_json()["has_files"] is False

    # POST 生成 → 返回两个 sidecar 文件 + patches 结构化
    rv = client.post("/api/world/p1/conflicts/c1/corrections")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["correction_count"] == 1
    assert body["patch_count"] == 1
    assert set(body["files"].keys()) == {"corrections.json", "corrected_patches.md"}
    assert body["patches"][0]["op"] == "replace"
    assert body["patches"][0]["locator"] == "五百年前建立的龙裔王国"
    # 不再出现整本复制文件
    assert "corrected_settings.md" not in body["files"]
    assert "corrected_story.md" not in body["files"]
    # 补丁 sidecar 含定位点而非整本正文
    assert "五百年前建立的龙裔王国" in body["files"]["corrected_patches.md"]["content"]

    # GET 现可读到
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    g = rv.get_json()
    assert g["has_files"] is True
    assert g["patch_count"] == 1
    assert g["patches"][0]["op"] == "replace"


def test_corrections_missing_conflict_404(client):
    rv = client.post("/api/world/p1/conflicts/nope/corrections")
    assert rv.status_code == 404
    rv = client.get("/api/world/p1/conflicts/nope/corrections")
    assert rv.status_code == 404


def test_corrections_download(client):
    _seed(client, [_conflict("c1", story_quote="五百年前建立的龙裔王国", status="accepted", effective=True)])
    client.post("/api/world/p1/conflicts/c1/corrections")
    rv = client.get("/api/world/p1/conflicts/c1/corrections/corrected_patches.md/download")
    assert rv.status_code == 200
    assert "五百年前建立的龙裔王国" in rv.data.decode("utf-8")
    # 非法文件名
    rv = client.get("/api/world/p1/conflicts/c1/corrections/evil.txt/download")
    assert rv.status_code == 400
    # corrections.json 可下载
    rv = client.get("/api/world/p1/conflicts/c1/corrections/corrections.json/download")
    assert rv.status_code == 200


def test_render_endpoint(client):
    _seed(client, [_conflict("c1", story_quote="五百年前建立的龙裔王国", status="accepted", effective=True)])
    client.post("/api/world/p1/conflicts/c1/corrections")
    rv = client.get("/api/world/p1/conflicts/c1/corrections/render?source=story")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["source"] == "story"
    assert "龙裔王国建于三百年前" in body["text"]
    # 非法 source
    rv = client.get("/api/world/p1/conflicts/c1/corrections/render?source=bogus")
    assert rv.status_code == 400
    # download 模式返回 md 附件
    rv = client.get("/api/world/p1/conflicts/c1/corrections/render?source=settings&download=1")
    assert rv.status_code == 200
    assert "改正后的设定" in rv.data.decode("utf-8")


def test_patch_conflict_auto_generates_corrections(client):
    """PATCH 辩驳成功后应自动生成外挂补丁文件。"""
    _seed(client, [_conflict("c1", status="open", effective=False)])
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "accepted"})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["conflict"]["effective"] is True
    assert body.get("corrections_regenerated") is True
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    assert rv.get_json()["has_files"] is True
