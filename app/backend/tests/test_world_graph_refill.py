"""
t8 补边（edge refill）测试：
1. episodes 缓存 save/load + project_id 白名单（路径穿越防护）
2. run_edge_refill 成功（全补，走 add_episode_for_edge_refill 契约）
3. run_edge_refill 降级（全失败跳过，全局配置不被调用方线程改写）
4. 有界重试（2 次后跳过）
5. POST /api/world/<id>/graph/refill_edges 端点（建任务/成功/失败降级）
"""

import time
from types import SimpleNamespace
from unittest import mock

import pytest

from app import create_app
from app.config import Config

# 与 ProjectManager.create_project（proj_ + 12 位小写 hex）一致的真实格式
VALID_PID = "proj_0123456789ab"


@pytest.fixture(autouse=True)
def _isolate_refill_dir(tmp_path, monkeypatch):
    """把 world-graph 缓存根重定向到临时目录。"""
    import app.services.world_graph_refill as wgr
    monkeypatch.setattr(wgr, 'WORLD_GRAPH_ROOT', str(tmp_path / "world-graph"))
    yield


@pytest.fixture()
def refill_client(tmp_path, monkeypatch):
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd
    monkeypatch.setattr(wb, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    monkeypatch.setattr(cd, 'WORLD_DATA_ROOT', str(tmp_path / "world"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 缓存 + 白名单
# ---------------------------------------------------------------------------
def test_episodes_cache_roundtrip():
    import app.services.world_graph_refill as wgr

    assert wgr.save_episodes_cache(VALID_PID, ["ep1", "ep2"]) is True
    assert wgr.load_episodes_cache(VALID_PID) == ["ep1", "ep2"]
    # 不存在返回 None
    assert wgr.load_episodes_cache("proj_ffffffffffff") is None


def test_project_id_whitelist_rejects_traversal():
    import app.services.world_graph_refill as wgr

    for bad in [
        "../etc", "proj_../../evil", "proj_ABC", "proj_ABC123", "",
        "proj1", "proj_0123456789ABCDEF", "proj_0123456789ab/../x",
        "x" * 200, None, 123,
    ]:
        with pytest.raises(ValueError):
            wgr.validate_project_id(bad)
    # 穿越 pid 不落盘、不读盘（save/load 内部吞异常并降级）
    assert wgr.save_episodes_cache("../evil", ["x"]) is False
    assert wgr.load_episodes_cache("../evil") is None


# ---------------------------------------------------------------------------
# run_edge_refill
# ---------------------------------------------------------------------------
class _FakeClient:
    """记录 add_episode_for_edge_refill 调用契约的假客户端。"""

    def __init__(self, fail: bool = False):
        self.calls = []
        self._fail = fail

    def add_episode_for_edge_refill(self, graph_id, data, **kw):
        self.calls.append((data, kw))
        if self._fail:
            raise ConnectionError("boom")
        return f"uuid_{len(self.calls)}"


def _run(client, texts, monkeypatch):
    import app.services.world_graph_refill as wgr
    wgr.save_episodes_cache(VALID_PID, texts)
    with mock.patch.object(wgr, 'get_zep_client', return_value=client):
        from app.models.task import TaskManager
        tm = TaskManager()
        tid = tm.create_task('world_edge_refill')
        result = wgr.run_edge_refill(VALID_PID, "graphX", tm, tid)
    return result


def test_refill_success(monkeypatch):
    client = _FakeClient()
    result = _run(client, ["e1", "e2", "e3"], monkeypatch)
    assert result["total"] == 3 and result["refilled"] == 3 and result["failed"] == 0
    # 每条都携带 always + 小块参数（环境切换在客户端内部完成）
    assert all(
        kw["edge_mode"] == "always" and kw["max_nodes"] == 4
        for _, kw in client.calls
    )
    # 调用方线程从未改写全局配置
    assert Config.GRAPHITI_EDGE_MODE == 'skip'


def test_refill_all_fail_degrades(monkeypatch):
    client = _FakeClient(fail=True)
    result = _run(client, ["e1", "e2"], monkeypatch)
    assert result["total"] == 2 and result["refilled"] == 0 and result["failed"] == 2
    assert Config.GRAPHITI_EDGE_MODE == 'skip'


def test_refill_bounded_retry(monkeypatch):
    calls = {"n": 0}

    class Flaky:
        def add_episode_for_edge_refill(self, **kw):
            calls["n"] += 1
            raise ConnectionError("still down")

    # MAX_EPISODE_RETRIES=2 → 每条最多 3 次调用（1 + 2 重试）
    import app.services.world_graph_refill as wgr
    wgr.save_episodes_cache(VALID_PID, ["e1"])
    with mock.patch.object(wgr, 'get_zep_client', return_value=Flaky()),          mock.patch.object(time, 'sleep'):
        from app.models.task import TaskManager
        tm = TaskManager()
        wgr.run_edge_refill(VALID_PID, "graphX", tm, tm.create_task("x"))
    assert calls["n"] == 3, f"单条最多 1 + 2 次调用，实际 {calls['n']}"


# ---------------------------------------------------------------------------
# /refill_edges 端点
# ---------------------------------------------------------------------------
def _make_project(graph_id=None):
    return SimpleNamespace(project_id=VALID_PID, graph_id=graph_id)


def test_refill_endpoint_no_graph_returns_400(refill_client):
    from app.models.project import ProjectManager
    with mock.patch.object(ProjectManager, 'get_project', return_value=_make_project(None)):
        rv = refill_client.post(f"/api/world/{VALID_PID}/graph/refill_edges")
    assert rv.status_code == 400
    assert "尚未构建图谱" in rv.get_json()["error"]


def test_refill_endpoint_tasks_and_completes(refill_client, monkeypatch):
    import app.services.world_graph_refill as wgr
    from app.models.project import ProjectManager

    wgr.save_episodes_cache(VALID_PID, ["ep1", "ep2"])

    refilled = []

    class OkClient:
        def add_episode_for_edge_refill(self, graph_id, data, **kw):
            refilled.append(data)
            return f"uuid_{len(refilled)}"

    with mock.patch.object(ProjectManager, 'get_project', return_value=_make_project("g123")),          mock.patch.object(wgr, 'get_zep_client', return_value=OkClient()):
        rv = refill_client.post(f"/api/world/{VALID_PID}/graph/refill_edges")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True and body["task_id"]
        task_id = body["task_id"]
        # 等待后台线程完成（轮询任务状态）
        from app.models.task import TaskManager
        tm = TaskManager()
        deadline = time.time() + 10
        while time.time() < deadline:
            task = tm.get_task(task_id)
            if task and task.status.value in ("completed", "failed"):
                break
            time.sleep(0.1)
        task = tm.get_task(task_id)

    assert refilled == ["ep1", "ep2"], "应逐条重放缓存的 episode"
    assert task is not None and task.status.value == "completed"
    assert task.result["total"] == 2 and task.result["refilled"] == 2


def test_refill_endpoint_no_cache_returns_400(refill_client):
    from app.models.project import ProjectManager
    with mock.patch.object(ProjectManager, 'get_project', return_value=_make_project("g123")):
        rv = refill_client.post(f"/api/world/{VALID_PID}/graph/refill_edges")
    assert rv.status_code == 400
    assert "没有可补边" in rv.get_json()["error"]
