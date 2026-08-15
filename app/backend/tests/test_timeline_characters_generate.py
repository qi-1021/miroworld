"""
t30 人物设定自动生成测试：

1. 生成填充空字段（traits/description 空 → LLM 生成填入）。
2. 已编辑字段不被覆盖。
3. 全部已填 → 不调 LLM，message="所有人物已有设定，无需生成"。
4. LLM 失败 → status=failed + error。
5. 端点 POST /<pid>/characters/generate → 200 task_id；非法 project → 400。
"""
import time

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


class _GenLLM:
    """返回预置人物设定 JSON 数组。calls 记录调用次数。"""
    def __init__(self, reply, fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = 0

    def chat(self, **kw):
        self.calls += 1
        if self.fail:
            raise ConnectionError("gateway down")
        return self.reply


def _wait(task_id, deadline=10):
    s = None
    end = time.time() + deadline
    while time.time() < end:
        s = svc.get_status(task_id)
        if s and s.get("status") in ("completed", "failed"):
            return s
        time.sleep(0.05)
    return s


def _seed_characters(names, fill=False):
    """写入人物设定档案。fill=True 时给第一个人物填 traits/description（模拟已编辑）。"""
    profiles = [{"name": n, "traits": "", "description": ""} for n in names]
    if fill and profiles:
        profiles[0]["traits"] = "已编辑特质"
        profiles[0]["description"] = "已编辑描述"
    svc.save_characters("proj_0123456789ab", profiles)
    return profiles


def test_generate_fills_empty_fields(monkeypatch):
    _seed_characters(["阿米娅", "博士"])
    llm = _GenLLM('[{"name":"阿米娅","traits":"温柔坚韧","description":"罗德岛领袖"},'
                  '{"name":"博士","traits":"冷静指挥","description":"战略家"}]')
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: llm)
    task_id = svc.start_characters_generate("proj_0123456789ab")
    status = _wait(task_id)
    assert status is not None and status["status"] == "completed"
    assert "已生成 2 位" in status["message"]
    loaded = svc.load_characters("proj_0123456789ab")
    by_name = {p["name"]: p for p in loaded}
    assert by_name["阿米娅"]["traits"] == "温柔坚韧"
    assert by_name["阿米娅"]["description"] == "罗德岛领袖"
    assert by_name["博士"]["traits"] == "冷静指挥"
    assert llm.calls == 1


def test_generate_does_not_overwrite_edited(monkeypatch):
    _seed_characters(["阿米娅", "博士"], fill=True)
    llm = _GenLLM('[{"name":"阿米娅","traits":"LLM新特质","description":"LLM新描述"},'
                  '{"name":"博士","traits":"冷静指挥","description":"战略家"}]')
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: llm)
    task_id = svc.start_characters_generate("proj_0123456789ab")
    status = _wait(task_id)
    assert status is not None and status["status"] == "completed"
    loaded = svc.load_characters("proj_0123456789ab")
    by_name = {p["name"]: p for p in loaded}
    # 阿米娅已编辑 → 不被覆盖
    assert by_name["阿米娅"]["traits"] == "已编辑特质"
    assert by_name["阿米娅"]["description"] == "已编辑描述"
    # 博士空 → 被填入
    assert by_name["博士"]["traits"] == "冷静指挥"


def test_generate_all_filled_skips_llm(monkeypatch):
    _seed_characters(["阿米娅"], fill=True)
    llm = _GenLLM('[{"name":"阿米娅","traits":"x","description":"y"}]')
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: llm)
    task_id = svc.start_characters_generate("proj_0123456789ab")
    status = _wait(task_id)
    assert status is not None and status["status"] == "completed"
    assert "无需生成" in status["message"]
    assert llm.calls == 0, "全部已填不应调用 LLM"


def test_generate_failure_sets_error(monkeypatch):
    _seed_characters(["阿米娅"])
    llm = _GenLLM('', fail=True)
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: llm)
    task_id = svc.start_characters_generate("proj_0123456789ab")
    status = _wait(task_id)
    assert status is not None and status["status"] == "failed"
    assert status["error"] and status["stage"] == "失败"


def test_endpoint_generate(monkeypatch):
    _seed_characters(["阿米娅"])
    llm = _GenLLM('[{"name":"阿米娅","traits":"t","description":"d"}]')
    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: llm)
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/timeline/proj_0123456789ab/characters/generate")
        assert r.status_code == 200
        assert r.get_json()["data"]["task_id"]
        # 非法 project → 400
        r2 = c.post("/api/timeline/bad_pid/characters/generate")
        assert r2.status_code == 400
