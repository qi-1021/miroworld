"""
t14 时间线后端测试：
1. project_id 白名单拒绝
2. 分块大小 <=2000
3. 地点/时间/ev_type 归一化（sort 键非空、age 锚 year=null）
4. 启发式降级（LLM 全挂→重试1→启发式；extract_method=heuristic、confidence<0.4；status=partial_failed）
5. 端点 mock：extract→status 轮询、GET timeline、PATCH、future 追加
"""
import time

import pytest

from app import create_app
from app.services import timeline_service as svc


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    """隔离时间线数据根目录。"""
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    # 清空任务表，避免跨用例串扰
    with svc._task_lock:
        svc._tasks.clear()
    yield svc


@pytest.fixture()
def tl_client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------
def test_project_id_whitelist_rejects():
    for bad in ("../evil", "proj_XX", "proj_0123456789ab/../x", "a b"):
        with pytest.raises(ValueError):
            svc.validate_project_id(bad)


def test_project_id_whitelist_accepts():
    assert svc.validate_project_id("proj_0123456789ab") == "proj_0123456789ab"


# ---------------------------------------------------------------------------
# 分块
# ---------------------------------------------------------------------------
def test_chunk_size_bound():
    text = ("泰拉大陆上，罗德岛本舰缓缓驶过维多利亚上空。然而，这个世界正在被源石矿脉"
            "与利益联盟撕裂。\n" * 60)
    chunks = svc.chunk_text(text)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= svc.MAX_CHUNK_CHARS


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def test_normalize_location_dict():
    from app.services import timeline_normalizer as norm
    assert norm.normalize_location("维多利亚") == ("维多利亚", "nation", True)
    assert norm.normalize_location("罗德岛本舰") == ("罗德岛", "facility", True)
    assert norm.normalize_location("罗德里西亚")[2] is False  # 未命中


def test_normalize_time_anchor_absolute():
    from app.services import timeline_normalizer as norm
    a = norm.parse_time_anchor("1085 年")
    assert a["year"] == 1085 and a["sort_lower"] == 10850
    # 年龄锚
    a2 = norm.parse_time_anchor("五岁生日")
    assert a2["age"] == 5 and a2["time_kind"] == "age"


def test_normalize_event_sort_non_null():
    ev = svc._normalize_event(
        {"summary": "成长为少年", "time_text": "少年", "ev_type": "life",
         "location_text": "罗德岛", "confidence": 0.9, "characters": ["阿米娅"]},
        "proj_0123456789ab", "story", 0, "llm", 3,
    )
    assert ev["sort_lower"] is not None
    assert ev["sort_upper"] is not None
    assert ev["location_name"] == "罗德岛"
    assert ev["location_kind"] == "facility"
    # 无显式 time_text 时用 seq 兜底
    ev2 = svc._normalize_event(
        {"summary": "某事件", "time_text": "", "ev_type": "other"},
        "proj_0123456789ab", "story", 0, "llm", 7,
    )
    assert ev2["sort_lower"] == 7.0


# ---------------------------------------------------------------------------
# 启发式降级
# ---------------------------------------------------------------------------
def test_heuristic_fallback_on_llm_down(tl_service, monkeypatch):
    """LLM 全挂：每块重试 1 次后走启发式；状态 partial_failed，事件 confidence<0.4。"""

    class _Down:
        def chat(self, **kw):
            raise ConnectionError("gateway down")

    original = svc._build_llm_client
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _Down())

    def _fake_bible(project_id):
        class B:
            background_text = ""
            story_text = "五岁生日那天，母亲把我抱到床上。\n十五岁那一年，我通过了考核。\n从此我前往乌萨斯，驻扎多年。"
        return B()

    from app.services import world_bible
    monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(_fake_bible))

    task_id = svc.start_extract("proj_0123456789ab", "story")
    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        status = svc.get_status(task_id)
        if status and status["status"] in ("completed", "partial_failed", "failed"):
            break
        time.sleep(0.05)
    assert status is not None
    assert status["status"] == "partial_failed"
    assert status["heuristic"] >= 1
    events = svc.load_timeline("proj_0123456789ab", "story")["events"]
    assert events, "启发式应产出事件"
    for e in events:
        assert e["extract_method"] == "heuristic"
        assert e["confidence"] < 0.4

    monkeypatch.setattr(svc, "_build_llm_client", original)


# ---------------------------------------------------------------------------
# future 追加
# ---------------------------------------------------------------------------
def test_future_appends(tl_service, monkeypatch):
    class _Ok:
        def chat(self, **kw):
            return ('[{"summary":"五年后大陆迎来和平","time_text":"五年后",'
                    '"time_kind":"phase","location_text":"罗德岛","ev_type":"milestone",'
                    '"confidence":0.8,"characters":["阿米娅"]}]')

    monkeypatch.setattr(svc, "_build_llm_client", lambda: _Ok())
    # 先造一条基础事件
    ev_base = svc._normalize_event(
        {"summary": "当前事件", "time_text": "十五岁", "ev_type": "milestone"},
        "proj_0123456789ab", "story", 0, "llm", 1,
    )
    svc._save_timeline("proj_0123456789ab", [ev_base])

    task_id = svc.start_future("proj_0123456789ab", "统一大陆", 5)
    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        status = svc.get_status(task_id)
        if status and status["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
    events = svc.load_timeline("proj_0123456789ab", None)["events"]
    assert len(events) == 2
    future_ev = [e for e in events if e.get("source") == "future"]
    assert future_ev and future_ev[0]["summary"] == "五年后大陆迎来和平"


# ---------------------------------------------------------------------------
# 端点测试（全 mock，不做真实 LLM）
# ---------------------------------------------------------------------------
def _mock_extract_endpoints(client, monkeypatch, llm_factory):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(__import__("tempfile").mkdtemp()))
    with svc._task_lock:
        svc._tasks.clear()

    def _fake_bible(project_id):
        class B:
            background_text = "泰拉大陆拥有三大源石矿脉分布带。1085 年，一位学者退休。"
            story_text = "五岁生日那天，母亲把我抱到床上。十五岁，我通过考核。" * 3
        return B()

    from app.services import world_bible
    monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(_fake_bible))
    monkeypatch.setattr(svc, "_build_llm_client", llm_factory)


def test_endpoint_extract_and_get_and_patch(tl_client, monkeypatch):
    class _Ok:
        def chat(self, **kw):
            return ('[{"summary":"五岁生日","time_text":"五岁生日","time_kind":"age","age":5,'
                    '"location_text":"罗德岛","ev_type":"birth","confidence":0.9,"characters":["阿米娅"]},'
                    '{"summary":"通过考核","time_text":"十五岁","age":15,"location_text":"罗德岛本舰",'
                    '"ev_type":"education","confidence":0.85,"characters":["阿米娅"]}]')

    _mock_extract_endpoints(tl_client, monkeypatch, lambda: _Ok())

    r = tl_client.post("/api/timeline/extract", json={"project_id": "proj_0123456789ab", "source": "story"})
    assert r.status_code == 200
    task_id = r.get_json()["data"]["task_id"]

    # 轮询 status
    status = None
    deadline = time.time() + 10
    while time.time() < deadline:
        s = tl_client.get(f"/api/timeline/status?task_id={task_id}").get_json()
        if s["data"]["status"] in ("completed", "partial_failed", "failed"):
            status = s["data"]
            break
        time.sleep(0.05)
    assert status is not None
    assert status["status"] == "completed"

    # GET 时间线
    r = tl_client.get("/api/timeline/proj_0123456789ab?source=story")
    assert r.status_code == 200
    body = r.get_json()
    events = body["data"]["events"]
    assert body["count"] >= 2
    # 排序升序
    sorts = [e["sort_lower"] for e in events]
    assert sorts == sorted(sorts)

    # PATCH 修正
    ev = events[0]
    rp = tl_client.patch(
        f"/api/timeline/proj_0123456789ab/{ev['id']}",
        json={"summary": "修正事件", "age": 6, "sort_lower": 6},
    )
    assert rp.status_code == 200
    upd = rp.get_json()["data"]
    assert upd["summary"] == "修正事件" and upd["age"] == 6

    # 白名单拒绝：路径穿越被 WSGI/Flask 规范化，只需确认不 200 且合法项目通过
    assert tl_client.get("/api/timeline/proj_0123456789ab?source=story").status_code == 200
    assert tl_client.post("/api/timeline/extract", json={"project_id": "bad", "source": "story"}).status_code == 400


def test_endpoint_future(tl_client, monkeypatch):
    class _Ok:
        def chat(self, **kw):
            return ('[{"summary":"未来和平","time_text":"五年后","ev_type":"milestone",'
                    '"location_text":"罗德岛","confidence":0.8}]')

    _mock_extract_endpoints(tl_client, monkeypatch, lambda: _Ok())

    r = tl_client.post("/api/timeline/future", json={"project_id": "proj_0123456789ab", "goal": "统一", "horizon": 5})
    assert r.status_code == 200
    task_id = r.get_json()["data"]["task_id"]
    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        s = tl_client.get(f"/api/timeline/status?task_id={task_id}").get_json()
        if s["data"]["status"] in ("completed", "failed"):
            status = s["data"]
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
