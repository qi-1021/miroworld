"""
t28 分支对比 API 测试：

种子时间线：
- 分支点事件 bp（sort=10）
- before 事件（sort=5，须在 before 分类）
- base_after 事件：baseA（sort=20，与分支事件相似 → changed）、baseB（sort=30，无分支配对 → base_only）
- 分支事件（kind='branch'，branch_id=B1）：branchX（sort=11，与 baseA 高相似 → changed）、branchY（sort=12，低相似 → branch_new）

验证 compare_branch 返回 before / changed / base_only / branch_new 分类正确；
API GET /branch/compare?branch_id= → 成功、缺 branch_id 400、分支不存在 404。
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


def _ev(pid, eid, summary, sort, branch=False, branch_id="b1", bp="bp_id"):
    ev = svc._normalize_event(
        {"summary": summary, "time_text": "", "ev_type": "milestone"},
        pid, "story", 0, "llm", 0,
    )
    ev["id"] = eid
    ev["sort_lower"] = float(sort)
    ev["sort_upper"] = float(sort)
    if branch:
        ev["kind"] = "branch"
        ev["branch_id"] = branch_id
        ev["branch_point"] = bp
    return ev


def _seed(service):
    events = [
        _ev("proj_0123456789ab", "bp_id", "决裂发生的那一天", 10.0),
        _ev("proj_0123456789ab", "before1", "早年师从泰拉学者", 5.0),
        _ev("proj_0123456789ab", "baseA", "前往乌萨斯驻扎多年", 20.0),
        _ev("proj_0123456789ab", "baseB", "返回罗德岛述职", 30.0),
        _ev("proj_0123456789ab", "branchX", "前往乌萨斯驻扎多年", 11.0, branch=True),
        _ev("proj_0123456789ab", "branchY", "转向拉特兰破局", 12.0, branch=True),
    ]
    svc._save_timeline("proj_0123456789ab", events)
    return events


def test_compare_classifications():
    _seed(svc)
    result = svc.compare_branch("proj_0123456789ab", "b1")
    assert result is not None
    kinds = {e["kind"]: e for e in result["entries"]}
    # before：分叉点及之前的主线事件
    assert kinds["before"]["event"]["id"] in ("bp_id", "before1")
    # changed：分支事件与主线高相似配对
    change = [e for e in result["entries"] if e["kind"] == "changed"]
    assert any(e["event"]["id"] == "branchX" and e["base_event"]["id"] == "baseA" for e in change),         "branchX 与 baseA 高相似应判为 changed"
    # branch_new：低相似分支事件未配对
    assert any(e["kind"] == "branch_new" and e["event"]["id"] == "branchY" for e in result["entries"])
    # base_only：主线未配对事件
    assert any(e["kind"] == "base_only" and e["event"]["id"] == "baseB" for e in result["entries"])
    # 元数据
    assert result["branch_point_id"] == "bp_id"
    assert "决裂" in result["branch_point_summary"]


def test_compare_low_similarity_not_paired():
    """低相似分支事件不与主线配对 → branch_new。"""
    _seed(svc)
    result = svc.compare_branch("proj_0123456789ab", "b1")
    changed = [e for e in result["entries"] if e["kind"] == "changed"]
    # branchY（"转向拉特兰破局"）与任何主线都 <0.55，不应出现在 changed
    for c in changed:
        assert c["event"]["id"] != "branchY"


def test_compare_branch_missing_returns_none():
    _seed(svc)
    assert svc.compare_branch("proj_0123456789ab", "no_such_branch") is None


def test_compare_api_success():
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/timeline/proj_0123456789ab/branch/compare?branch_id=b1")
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"] is True
        assert body["count"] >= 4
        assert body["data"]["branch_id"] == "b1"


def test_compare_api_missing_branch_id_400():
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/timeline/proj_0123456789ab/branch/compare")
        assert r.status_code == 400
        assert "branch_id" in r.get_json()["error"]


def test_compare_api_branch_not_found_404():
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/timeline/proj_0123456789ab/branch/compare?branch_id=nope")
        assert r.status_code == 404
