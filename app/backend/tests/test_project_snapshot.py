"""项目快照导出/导入测试。"""

import pytest

from app.models.project import ProjectManager
from app.services import timeline_service as tl
from app.services import world_bible as wb
from app.services import conflict_detector as cd
from app.services.project_snapshot import export_project_snapshot, import_project_snapshot


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(wb, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(tl, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(cd, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False
    yield
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False


def _make_source_project():
    project = ProjectManager.create_project(name="大地巡旅")
    project.simulation_requirement = "推演大陆诸国未来"
    project.ontology = {
        "entity_types": [{"name": "国家", "description": "国家实体"}],
        "edge_types": [{"name": "结盟", "description": "国家间结盟"}],
    }
    project.chunk_size = 800
    project.chunk_overlap = 80
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, "这是提取原文")

    wb.WorldBibleService.save_input(
        project_id=project.project_id,
        background="乌萨斯帝国位于大陆北方。",
        story="阿米娅踏上旅途。",
        chunk_size=800,
        overlap=80,
        metadata={"goal": "推演未来", "files": [{"filename": "a.txt", "source": "background"}]},
        embed=False,
    )

    ev = tl._normalize_event(
        {"summary": "乌萨斯东扩", "time_text": "1090 年", "ev_type": "conflict",
         "thread_name": "乌萨斯线", "dimension": "main"},
        project.project_id, "bg", 0, "llm", 1,
    )
    tl._save_timeline(project.project_id, [ev])
    tl.save_characters(project.project_id, [
        {"name": "阿米娅", "aliases": ["阿米娅·亚莱"], "traits": "温柔", "description": "罗德岛领袖"},
    ])

    report = cd.ConflictReport(
        project_id=project.project_id,
        conflicts=[cd.ConflictItem(
            conflict_id="c1", topic="建国时间", conflict_type="time_conflict",
            background_fact="三百年前", story_fact="五百年前", status="justified",
            resolution_note="寓言层不构成矛盾",
        )],
    )
    cd.save_conflict_report(project.project_id, report)
    return project


def test_export_import_roundtrip():
    src = _make_source_project()
    snapshot = export_project_snapshot(src.project_id)
    assert snapshot["format"] == "mirofish-project-snapshot"
    assert snapshot["project"]["name"] == "大地巡旅"
    assert snapshot["timeline"]["events"]
    assert snapshot["characters"]
    assert snapshot["conflicts"]["conflicts"][0]["status"] == "justified"

    new_project = import_project_snapshot(snapshot)
    assert new_project["project_id"] != src.project_id
    assert new_project["name"] == "大地巡旅"
    assert new_project["simulation_requirement"] == "推演大陆诸国未来"

    # 世界设定库恢复
    bible = wb.WorldBibleService.get_bible(new_project["project_id"])
    assert bible is not None
    assert "乌萨斯帝国" in bible.background_text
    assert "阿米娅踏上旅途" in bible.story_text

    # 时间线/人物恢复
    timeline = tl.load_timeline(new_project["project_id"], None)
    assert len(timeline["events"]) == 1
    assert timeline["events"][0]["thread_name"] == "乌萨斯线"
    chars = tl.load_characters(new_project["project_id"])
    assert chars[0]["aliases"] == ["阿米娅·亚莱"]

    # 冲突恢复
    report = cd.load_conflict_report(new_project["project_id"])
    assert report is not None
    assert report.conflicts[0].status == "justified"
    assert report.conflicts[0].resolution_note == "寓言层不构成矛盾"


def test_import_rejects_bad_snapshot():
    with pytest.raises(ValueError):
        import_project_snapshot({"foo": 1})


def test_imported_world_project_appears_in_history():
    """导入含世界设定库的项目后，/api/simulation/history 应出现其 world 条目。"""
    from app import create_app
    from app.services.project_snapshot import import_project_snapshot

    src = _make_source_project()
    snapshot = export_project_snapshot(src.project_id)
    imported = import_project_snapshot(snapshot)
    new_pid = imported["project_id"]

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        rv = c.get("/api/simulation/history")
        assert rv.status_code == 200
        entries = rv.get_json()["data"]
        # 导入项目应作为世界中项目出现在历史列表（world 条目）
        world_hits = [e for e in entries
                      if e.get("kind") == "world" and e.get("project_id") == new_pid]
        assert world_hits, f"导入项目 {new_pid} 未出现在首页历史列表"
        hit = world_hits[0]
        assert hit["has_world_data"] is True
        # 前端 HistoryDatabase.isWorldProject → 可导航到 WorldSetup
        assert hit["history_type"] == "world"
