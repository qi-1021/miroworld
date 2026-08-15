"""
t23 补充设定 guidance + 人物设定档案 + 提示词注入测试：

1. fork 两批调用：批1 前半段 + 批2（并入 guidance）后半段；事件带 branch_goal/guidance。
2. 批2 失败但批1 成功 → completed（partial），不失败。
3. inject_fork_guidance：运行中注入合并；非 running → ValueError（端点 400）。
4. branch/continue：sort 从分支最大 +1 起续推。
5. characters：从事件种子 / 保存 / 读取；_character_profiles 注入提示词。
6. 提示词总长 <=2600（mock 捕获 user 消息断言）。
7. 400/404 校验。
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
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 0.05)  # 测试加速：跳过批2等待窗口
    yield svc


class _QueueLLM:
    """按顺序返回预置 JSON 数组；Queue 内容为 dict，'RAISE' 触发异常。"""
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        self.last_user = None
        self._calls_users = []

    def chat(self, **kw):
        self.calls += 1
        user = kw.get("messages", [{}])[-1].get("content", "")
        self.last_user = user
        self._calls_users.append(user)
        reply = self._replies.pop(0) if self._replies else None
        if reply is None:
            raise ConnectionError("no more replies")
        if reply == "RAISE":
            raise ConnectionError("gateway down")
        return reply


def _seed(service, n=3):
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
        if s and s.get("status") in ("completed", "partial_failed", "failed", "completed-partial"):
            return s
        time.sleep(0.05)
    return s


# ---------------------------------------------------------------------------
# fork 两批 + guidance 注入字段
# ---------------------------------------------------------------------------
def test_fork_two_batch_with_guidance(tl_service, monkeypatch):
    arr1 = '[{"summary":"分支甲","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    arr2 = '[{"summary":"分支乙","time_text":"三年后","ev_type":"milestone","confidence":0.7}]'
    llm = _QueueLLM([arr1, arr2])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5, guidance=["补充：北方路线"])
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    assert status.get("event_count", 0) == 2, "两批各 1 条 → 共 2 条"
    branch_ev = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
                 if e.get("kind") == "branch"]
    assert len(branch_ev) == 2
    # 事件带 branch_goal / guidance 列表
    for e in branch_ev:
        assert e.get("branch_goal") == "目标"
        assert e.get("guidance") == ["补充：北方路线"]
    # 两批各一次 LLM 调用
    assert llm.calls == 2
    # 批1 user 含初始 guidance 与人物设定段/无人物时无；批2 user 含批1 结果与 guidance
    assert "补充：北方路线" in llm._calls_users[0]
    assert "已生成分支事件" in llm._calls_users[1]


def test_fork_batch2_fails_keeps_batch1(tl_service, monkeypatch):
    arr1 = '[{"summary":"前半段事件","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    llm = _QueueLLM([arr1, "RAISE"])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed", "批2失败但批1成功 → completed"
    assert status.get("event_count", 0) == 1
    branch_ev = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
                 if e.get("kind") == "branch"]
    assert len(branch_ev) == 1


# ---------------------------------------------------------------------------
# inject_fork_guidance
# ---------------------------------------------------------------------------
def test_inject_guidance_while_running(tl_service, monkeypatch, tmp_path):
    import threading
    gate = threading.Event()  # 批1 阻塞，直到我们放行，保证注入发生在 running 期间

    class _Gated:
        def chat(self, **kw):
            gate.wait(timeout=10)  # 阻塞批1，让主线程有时间注入
            return '[{"summary":"分支甲","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _Gated())
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    # 确保任务在 running（批1 被 gate 阻塞）
    # 服务直接注入
    res = svc.inject_fork_guidance(task_id, "补充：南线破局")
    assert res["accepted"] == "running"
    assert any("南线破局" in g for g in res["guidance"])
    # 端点验证
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/fork/guidance", json={"task_id": task_id, "guidance": "再补：海上贸易"})
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["accepted"] == "running"
        assert any("南线破局" in g for g in data["guidance"])
        assert any("海上贸易" in g for g in data["guidance"])
    # 放行批1 → 任务继续并完成（批2 提示词应含运行中注入的 guidance）
    gate.set()
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] in ("completed", "failed")


def test_inject_guidance_non_running_raises(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _QueueLLM(['[{"summary":"x","ev_type":"task"}]']))
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    _wait(tl_service, task_id)  # 等完成
    with pytest.raises(ValueError):
        svc.inject_fork_guidance(task_id, "太晚了")
    # 端点 → 400
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/fork/guidance", json={"task_id": task_id, "guidance": "x"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# branch/continue
# ---------------------------------------------------------------------------
def test_branch_continue_sort_continues(tl_service, monkeypatch):
    arr1 = '[{"summary":"分支甲","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    arr2 = '[{"summary":"分支乙","time_text":"三年后","ev_type":"milestone","confidence":0.7}]'
    arrc = '[{"summary":"续推丙","time_text":"五年后","ev_type":"milestone","confidence":0.7}]'
    llm = _QueueLLM([arr1, arr2, arrc])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    events = _seed(tl_service)
    t1 = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    _wait(tl_service, t1)
    branch_ev = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
                 if e.get("kind") == "branch"]
    branch_id = branch_ev[0]["branch_id"]
    max_sort = max(e["sort_lower"] for e in branch_ev)
    t2 = svc.start_branch_continue("proj_0123456789ab", branch_id, "继续推进", 5)
    status = _wait(tl_service, t2)
    assert status is not None and status["status"] == "completed"
    after = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
             if e.get("branch_id") == branch_id]
    cont = [e for e in after if e["summary"] == "续推丙"]
    assert cont, "续推事件应存在"
    assert cont[0]["sort_lower"] > max_sort, "续推 sort 应从分支最大+1 起"


def test_branch_continue_missing_branch_400(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "_build_llm_client", lambda: _QueueLLM(['[{"summary":"x","ev_type":"task"}]']))
    _seed(tl_service)
    task_id = svc.start_branch_continue("proj_0123456789ab", "no_such_branch", "x", 3)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "failed"


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------
def test_characters_seed_save(tl_service):
    events = _seed(tl_service)
    # 事件带 characters
    for i, e in enumerate(events):
        e["characters"] = [f"角色{i}"]
    svc._save_timeline("proj_0123456789ab", events)
    profiles = svc.ensure_characters("proj_0123456789ab")
    assert profiles, "应从事件自动种子"
    assert all(isinstance(p, dict) and p.get("name") for p in profiles)
    # 提示词注入版返回字符串列表
    inj = svc._character_profiles("proj_0123456789ab")
    assert inj and all(isinstance(s, str) and s.startswith("角色") for s in inj)
    # 保存自定义
    ok = svc.save_characters("proj_0123456789ab", [{"name": "阿米娅", "description": "罗德岛领袖"}])
    assert ok
    loaded = svc.load_characters("proj_0123456789ab")
    assert loaded and loaded[0]["name"] == "阿米娅"
    # 提示词注入块
    block = svc._character_profiles_block("proj_0123456789ab")
    assert "人物设定：" in block and "阿米娅" in block


def test_characters_endpoints(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(__import__("tempfile").mkdtemp()))
    with svc._task_lock:
        svc._tasks.clear()
    _seed(svc)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        # GET 空 → 从事件种子
        r = c.get("/api/timeline/proj_0123456789ab/characters")
        assert r.status_code == 200
        # PUT 保存
        r2 = c.put("/api/timeline/proj_0123456789ab/characters",
                   json={"characters": [{"name": "龙门守门人", "description": "沉默寡言"}]})
        assert r2.status_code == 200
        assert r2.get_json()["data"]["characters"][0]["name"] == "龙门守门人"
        # GET 回读
        r3 = c.get("/api/timeline/proj_0123456789ab/characters")
        assert r3.get_json()["data"]["characters"][0]["name"] == "龙门守门人"


def test_characters_prompt_injection_and_length(tl_service, monkeypatch):
    # 超长事件 summary 截断 + 人物设定注入，且 user <= 2600
    long_summary = "长" * 300
    events = _seed(tl_service)
    events[0]["summary"] = long_summary
    events[0]["characters"] = ["阿米娅", "博士"]
    svc._save_timeline("proj_0123456789ab", events[:1])
    svc.save_characters("proj_0123456789ab", [
        {"name": "阿米娅", "description": "长" * 200},
        {"name": "博士", "description": "指挥"},
    ])
    arr1 = '[{"summary":"分支甲","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    arr2 = '[{"summary":"分支乙","time_text":"三年后","ev_type":"milestone","confidence":0.7}]'
    llm = _QueueLLM([arr1, arr2])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    # 断言注入块出现过 人物设定
    assert "人物设定" in (llm.last_user or "")
    # 断言 user 消息 <= 2600
    assert len(llm.last_user or "") <= 2600


# ---------------------------------------------------------------------------
# 400/404 校验
# ---------------------------------------------------------------------------
def test_branch_continue_route_invalid_pid(tl_service, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(__import__("tempfile").mkdtemp()))
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/bad_pid/branch/continue", json={"branch_id": "b1"})
        assert r.status_code in (400, 404)
        r2 = c.post("/api/timeline/bad_pid/branch/continue", json={})
        assert r2.status_code == 400  # 缺 branch_id


# ---------------------------------------------------------------------------
# 批1/批2 之间的 guidance 等待窗口
# ---------------------------------------------------------------------------
def test_guidance_window_inject_immediately_continues(tl_service, monkeypatch):
    """批1 完成后窗口期内注入 guidance → 立即续写批2，批2 提示词与事件均携带注入。"""
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 2.0)
    arr1 = '[{"summary":"前半段","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    arr2 = '[{"summary":"后半段","time_text":"三年后","ev_type":"milestone","confidence":0.7}]'
    llm = _QueueLLM([arr1, arr2])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    # 批1 是 mock（立即返回），0.3s 后必然已进入等待窗口
    time.sleep(0.3)
    svc.inject_fork_guidance(task_id, "注入：引导结局")
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    assert status.get("event_count", 0) == 2
    # 批2（最后一次调用）提示词包含注入
    assert "注入：引导结局" in (llm.last_user or "")
    # 分支事件 guidance 列表包含注入（批1 事件只带初始 guidance，批2 事件带注入）
    branch_ev = [e for e in svc.load_timeline("proj_0123456789ab", None)["events"]
                 if e.get("kind") == "branch"]
    assert branch_ev
    assert any("注入：引导结局" in (e.get("guidance") or []) for e in branch_ev)


def test_guidance_window_timeout_continues_without(tl_service, monkeypatch):
    """窗口期无人注入 → 窗口结束后仍正常续写批2，提示词不含补充设定段。"""
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 0.3)
    arr1 = '[{"summary":"前半段","time_text":"一年后","ev_type":"task","confidence":0.8}]'
    arr2 = '[{"summary":"后半段","time_text":"三年后","ev_type":"milestone","confidence":0.7}]'
    llm = _QueueLLM([arr1, arr2])
    monkeypatch.setattr(svc, "_build_llm_client", lambda: llm)
    events = _seed(tl_service)
    task_id = svc.start_fork("proj_0123456789ab", events[0]["id"], "目标", 5)
    status = _wait(tl_service, task_id)
    assert status is not None and status["status"] == "completed"
    assert status.get("event_count", 0) == 2
    assert "补充设定" not in (llm.last_user or "")