"""内置项目助手 API 测试。"""

import json

import pytest

from app import create_app
from app.models.project import ProjectManager
from app.services import timeline_service as tl
from app.services import world_bible as wb
from app.services import conflict_detector as cd
from app.api import assistant as assistant_api


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(wb, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(tl, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(cd, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False
    yield
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False


class _FakeLLM:
    def __init__(self, answer="建议去「时间线」面板，把结尾事件标记为 dimension=meta。"):
        self.answer = answer
        self.calls = 0

    def chat(self, **kw):
        self.calls += 1
        return self.answer


def test_assistant_returns_answer(monkeypatch):
    project = ProjectManager.create_project(name="测试项目")
    wb.WorldBibleService.save_input(
        project_id=project.project_id,
        background="乌萨斯帝国位于北方。",
        story="阿米娅踏上旅途。",
        embed=False,
    )
    fake = _FakeLLM()
    monkeypatch.setattr(assistant_api, "_build_llm_client_for_project", lambda pid: fake)

    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/assistant/ask", json={
            "project_id": project.project_id,
            "question": "结尾和前面不像同一世界，怎么办？",
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"] is True
        assert body["data"]["answer"] == fake.answer
        assert "测试项目" in body["data"]["context"]
        assert fake.calls == 1


def test_assistant_can_execute_timeline_update(monkeypatch):
    project = ProjectManager.create_project(name="操作项目")
    ev = tl._normalize_event(
        {"summary": "旧事件", "time_text": "1090 年", "ev_type": "milestone"},
        project.project_id, "bg", 0, "llm", 1,
    )
    tl._save_timeline(project.project_id, [ev])

    fake = _FakeLLM(answer=json.dumps({
        "action": "update_timeline_event",
        "params": {"event_id": ev["id"], "patch": {"summary": "新事件"}},
    }, ensure_ascii=False))
    monkeypatch.setattr(assistant_api, "_build_llm_client_for_project", lambda pid: fake)

    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/assistant/ask", json={
            "project_id": project.project_id,
            "question": "把这条事件改成新事件",
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"] is True
        assert body["data"]["action"] == "update_timeline_event"
        assert body["data"]["action_result"]["updated"]["summary"] == "新事件"
        # 持久化验证
        reloaded = tl.load_timeline(project.project_id, None)["events"][0]
        assert reloaded["summary"] == "新事件"


def test_assistant_requires_project_and_question(monkeypatch):
    app = create_app(); app.config["TESTING"] = True
    with app.test_client() as c:
        assert c.post("/api/assistant/ask", json={"project_id": "", "question": "x"}).status_code == 400
        assert c.post("/api/assistant/ask", json={"project_id": "proj_0123456789ab", "question": ""}).status_code == 400
