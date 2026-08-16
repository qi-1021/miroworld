"""冲突改正文件生成服务 + 接口测试（确定性，不依赖 LLM）"""

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


def _seed(client, conflicts, background="龙裔王国建于三百年前。", story="龙裔王国建于五百年前。"):
    """落盘一份 bible + 冲突报告（含指定冲突），返回项目 id。"""
    from app.services.world_bible import WorldBibleService
    from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report

    WorldBibleService.save_input("p1", background, story)
    save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=conflicts))
    return "p1"


def _conflict(cid, resolution_note="", **_extra):
    from app.services.conflict_detector import ConflictItem, DefenseRound
    verdict = _extra.pop("verdict", "")
    status = _extra.get("status", "accepted")
    base = dict(
        conflict_id=cid, topic=f"T{cid}", conflict_type="time_conflict",
        background_fact="三百年前", story_fact="五百年前",
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

def test_generate_deterministic_and_idempotent(tmp_path):
    import app.services.conflict_detector as cd
    import app.services.conflict_correction as cc
    import app.services.world_bible as wb
    orig = (cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT)
    root = str(tmp_path / "w")
    cd.WORLD_DATA_ROOT = wb.WORLD_DATA_ROOT = cc.WORLD_DATA_ROOT = root
    try:
        from app.services.world_bible import WorldBibleService
        from app.services.conflict_detector import ConflictItem, ConflictReport, save_conflict_report
        WorldBibleService.save_input("p1", "王国建于三百年前。", "王国建于五百年前。")
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[
            _conflict("c1", status="accepted", effective=True),
            _conflict("c2", status="justified", effective=True,
                      resolution_note="主角为特例", verdict="defense_accepted"),
        ]))
        r = generate_corrections("p1")
        assert len(r.corrections) == 2
        # c1 → correct_story / corrected_story.md；c2 有辩解 → settings 侧 canonical_note
        by_id = {e.conflict_id: e for e in r.corrections}
        assert by_id["c1"].action == "correct_story"
        assert by_id["c1"].target_file == "corrected_story.md"
        assert by_id["c2"].action == "canonical_note"

        # 幂等：再生成不回源条目不翻倍
        r2 = generate_corrections("p1")
        assert len(r2.corrections) == 2
        # 三个文件都落盘
        d = cc.ConflictCorrectionService.corrections_dir("p1")
        for fn in ("corrections.json", "corrected_settings.md", "corrected_story.md"):
            assert os.path.exists(os.path.join(d, fn)), fn
        # load 能读回
        loaded = load_corrections("p1")
        assert loaded is not None
        assert len(loaded.corrections) == 2
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
        # 被驳回但仍在辩驳中的冲突：effective=False
        rej_c = ConflictItem(
            conflict_id="c_rej", topic="被驳回", conflict_type="other",
            background_fact="x", story_fact="y", status="open", effective=False,
            defense_rounds=[DefenseRound(round_id="a", role="assistant",
                                         verdict="defense_rejected", content="不成立")],
        )
        save_conflict_report("p1", ConflictReport(project_id="p1", conflicts=[open_c, rej_c]))
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
        assert "未发现需要改正" in r.corrected_settings_md
    finally:
        cd.WORLD_DATA_ROOT, wb.WORLD_DATA_ROOT, cc.WORLD_DATA_ROOT = orig


# ---------------------------------------------------------------- 接口层

def test_corrections_endpoints_generate_and_get(client):
    from app.services.conflict_detector import ConflictItem, DefenseRound
    _seed(client, [_conflict("c1", status="accepted", effective=True)])
    # 未生成前 GET → has_files False
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    assert rv.status_code == 200
    assert rv.get_json()["has_files"] is False

    # POST 生成 → 返回三份文件内容
    rv = client.post("/api/world/p1/conflicts/c1/corrections")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["correction_count"] == 1
    assert set(body["files"].keys()) == {"corrections.json", "corrected_settings.md", "corrected_story.md"}
    assert "correct_story" in body["files"]["corrected_story.md"]["content"]
    assert "王国建于三百年前" in body["files"]["corrected_settings.md"]["content"]

    # GET 现可读到（has_files True）
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    assert rv.get_json()["has_files"] is True
    assert rv.get_json()["correction_count"] == 1


def test_corrections_missing_conflict_404(client):
    rv = client.post("/api/world/p1/conflicts/nope/corrections")
    assert rv.status_code == 404
    rv = client.get("/api/world/p1/conflicts/nope/corrections")
    assert rv.status_code == 404


def test_corrections_download(client):
    from app.services.conflict_detector import ConflictItem
    _seed(client, [_conflict("c1", status="accepted", effective=True)])
    client.post("/api/world/p1/conflicts/c1/corrections")
    rv = client.get("/api/world/p1/conflicts/c1/corrections/corrected_story.md/download")
    assert rv.status_code == 200
    assert b"correct_story" in rv.data
    # 非法文件名
    rv = client.get("/api/world/p1/conflicts/c1/corrections/evil.txt/download")
    assert rv.status_code == 400
    # 未生成文件的下载 → 404
    rv = client.get("/api/world/p1/conflicts/c1/corrections/corrections.json/download")
    assert rv.status_code in (200, 404)


def test_patch_conflict_auto_generates_corrections(client):
    """PATCH 辩驳成功后应自动生成改正文件（corrections_regenerated=true）。"""
    from app.services.conflict_detector import ConflictItem
    # 开局一条 open 冲突，PATCH 标记 accepted 生效
    _seed(client, [_conflict("c1", status="open", effective=False)])
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "accepted"})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["conflict"]["effective"] is True
    assert body.get("corrections_regenerated") is True
    # 改正文件应已生成
    rv = client.get("/api/world/p1/conflicts/c1/corrections")
    assert rv.get_json()["has_files"] is True
