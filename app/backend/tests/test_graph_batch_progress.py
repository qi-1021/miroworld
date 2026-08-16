"""t27 图谱建图批处理进度测试：add_episode_batch 批内逐条进度 + max_workers。

覆盖：
- Graphiti 实现的 add_episode_batch：progress_callback 逐条触发；(done,total,msg) 递增
- max_workers=1（默认）串行、max_workers=2 并发，两条路径都处理完所有 episode 且回调逐条触发
- world.py build 默认 batch_size=4；body max_workers 1-3 可覆盖并透传给 client
（monkeypatch graphiti 的 add_episode，不打真实图库/LLM）
"""

import threading
import time
from unittest import mock

import pytest

from app import create_app


def _make_client(add_episode_side_effect):
    """构造一个 GraphitiClient，mock 掉 add_episode / _ensure_initialized。"""
    from app.services.zep_graphiti_impl import GraphitiClient
    c = GraphitiClient(
        neo4j_uri="bolt://localhost:1",
        neo4j_user="u", neo4j_password="p",
    )
    c._ensure_initialized = lambda: None
    c._initialized = True
    c.add_episode = add_episode_side_effect
    return c


# ---------------------------------------------------------------------------
# Graphiti add_episode_batch：progress_callback 逐条 + max_workers
# ---------------------------------------------------------------------------

def test_add_episode_batch_progress_callback_per_episode():
    episodes = [{"data": f"chunk{i}", "type": "text"} for i in range(5)]
    added = []
    lock = threading.Lock()

    def _fake_add_episode(graph_id=None, data="", episode_type="text", **kw):
        time.sleep(0.001)
        with lock:
            added.append(data)
        return f"uuid_{len(added)}"

    client = _make_client(_fake_add_episode)
    cb = []
    uuids = client.add_episode_batch(
        "g1", episodes, progress_callback=lambda d, t, m: cb.append((d, t, m)),
        max_workers=1,
    )
    # 5 条全部成功
    assert len(uuids) == 5
    assert len(added) == 5
    # 进度回调逐条触发，done 递增到 total=5
    assert cb[-1] == (5, 5, "episode 5/5")
    assert [d for d, t, m in cb] == [1, 2, 3, 4, 5]
    assert all(t == 5 for d, t, m in cb)


def test_add_episode_batch_max_workers_parallel_processes_all():
    episodes = [{"data": f"c{i}", "type": "text"} for i in range(6)]
    peak = 0
    cur = 0
    lock = threading.Lock()

    def _fake_add_episode(graph_id=None, data="", episode_type="text", **kw):
        nonlocal peak, cur
        with lock:
            cur += 1
            peak = max(peak, cur)
        try:
            time.sleep(0.05)  # 允许并发窗口展开
        finally:
            with lock:
                cur -= 1
        return f"u_{len(data)}"

    client = _make_client(_fake_add_episode)
    cb = []
    # 并发 2：应确实并行（peak 到达过 ≥2）
    uuids = client.add_episode_batch(
        "g1", episodes, progress_callback=lambda d, t, m: cb.append((d, t, m)),
        max_workers=2,
    )
    assert len(uuids) == 6
    assert cb[-1] == (6, 6, "episode 6/6")
    assert peak >= 2, f"max_workers=2 应出现并发执行，但 peak={peak}"


def test_add_episode_batch_max_workers1_is_serial():
    episodes = [{"data": f"c{i}", "type": "text"} for i in range(4)]
    lock = threading.Lock()
    peak = 0
    cur = 0

    def _fake_add_episode(graph_id=None, data="", episode_type="text", **kw):
        nonlocal peak, cur
        time.sleep(0.005)
        with lock:
            cur += 1
            peak = max(peak, cur)
            time.sleep(0.005)
            cur -= 1
        return "u"

    client = _make_client(_fake_add_episode)
    client.add_episode_batch("g1", episodes, max_workers=1)
    assert peak == 1, f"max_workers=1 应完全串行，但 peak={peak}"


def test_add_episode_batch_empty_no_crash():
    client = _make_client(lambda *a, **k: "u")
    cb = []
    uuids = client.add_episode_batch("g1", [], progress_callback=lambda d, t, m: cb.append((d, t, m)))
    assert uuids == []
    # 空批次也应通知一次 (0,0)
    assert cb == [(0, 0, "空批次，无需处理")]


def test_add_episode_batch_retry_on_failure():
    """首次失败自动重试一次；第二次成功返回 uuid，不再进 failed。"""
    attempts = {"n": 0}

    def _fake_add_episode(graph_id=None, data="", episode_type="text", **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("gateway 抖动")
        return "uuid_ok"

    client = _make_client(_fake_add_episode)
    uuids = client.add_episode_batch("g1", [{"data": "x", "type": "text"}], max_workers=1)
    assert uuids == ["uuid_ok"]


# ---------------------------------------------------------------------------
# world.py：默认 batch_size=4 + max_workers 透传
# ---------------------------------------------------------------------------

def _setup_world(client, monkeypatch, chunk_count, body):
    """mock 建图依赖，提交请求，捕获 client.add_episode_batch 的 kwargs。"""
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    import app.services.world_graph_refill as wgr
    from app.models.task import TaskManager

    from types import SimpleNamespace
    bible = SimpleNamespace(background_text="背景文本", story_text="小说正文文本" * 30)
    chunks = [f"chunk_{i}" for i in range(chunk_count)]
    proj = SimpleNamespace(project_id="proj_00aa11bb22cc", name="测试世界",
                           graph_id=None, status=None,
                           chunk_size=1500, chunk_overlap=150)

    kwargs_calls = []
    captured_max_workers = []

    with mock.patch("app.services.world_bible.WorldBibleService.get_bible",
                    return_value=bible), \
         mock.patch("app.models.project.ProjectManager.get_project",
                    side_effect=lambda pid: proj), \
         mock.patch("app.models.project.ProjectManager.save_project", side_effect=lambda p: None), \
         mock.patch("app.models.project.ProjectManager.create_project", return_value=proj), \
         mock.patch("app.services.ontology_generator.OntologyGenerator"), \
         mock.patch("app.services.ontology_generator.generate_ontology_with_cache",
                    return_value={"entity_types": [], "edge_types": [], "analysis_summary": "x"}), \
         mock.patch("app.services.graph_builder.GraphBuilderService") as _gb, \
         mock.patch("app.services.text_processor.TextProcessor.split_text", return_value=chunks), \
         mock.patch("app.services.world_graph_refill.save_episodes_cache", return_value=True):

        def _fake_batch(graph_id=None, episodes=None, progress_callback=None, max_workers=1):
            kwargs_calls.append({"episodes": episodes, "max_workers": max_workers,
                                 "has_cb": progress_callback is not None})
            captured_max_workers.append(max_workers)
            return [f"u_{i}" for i in range(len(episodes or []))]

        _gb.return_value.create_graph.return_value = "g123"
        _gb.return_value.set_ontology.return_value = None
        _gb.return_value.client.add_episode_batch.side_effect = _fake_batch
        _gb.return_value._wait_for_episodes.return_value = None
        _gb.return_value.get_graph_data.return_value = {"node_count": 2, "edge_count": 3}

        rv = client.post("/api/world/proj_00aa11bb22cc/graph/build", json=body)
        assert rv.status_code == 200, rv.get_json()
        task_id = rv.get_json()["task_id"]
        tm = TaskManager()
        deadline = time.time() + 15
        while time.time() < deadline:
            task = tm.get_task(task_id)
            if task and task.status.value in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert task is not None and task.status.value == "completed", task.error if task else "?"

    return kwargs_calls, captured_max_workers


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    import app.services.world_graph_refill as wgr
    monkeypatch.setattr(wb, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(cd, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(wgr, "WORLD_GRAPH_ROOT", str(tmp_path / "world-graph"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_world_default_batch_size_4(client, monkeypatch):
    """默认 batch_size=4：10 块 → 3 批 add_episode_batch 调用。"""
    kwargs_calls, _ = _setup_world(client, monkeypatch, 10, {})
    assert len(kwargs_calls) == 3, kwargs_calls
    sizes = [len(c["episodes"]) for c in kwargs_calls]
    assert sizes == [4, 4, 2]


def test_world_default_max_workers_1(client, monkeypatch):
    """默认 max_workers=1 透传给 client，且逐条进度回调已挂上。"""
    kwargs_calls, mw = _setup_world(client, monkeypatch, 5, {})
    assert mw and mw[0] == 1
    assert kwargs_calls[0]["has_cb"] is True


def test_world_max_workers_override(client, monkeypatch):
    """body max_workers=3 透传给 client。"""
    kwargs_calls, mw = _setup_world(client, monkeypatch, 6, {"max_workers": 3})
    assert mw and mw[0] == 3
