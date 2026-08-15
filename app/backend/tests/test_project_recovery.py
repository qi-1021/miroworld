"""项目管理：启动恢复与损坏元数据降级测试。"""

import json
import os

import pytest

from app.models.project import ProjectManager, ProjectStatus


@pytest.fixture()
def projects_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    return tmp_path / "projects"


def test_recover_interrupted_projects_marks_graph_building_failed(projects_root):
    p = ProjectManager.create_project("测试")
    p.status = ProjectStatus.GRAPH_BUILDING
    p.graph_build_task_id = "task-gone-after-restart"
    ProjectManager.save_project(p)

    assert ProjectManager.recover_interrupted_projects() == 1

    reloaded = ProjectManager.get_project(p.project_id)
    assert reloaded.status == ProjectStatus.FAILED
    assert reloaded.graph_build_task_id is None
    assert "服务重启" in reloaded.error


def test_recover_interrupted_projects_skips_other_statuses(projects_root):
    p = ProjectManager.create_project("正常项目")
    p.status = ProjectStatus.GRAPH_COMPLETED
    ProjectManager.save_project(p)

    assert ProjectManager.recover_interrupted_projects() == 0
    assert ProjectManager.get_project(p.project_id).status == ProjectStatus.GRAPH_COMPLETED


def test_get_project_returns_none_for_corrupted_json(projects_root):
    p = ProjectManager.create_project("损坏项目")
    with open(
        os.path.join(ProjectManager._get_project_dir(p.project_id), "project.json"),
        "w", encoding="utf-8",
    ) as f:
        f.write("{ not valid json")
    assert ProjectManager.get_project(p.project_id) is None
    # list_projects 跳过损坏项而不抛异常
    assert ProjectManager.list_projects() == []


def test_list_projects_skips_non_directories(projects_root):
    p = ProjectManager.create_project("项目")
    (projects_root / "not_a_project.json").write_text("{}", encoding="utf-8")
    listed = ProjectManager.list_projects()
    assert [x.project_id for x in listed] == [p.project_id]
