"""
t22 世界图谱构建：每批完成立即存断点 + batch_size 默认8（可覆盖1-16）+ 每批更新进度。

验证（monkeypatch 假建图，不联网/不依赖真实 Graphiti）：
- 每批完成都会调用一次 mark_chunks_done（分批存断点，而非全部完成后一次）
- batch_size 默认 8；body 可覆盖 1-16；超界被夹取
- 每批更新任务进度（message 含批次信息）
"""

import json
import os
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    import app.services.world_graph_refill as wgr
    monkeypatch.setattr(wb, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    monkeypatch.setattr(cd, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    monkeypatch.setattr(wgr, 'WORLD_GRAPH_ROOT', str(tmp_path / "world-graph"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_chunks(n):
    return [f"chunk_{i}" for i in range(n)]


def _drive_build(client, monkeypatch, chunk_count=10, body=None, mark_spy=None):
    """mock 全部建图依赖并提交一次建图请求，等待后台任务完成。返回完成的任务。"""
    import app.services.world_graph_refill as wgr

    bible = SimpleNamespace(
        background_text="背景设定文本",
        story_text="小说正文文本",
    )
    project_server = SimpleNamespace(
        project_id="proj_00aa11bb22cc", name="测试世界", graph_id=None,
        status=None, chunk_size=1500, chunk_overlap=150,
    )
    chunks = _make_chunks(chunk_count)

    with mock.patch("app.services.world_bible.WorldBibleService.get_bible",
                    return_value=bible), \
         mock.patch("app.models.project.ProjectManager.get_project",
                    side_effect=lambda pid: project_server), \
         mock.patch("app.models.project.ProjectManager.save_project", side_effect=lambda p: None), \
         mock.patch("app.models.project.ProjectManager.create_project",
                    return_value=project_server), \
         mock.patch("app.services.ontology_generator.OntologyGenerator"), \
         mock.patch("app.services.ontology_generator.generate_ontology_with_cache",
                    return_value={"entity_types": [], "edge_types": [], "analysis_summary": "x"}), \
         mock.patch("app.services.graph_builder.GraphBuilderService") as _gb, \
         mock.patch("app.services.text_processor.TextProcessor.split_text",
                    return_value=chunks), \
         mock.patch("app.services.world_graph_refill.save_episodes_cache", return_value=True):

        # 假 builder：每批返回与本批块数对应的 uuid，并调用批内进度回调
        def _fake_add_batch(graph_id=None, episodes=None, progress_callback=None,
                            max_workers=1):
            n = len(episodes or [])
            for i in range(n):
                if progress_callback is not None:
                    progress_callback(i + 1, n, f"episode {i + 1}/{n}")
            return [f"u_{i}" for i in range(n)]

        _gb.return_value.create_graph.return_value = "g123"
        _gb.return_value.set_ontology.return_value = None
        _gb.return_value.client.add_episode_batch.side_effect = _fake_add_batch
        _gb.return_value._wait_for_episodes.return_value = None
        _gb.return_value.get_graph_data.return_value = {"node_count": 2, "edge_count": 3}

        # 记录每次 mark_chunks_done 调用（拦截但委托真实行为）
        calls = []

        real_mark = wgr.mark_chunks_done

        def _spy_mark(project_id, chunks_, indices_, uuids_, graph_id=None):
            calls.append({"n_chunks": len(chunks_), "indices": list(indices_)})
            return real_mark(project_id, chunks_, indices_, uuids_, graph_id=graph_id)

        with mock.patch("app.services.world_graph_refill.mark_chunks_done",
                        side_effect=_spy_mark):
            params = dict(body or {})
            rv = client.post("/api/world/proj_00aa11bb22cc/graph/build", json=params)
            assert rv.status_code == 200, rv.get_json()
            task_id = rv.get_json()["task_id"]

            from app.models.task import TaskManager
            tm = TaskManager()
            deadline = time.time() + 15
            task = None
            while time.time() < deadline:
                task = tm.get_task(task_id)
                if task and task.status.value in ("completed", "failed"):
                    break
                time.sleep(0.05)
            assert task is not None, "build 任务应存在"
            assert task.status.value == "completed", task.error or task.message

    return task, calls


def _expected_batches(n_chunks, batch_size):
    return (n_chunks + batch_size - 1) // batch_size


# ---------------------------------------------------------------------------
# 1. 每批完成即 mark_chunks_done
# ---------------------------------------------------------------------------

def test_mark_chunks_done_called_per_batch_default(client, monkeypatch):
    """默认 batch_size=4，10 块 → 3 批 → mark_chunks_done 调用 3 次。"""
    task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={})
    assert len(calls) == _expected_batches(10, 4) == 3, calls
    # 分 4/4/2
    assert calls[0]["n_chunks"] == 4
    assert calls[1]["n_chunks"] == 4
    assert calls[2]["n_chunks"] == 2


def test_mark_chunks_done_per_batch_override(client, monkeypatch):
    """body batch_size=4 → 10 块 → 3 批。"""
    task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 4})
    assert len(calls) == _expected_batches(10, 4) == 3, calls


def test_mark_chunks_done_single_batch_when_in_one(client, monkeypatch):
    """body batch_size=16 → 10 块 → 1 批（> 块数）。"""
    task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 16})
    assert len(calls) == 1


def test_batch_size_clamped_above(client, monkeypatch):
    """body batch_size=99 → 夹到 16 → 10 块 1 批。"""
    task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 99})
    assert len(calls) == 1


def test_batch_size_clamped_below(client, monkeypatch):
    """body batch_size=0 → 夹到 1 → 每块一批，10 批。"""
    task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 0})
    assert len(calls) == 10
    assert all(c["n_chunks"] == 1 for c in calls)


# ---------------------------------------------------------------------------
# 2. 断点文件渐进写入（每批落盘）
# ---------------------------------------------------------------------------

def test_checkpoint_file_records_all_chunks(client, monkeypatch):
    """建图完成后 build-progress.json 已包含全部 chunk（done）。"""
    import app.services.world_graph_refill as wgr
    task, _calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 4})
    build_progress_path = wgr.build_progress_path("proj_00aa11bb22cc")
    assert os.path.exists(build_progress_path)
    with open(build_progress_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["chunks"]) == 10
    assert all(c["status"] == "done" for c in data["chunks"])
    assert task.status.value == "completed"


# ---------------------------------------------------------------------------
# 3. 每批更新进度
# ---------------------------------------------------------------------------

def test_task_progress_updated_per_batch(client, monkeypatch):
    """任务运行中会按批更新进度（message 含「第 X/Y 批」批次信息）。"""
    from app.models.task import TaskManager

    messages = []
    _orig = TaskManager.update_task  # 保存真实方法，避免 spy 内递归调用补丁

    def _spy_update(self2, task_id=None, status=None, progress=None, message=None,
                    result=None, error=None, progress_detail=None):
        if message:
            messages.append(str(message))
        return _orig(self2, task_id, status=status, progress=progress, message=message,
                     result=result, error=error, progress_detail=progress_detail)

    with mock.patch.object(TaskManager, "update_task", _spy_update):
        task, calls = _drive_build(client, monkeypatch, chunk_count=10, body={"batch_size": 3})

    # 3 块一批，10 块 → 4 批 → 有 [消息] 提到「第 1/4 批」… 以及批次完成消息
    batch_msgs = [m for m in messages if "批" in m]
    assert batch_msgs, f"应有批次进度消息，实际 {messages}"
    assert any("1/4" in m for m in batch_msgs), batch_msgs
    assert any("4/4" in m for m in batch_msgs), batch_msgs
    assert len(calls) == _expected_batches(10, 3) == 4
    assert task.status.value == "completed"
