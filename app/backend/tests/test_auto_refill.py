"""
t13 建图完成后自动补边（auto refill）测试。

三条路径：
1. 开启（默认）：build 后台任务完成时自动 start_edge_refill，结果里写入 auto_refill_task。
2. 关闭：Config.GRAPHITI_AUTO_REFILL=False 时不启动补边，auto_refill_task 为 None。
3. 异常：auto_refill 启动抛异常 → 仅 warning，build 仍 COMPLETED，auto_refill_task 为 None。

只改 config.py / api/world.py / 本测试文件；mock 全部建图依赖，不做真实建图。
"""
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from app import create_app
from app.config import Config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    monkeypatch.setattr(wb, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    monkeypatch.setattr(cd, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _drive_build(client, monkeypatch, auto_refill):
    """mock 全部建图依赖并提交一次建图请求，返回 (completed/status, result)。"""
    # 依赖
    import time as _time

    # WorldBibleService.get_bible
    bible = SimpleNamespace(
        background_text="背景设定文本",
        story_text="小说正文文本",
    )
    project_server = SimpleNamespace(
        project_id="proj1",
        name="测试世界",
        graph_id=None,
        status=None,
        chunk_size=1500,
        chunk_overlap=150,
        chunk_count_helper=0,
    )

    # ProjectManager
    with mock.patch("app.services.world_bible.WorldBibleService.get_bible",
                    return_value=bible), \
         mock.patch("app.models.project.ProjectManager.get_project",
                    side_effect=lambda pid: project_server), \
         mock.patch("app.models.project.ProjectManager.save_project", side_effect=lambda p: None), \
         mock.patch("app.models.project.ProjectManager.create_project",
                    return_value=SimpleNamespace(project_id="proj1", name="测试世界")), \
         mock.patch("app.services.ontology_generator.OntologyGenerator") as _ogen, \
         mock.patch("app.services.graph_builder.GraphBuilderService") as _gb, \
         mock.patch("app.services.text_processor.TextProcessor.split_text",
                    return_value=["chunk1", "chunk2"]), \
         mock.patch("app.services.world_graph_refill.start_edge_refill") as _refill, \
         mock.patch("app.services.world_graph_refill.save_episodes_cache", return_value=True):

        _gb.return_value.create_graph.return_value = "g123"
        _gb.return_value.set_ontology.return_value = None
        _gb.return_value.add_text_batches.return_value = ["ep1", "ep2"]
        _gb.return_value._wait_for_episodes.return_value = None
        _gb.return_value.get_graph_data.return_value = {"node_count": 2, "edge_count": 3}

        # 兜底本体
        _ogen.return_value.generate.return_value = {
            "entity_types": [], "edge_types": [], "analysis_summary": "x",
        }

        # Config auto refill
        prev = Config.GRAPHITI_AUTO_REFILL
        Config.GRAPHITI_AUTO_REFILL = auto_refill
        refill_started = {"called": False, "value": None}

        def _fake_start(*a, **kw):
            refill_started["called"] = True
            refill_started["value"] = "refill_task_1"
            return "refill_task_1"

        _refill.side_effect = _fake_start

        try:
            rv = client.post(
                "/api/world/proj1/graph/build",
                json={"goal": "统一大陆"},
            )
            assert rv.status_code == 200, rv.get_json()
            task_id = rv.get_json()["task_id"]

            # 等待后台任务完成——注意 Config.GRAPHITI_AUTO_REFILL 是在后台
            # 线程内读取的，必须在等待期间保持目标值，结束后再还原。
            from app.models.task import TaskManager
            tm = TaskManager()
            deadline = _time.time() + 10
            task = None
            while _time.time() < deadline:
                task = tm.get_task(task_id)
                if task and task.status.value in ("completed", "failed"):
                    break
                _time.sleep(0.1)
            assert task is not None, "build 任务应存在"
            return task, refill_started, _refill
        finally:
            Config.GRAPHITI_AUTO_REFILL = prev


def test_auto_refill_enabled(client, monkeypatch):
    """开启：build 完成时自动启动补边，result.auto_refill_task 有值。"""
    task, started, _refill = _drive_build(client, monkeypatch, auto_refill=True)
    assert task.status.value == "completed"
    assert started["called"] is True, "开启时应调用 start_edge_refill"
    assert task.result["auto_refill_task"] == "refill_task_1"


def test_auto_refill_disabled(client, monkeypatch):
    """关闭：不启动补边，result.auto_refill_task 为 None。"""
    task, started, _refill = _drive_build(client, monkeypatch, auto_refill=False)
    assert task.status.value == "completed"
    assert started["called"] is False, "关闭时不应调用 start_edge_refill"
    assert task.result["auto_refill_task"] is None


def test_auto_refill_start_failure_degrades(client, monkeypatch):
    """启动补边抛异常：仅 warning，build 仍 COMPLETED，auto_refill_task 为 None。"""

    def _boom(*a, **kw):
        raise RuntimeError("refill failed")

    monkeypatch.setattr("app.services.world_graph_refill.start_edge_refill",
                        mock.Mock(side_effect=_boom))
    # 直接驱动（无 start EdgeRefill mock，它现在就是会抛异常的）
    # 复用 _drive_build，但关闭其对 start_edge_refill 的替换
    task, started, _refill = _drive_build_with_failing_refill(client, monkeypatch)
    assert task.status.value == "completed"
    assert task.result["auto_refill_task"] is None


def _drive_build_with_failing_refill(client, monkeypatch):
    import time as _time
    bible = SimpleNamespace(background_text="背景", story_text="正文")
    project_server = SimpleNamespace(project_id="proj1", name="测试世界", graph_id=None)

    with mock.patch("app.services.world_bible.WorldBibleService.get_bible",
                    return_value=bible), \
         mock.patch("app.models.project.ProjectManager.get_project",
                    side_effect=lambda pid: project_server), \
         mock.patch("app.models.project.ProjectManager.save_project", side_effect=lambda p: None), \
         mock.patch("app.models.project.ProjectManager.create_project",
                    return_value=SimpleNamespace(project_id="proj1", name="测试世界")), \
         mock.patch("app.services.ontology_generator.OntologyGenerator") as _ogen, \
         mock.patch("app.services.graph_builder.GraphBuilderService") as _gb, \
         mock.patch("app.services.text_processor.TextProcessor.split_text",
                    return_value=["chunk1"]), \
         mock.patch("app.services.world_graph_refill.save_episodes_cache", return_value=True):

        _ogen.return_value.generate.return_value = {
            "entity_types": [], "edge_types": [], "analysis_summary": "x",
        }
        _gb.return_value.create_graph.return_value = "g123"
        _gb.return_value.set_ontology.return_value = None
        _gb.return_value.add_text_batches.return_value = ["ep1"]
        _gb.return_value._wait_for_episodes.return_value = None
        _gb.return_value.get_graph_data.return_value = {"node_count": 1, "edge_count": 1}

        prev = Config.GRAPHITI_AUTO_REFILL
        Config.GRAPHITI_AUTO_REFILL = True
        try:
            rv = client.post("/api/world/proj1/graph/build", json={"goal": "x"})
            assert rv.status_code == 200, rv.get_json()
            task_id = rv.get_json()["task_id"]

            from app.models.task import TaskManager
            tm = TaskManager()
            deadline = _time.time() + 10
            task = None
            while _time.time() < deadline:
                task = tm.get_task(task_id)
                if task and task.status.value in ("completed", "failed"):
                    break
                _time.sleep(0.1)
            assert task is not None
            return task, None, None
        finally:
            Config.GRAPHITI_AUTO_REFILL = prev
