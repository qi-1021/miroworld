"""
t19 时间点分叉推演（fork）+ 事件异议（objection）测试：

1. fork 后台任务：生成 branch 事件（kind='branch'、branch_id、branch_point），
   sort 严格大于分叉点。
2. fork 失败（LLM 全挂 / 分叉点不存在）→ status=failed。
3. objection：往事件 dict 追加 objections 数组并持久化。
4. 端点：POST /api/timeline/fork（静态路由不被吞）、POST /objection。
"""
import time

import pytest

from app import create_app
from app.services import timeline_service as svc


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _OkLLM())
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 0.05)  # 测试加速：跳过批2等待窗口
    yield svc


@pytest.fixture()
def tl_client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class _OkLLM:
    def chat(self, **kw):
        return ('[{"summary":"分支：罗德岛转而北上","time_text":"五年后",'
                '"time_kind":"phase","location_text":"乌萨斯","ev_type":"task",'
                '"confidence":0.8,"characters":["阿米娅"]},'
                '{"summary":"分支：拉特兰破局","time_text":"七年后","time_kind":"phase",'
                '"ev_type":"milestone","confidence":0.7}]')


class _DownLLM:
    def chat(self, **kw):
        raise ConnectionError("gateway down")


def _seed(service, n=3):
    events = []
    for i in range(n):
        ev = svc._normalize_event(
            {"summary": f"事件{i}", "time_text": str(i + 1) if i < n else "", "ev_type": "milestone"},
            "proj_0123456789ab", "story", 0, "llm", i,
        )
        ev["sort_lower"] = float(i)
        ev["sort_upper"] = float(i)
        events.append(ev)
    svc._save_timeline("proj_0123456789ab", events)
    return events


def _wait(service, task_id, deadline=10):
    s = None
    end = time.time() + deadline
    while time.time() < end:
        s = service.get_status(task_id)
        if s and s.get("status") in ("completed", "failed"):
            return s
        time.sleep(0.05)
    return s


# ---------------------------------------------------------------------------
# fork 服务
# ---------------------------------------------------------------------------
def test_fork_creates_branch_events(tl_service):
    events = _seed(tl_service)
    bp = events[1]  # 事件1（sort=1）
    task_id = svc.start_fork("proj_0123456789ab", bp["id"], "假设罗德岛北上", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    all_ev = svc.load_timeline("proj_0123456789ab", None)["events"]
    branch_ev = [e for e in all_ev if e.get("kind") == "branch"]
    assert len(branch_ev) >= 1
    # 每个分支事件：branch_point=分叉点、有 branch_id、sort 严格大于分叉点
    bp_sort = bp["sort_lower"]
    for e in branch_ev:
        assert e["branch_point"] == bp["id"]
        assert e.get("branch_id")
        assert e["sort_lower"] > bp_sort
        assert e["sort_upper"] >= e["sort_lower"]


def test_fork_sorts_strictly_after_branch_point(tl_service):
    events = _seed(tl_service)
    bp = events[0]
    svc.start_fork("proj_0123456789ab", bp["id"], "x", 3)
    # 等完成
    tasks = list(svc._tasks.keys())
    status = None
    for t in tasks:
        s = _wait(tl_service, t)
        if s and s["status"] == "completed":
            status = s
    assert status is not None
    branch_ev = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
                 if e.get("kind") == "branch"]
    assert all(e["sort_lower"] > bp["sort_lower"] for e in branch_ev)


def test_fork_missing_branch_point_fails(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _OkLLM())
    _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", "no_such_evt", "x", 3)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "failed"


def test_fork_rejects_missing_event_id(tl_service):
    with pytest.raises(ValueError):
        svc.start_fork("proj_0123456789ab", "", "x", 3)


def test_fork_llm_down_fails_tolerably(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _DownLLM())
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "x", 3)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "failed"


# ---------------------------------------------------------------------------
# objection 服务
# ---------------------------------------------------------------------------
def test_add_objection_appends(tl_service):
    events = _seed(tl_service)
    ev = events[0]
    updated = svc.add_objection("proj_0123456789ab", ev["id"], "time",
                                "时间点疑似有误，应为五年后", "建议改为五年后")
    assert updated is not None
    objs = updated.get("objections", [])
    assert len(objs) == 1
    assert objs[0]["category"] == "time"
    assert "五年后" in objs[0]["reason"]
    assert "五年后" in objs[0]["suggestion"]
    # 再次提交 → 数组累积
    updated2 = svc.add_objection("proj_0123456789ab", ev["id"], "location", "b")
    assert len(updated2["objections"]) == 2
    # 持久化
    reloaded = svc.load_timeline("proj_0123456789ab", None)["events"]
    re_ev = next(e for e in reloaded if e["id"] == ev["id"])
    assert len(re_ev["objections"]) == 2


def test_add_objection_rejects_invalid_category(tl_service):
    events = _seed(tl_service)
    with pytest.raises(ValueError):
        svc.add_objection("proj_0123456789ab", events[0]["id"], "bad_category", "理由")


def test_add_objection_rejects_empty_reason(tl_service):
    events = _seed(tl_service)
    with pytest.raises(ValueError):
        svc.add_objection("proj_0123456789ab", events[0]["id"], "time", "  ")


def test_add_objection_missing_event_returns_none(tl_service):
    assert svc.add_objection("proj_0123456789ab", "no_such", "other", "b") is None


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
def test_endpoint_fork_not_swallowed(tl_client, monkeypatch):
    # /fork 是静态路由，不应被 /<project_id> 动态路由吞掉
    r = tl_client.post("/api/timeline/fork", json={})
    assert r.status_code == 400  # 缺 event_id/project_id → 400，而非动态路由 404/405


def test_endpoint_fork_returns_task(tl_client, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(__import__("tempfile").mkdtemp()))
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _OkLLM())
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    # seed 一条事件
    _seed(svc)
    ev_id = svc.load_timeline("proj_0123456789ab", None)["events"][0]["id"]
    r = tl_client.post("/api/timeline/fork",
                       json={"project_id": "proj_0123456789ab", "event_id": ev_id, "goal": "x"})
    assert r.status_code == 200
    assert r.get_json()["data"]["task_id"]


def test_endpoint_objection(tl_client, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(__import__("tempfile").mkdtemp()))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    _seed(svc)
    ev_id = svc.load_timeline("proj_0123456789ab", None)["events"][0]["id"]
    r = tl_client.post(
        f"/api/timeline/proj_0123456789ab/{ev_id}/objection",
        json={"category": "location", "reason": "地点应为罗德岛", "suggestion": "改为罗德岛"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert len(body["data"]["objections"]) == 1
    # 未找到事件 → 404
    r2 = tl_client.post("/api/timeline/proj_0123456789ab/no_such/objection", json={"category": "other", "reason": "b"})
    assert r2.status_code == 404
    # 非法分类 → 400
    r3 = tl_client.post(f"/api/timeline/proj_0123456789ab/{ev_id}/objection", json={"category": "bad", "reason": "b"})
    assert r3.status_code == 400
