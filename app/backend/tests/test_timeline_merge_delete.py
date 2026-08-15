"""
t29 事件删除 + 合并 API 测试：

1. delete_event(project_id, event_id) -> bool：存在删除并持久化；不存在 False。
2. merge_events：characters/entities 去重（target 在前）、objections 拼接、
   confidence 取 max、location_name target 空取第一个非空 source、source 删除、target 保留并持久化。
   target/source 任一不存在返回 None。
3. 端点：DELETE /<pid>/<event_id> 成功/404；POST /<pid>/merge 成功/400/404。
"""
import pytest

from app import create_app
from app.services import timeline_service as svc


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(svc, "_TASKS_DIR", str(tmp_path / "world-timeline" / "tasks"))
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False
    yield
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False


def _ev(pid, eid, summary, sort, characters=None, objections=None, confidence=0.5,
        location_name=""):
    ev = svc._normalize_event(
        {"summary": summary, "time_text": "", "ev_type": "milestone", "confidence": confidence,
         "characters": characters or []},
        pid, "story", 0, "llm", 0,
    )
    ev["id"] = eid
    ev["sort_lower"] = float(sort)
    ev["sort_upper"] = float(sort)
    ev["location_name"] = location_name
    if objections:
        ev["objections"] = objections
    return ev


def _seed(svc):
    events = [
        _ev("proj_0123456789ab", "t", "主线事件", 10.0, characters=["阿米娅"], objections=[{"id": "o1"}]),
        _ev("proj_0123456789ab", "s1", "待合并甲", 20.0, characters=["博士"], objections=[{"id": "o2"}], confidence=0.9),
        _ev("proj_0123456789ab", "s2", "待合并乙", 30.0, characters=["阿米娅", "红"], objections=[{"id": "o3"}], location_name="乌萨斯"),
    ]
    svc._save_timeline("proj_0123456789ab", events)
    return events


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------
def test_delete_event_exists():
    events = _seed(svc)
    assert svc.delete_event("proj_0123456789ab", "s1") is True
    remaining = svc.load_timeline("proj_0123456789ab", None)["events"]
    ids = [e["id"] for e in remaining]
    assert "s1" not in ids
    assert "t" in ids and "s2" in ids  # 仅删指定事件


def test_delete_event_missing_returns_false():
    _seed(svc)
    assert svc.delete_event("proj_0123456789ab", "no_such") is False


# ---------------------------------------------------------------------------
# merge_events
# ---------------------------------------------------------------------------
def test_merge_characters_dedup_and_objects():
    _seed(svc)
    merged = svc.merge_events("proj_0123456789ab", "t", ["s1", "s2"])
    assert merged is not None
    # characters 去重（target 在前）：阿米娅、博士、红
    assert merged["characters"] == ["阿米娅", "博士", "红"]
    # objections 拼接
    assert len(merged["objections"]) == 3
    # confidence 取 max（0.9）
    assert merged["confidence"] == 0.9
    # location_name target 空 → 取第一个非空 source（s1 空、s2=乌萨斯）
    assert merged["location_name"] == "乌萨斯"
    # source 删除、target 保留
    remaining = svc.load_timeline("proj_0123456789ab", None)["events"]
    ids = [e["id"] for e in remaining]
    assert "t" in ids and "s1" not in ids and "s2" not in ids


def test_merge_target_location_preserved():
    events = _seed(svc)
    # 给 target 设一个 location_name
    events[0]["location_name"] = "罗德岛"
    svc._save_timeline("proj_0123456789ab", events)
    merged = svc.merge_events("proj_0123456789ab", "t", ["s2"])
    assert merged["location_name"] == "罗德岛"  # target 已有则保留


def test_merge_missing_target_or_source():
    _seed(svc)
    assert svc.merge_events("proj_0123456789ab", "no_target", ["s1"]) is None
    assert svc.merge_events("proj_0123456789ab", "t", ["no_source"]) is None


# ---------------------------------------------------------------------------
# batch_events
# ---------------------------------------------------------------------------
def test_batch_delete_multiple():
    _seed(svc)
    result = svc.batch_events("proj_0123456789ab", "delete", ["t", "s2"])
    assert result["deleted"] == 2
    remaining = svc.load_timeline("proj_0123456789ab", None)["events"]
    ids = [e["id"] for e in remaining]
    assert "t" not in ids and "s2" not in ids and "s1" in ids


def test_batch_update_multiple():
    _seed(svc)
    result = svc.batch_events(
        "proj_0123456789ab", "update", ["t", "s1"],
        patch={"summary": "批量改后", "location_name": "龙门"},
    )
    assert len(result["updated"]) == 2
    remaining = {e["id"]: e for e in svc.load_timeline("proj_0123456789ab", None)["events"]}
    assert remaining["t"]["summary"] == "批量改后"
    assert remaining["t"]["location_name"] == "龙门"
    assert remaining["s1"]["summary"] == "批量改后"
    assert remaining["s2"]["summary"] == "待合并乙"  # 未选中不受影响


def test_batch_invalid_action():
    _seed(svc)
    with pytest.raises(ValueError):
        svc.batch_events("proj_0123456789ab", "rename", ["t"])


def test_batch_endpoint_delete():
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/proj_0123456789ab/batch",
                   json={"action": "delete", "event_ids": ["t", "s1"]})
        assert r.status_code == 200
        assert r.get_json()["data"]["deleted"] == 2
        # 空 event_ids → 400
        r2 = c.post("/api/timeline/proj_0123456789ab/batch",
                    json={"action": "delete", "event_ids": []})
        assert r2.status_code == 400


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
def test_delete_endpoint():
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.delete("/api/timeline/proj_0123456789ab/s1")
        assert r.status_code == 200
        assert r.get_json()["data"]["deleted"] is True
        ids = [e["id"] for e in svc.load_timeline("proj_0123456789ab", None)["events"]]
        assert "s1" not in ids
        # 不存在 → 404
        r2 = c.delete("/api/timeline/proj_0123456789ab/no_such")
        assert r2.status_code == 404


def test_merge_endpoint():
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/proj_0123456789ab/merge",
                   json={"target_id": "t", "source_ids": ["s1", "s2"]})
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["characters"] == ["阿米娅", "博士", "红"]
        # 空 source_ids → 400
        r2 = c.post("/api/timeline/proj_0123456789ab/merge",
                    json={"target_id": "t", "source_ids": []})
        assert r2.status_code == 400
        # 任一缺失 → 404
        r3 = c.post("/api/timeline/proj_0123456789ab/merge",
                    json={"target_id": "t", "source_ids": ["no_such"]})
        # target 已在第一二次合并被删，或 source 缺失 → 404
        assert r3.status_code == 404
