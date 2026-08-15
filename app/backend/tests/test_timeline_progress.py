"""
t22 后台任务进度增强测试：

验证 timeline_service 任务状态 dict 新增字段（stage/steps/progress/started_at/elapsed/error）
与逐阶段打点正确性：
1. extract 任务状态含 stage/progress/steps/elapsed
2. extract failed 状态含 error
3. future/extract 的 stage 打点流转
4. fork 完成状态含 branch_id/event_count
5. fork failed 状态含 error
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
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 0.05)  # 测试加速：跳过批2等待窗口
    yield svc


class _OkLLM:
    """返回一个事件的 JSON 数组。"""
    def chat(self, **kw):
        return ('[{"summary":"五岁生日","time_text":"五岁生日","time_kind":"age","age":5,'
                '"location_text":"罗德岛","ev_type":"birth","confidence":0.9,"characters":["阿米娅"]},'
                '{"summary":"通过考核","time_text":"十五岁","age":15,"ev_type":"education",'
                '"confidence":0.85}]')


class _DownLLM:
    def chat(self, **kw):
        raise ConnectionError("gateway down")


def _seed(service, n=2):
    events = []
    for i in range(n):
        ev = svc._normalize_event(
            {"summary": f"事件{i}", "time_text": "", "ev_type": "milestone"},
            "proj_0123456789ab", "story", 0, "llm", i,
        )
        ev["sort_lower"] = float(i); ev["sort_upper"] = float(i)
        events.append(ev)
    svc._save_timeline("proj_0123456789ab", events)
    return events


def _wait(service, task_id, deadline=10):
    s = None
    end = time.time() + deadline
    while time.time() < end:
        s = service.get_status(task_id)
        if s and s.get("status") in ("completed", "partial_failed", "failed"):
            return s
        time.sleep(0.05)
    return s


# ---------------------------------------------------------------------------
# extract：stage/progress/steps/elapsed
# ---------------------------------------------------------------------------
def test_extract_task_has_progress_fields(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _OkLLM())

    def _fake_bible(pid):
        class B:
            background_text = ""
            story_text = "五岁生日那天，母亲把我抱到床上。\n十五岁，我通过考核。" * 30
        return B()
    from app.services import world_bible
    monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(_fake_bible))

    task_id = svc.start_extract("proj_0123456789ab", "story")
    status = _wait(tl_service, task_id)
    assert status is not None
    assert status["status"] == "completed"
    # 新字段全部存在
    for f in ("stage", "steps", "progress", "started_at", "elapsed"):
        assert f in status, f"缺少字段 {f}"
    assert status["progress"] == 100
    assert isinstance(status["steps"], list) and status["steps"]
    # steps 每条带 [HH:MM:SS] 时间戳前缀
    assert status["steps"][0].startswith("[")
    # elapsed 非负
    assert status["elapsed"] >= 0
    # started_at 是 ISO 串（含 T）
    assert "T" in status["started_at"]
    # stage 是完成阶段
    assert status["stage"]


def test_extract_task_steps_capture_chunk_and_failures(tl_service, monkeypatch):
    """LLM 失败时 steps 记录重试/降级，最终 failed/partial_failed 含 error/steps。"""
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _DownLLM())

    def _fake_bible(pid):
        class B:
            background_text = ""
            story_text = "五岁生日那天，母亲把我抱到床上。十五岁，我通过考核。"
        return B()
    from app.services import world_bible
    monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(_fake_bible))

    task_id = svc.start_extract("proj_0123456789ab", "story")
    status = _wait(tl_service, task_id)
    assert status is not None
    assert status["status"] == "partial_failed"  # 全启发式 → partial_failed
    # steps 记录了 重试/降级
    joined = "\n".join(status["steps"])
    assert "重试" in joined or "降级" in joined
    assert status["progress"] == 100
    # partial_failed 不算 failed，error 可为空
    assert "error" in status


# ---------------------------------------------------------------------------
# future：stage 流转
# ---------------------------------------------------------------------------
def test_future_task_stages(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _OkLLM())
    _seed(tl_service)
    task_id = svc.start_future("proj_0123456789ab", "统一大陆", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    assert "steps" in status and status["steps"]
    # 应包含构建上下文/调用模型/解析/写入等阶段日志
    joined = "\n".join(status["steps"])
    for marker in ("构建", "调用", "解析", "写入", "追加"):
        assert marker in joined, f"steps 缺少阶段 {marker}"
    assert status["progress"] == 100


def test_future_failed_contains_error(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _DownLLM())
    _seed(tl_service)
    task_id = svc.start_future("proj_0123456789ab", "x", 3)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "failed"
    assert status["error"], "failed 状态应含 error"
    assert status["stage"] == "失败"


# ---------------------------------------------------------------------------
# fork：branch_id / event_count + failed error
# ---------------------------------------------------------------------------
def test_fork_completed_has_branch_meta(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _OkLLM())
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "假设北上", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    assert status.get("branch_id"), "fork 完成应含 branch_id"
    assert status.get("event_count", 0) >= 1, "fork 完成应含 event_count"
    assert "steps" in status and status["steps"]


def test_fork_failed_contains_error(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _DownLLM())
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "x", 3)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "failed"
    assert status["error"]
    assert status["stage"] == "失败"



def test_create_app_status_route_transparent(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _OkLLM())
    _seed(tl_service)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        task_id = svc.start_fork("proj_0123456789ab", _seed(tl_service)[0]["id"], "x", 3)
        status = _wait(tl_service, task_id)
        r = c.get(f"/api/timeline/status?task_id={task_id}")
        assert r.status_code == 200
        data = r.get_json()["data"]
        for f in ("stage", "steps", "progress", "started_at", "elapsed", "branch_id", "event_count", "error"):
            assert f in data, f"/status 未透传字段 {f}"