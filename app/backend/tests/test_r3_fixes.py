"""
t3 后端收尾补测试：为已实现功能补 pytest 测试并修复发现的问题。

覆盖：
1. delete_simulation 幂等（sim_/worldsim_/world_ 已不存在返回 already_absent）
2. save_world_input 后 project.files 同步
3. timeline_service._reconcile_threads 线性合并
4. timeline extract progress 读写
5. conflict defense_rounds 追加（PATCH /conflicts/<id> justified）
6. world_novel 生成/读取（mock LLM）
7. assistant 动作分发
8. graph build_progress 读写/resume 跳过
"""

import io
import json
import os
from types import SimpleNamespace

import pytest

from app import create_app
from app.models.project import ProjectManager, ProjectStatus
from app.services import conflict_detector as cd
from app.services import simulation_manager as sm
from app.services import timeline_service as tl
from app.services import world_bible as wb
from app.services import world_graph_refill as wgr
from app.services import world_novel as wn
from app.services import world_simulation as ws


VALID_PID = "proj_0123456789ab"


def _make_file(name, content, filename=None):
    return (io.BytesIO(content.encode("utf-8")), filename or name)


# ---------------------------------------------------------------------------
# 公共隔离 fixture：隔离各类数据根目录，避免污染真实数据
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(wb, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(cd, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(tl, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(ws, "WORLD_SIM_ROOT", str(tmp_path / "world-sim"))
    monkeypatch.setattr(wn, "WORLD_SIM_ROOT", str(tmp_path / "world-sim"))
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "uploads-sim"))
    monkeypatch.setattr(wgr, "WORLD_GRAPH_ROOT", str(tmp_path / "world-graph"))
    # 重置时间线任务状态缓存
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False
    # 重置世界模拟内存状态缓存
    with ws.WorldSimulationService._lock:
        ws.WorldSimulationService._states.clear()
    yield
    with tl._task_lock:
        tl._tasks.clear()
    tl._tasks_loaded = False
    with ws.WorldSimulationService._lock:
        ws.WorldSimulationService._states.clear()


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _seed_project():
    """创建一个项目并写入背景/正文，返回 project 对象。"""
    project = ProjectManager.create_project(name="r3测试项目")
    wb.WorldBibleService.save_input(
        project_id=project.project_id,
        background="龙裔王国建于三百年前，首都是龙脊城。",
        story="清晨，龙脊城街道上，平民艾拉抱怨道：'五百年前建立的龙裔王国……'",
        embed=False,
    )
    return project


# ---------------------------------------------------------------------------
# 1. delete_simulation 幂等
# ---------------------------------------------------------------------------
class TestDeleteSimulationIdempotent:
    def test_world_placeholder_already_absent(self, client):
        """world_<pid> 数据目录不存在 → already_absent: True"""
        rv = client.delete("/api/simulation/world_proj_ffffffffffff")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True
        assert body["removed_any"] is False
        assert body["already_absent"] is True

    def test_worldsim_already_absent(self, client):
        """worldsim_xxx 不存在 → already_absent: True（不 404）"""
        rv = client.delete("/api/simulation/worldsim_19880101000000_deadbeef")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True
        assert body["already_absent"] is True
        assert body["removed_any"] is False

    def test_sim_idempotent_after_directory_removed(self, client):
        """媒体模拟目录删除后再删 → already_absent True"""
        SimulationManager = sm.SimulationManager
        sim_dir = os.path.join(SimulationManager.SIMULATION_DATA_DIR, "sim_abc123")
        os.makedirs(sim_dir, exist_ok=True)
        with open(os.path.join(sim_dir, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"simulation_id": "sim_abc123", "status": "created"}, f)
        # 第一次删除成功
        rv1 = client.delete("/api/simulation/sim_abc123")
        assert rv1.status_code == 200
        assert rv1.get_json()["removed_any"] is True
        assert not os.path.exists(sim_dir)
        # 第二次删除：目录已不存在 → 幂等 already_absent
        rv2 = client.delete("/api/simulation/sim_abc123")
        assert rv2.status_code == 200
        body2 = rv2.get_json()
        assert body2["success"] is True
        assert body2["already_absent"] is True
        assert body2["removed_any"] is False

    def test_non_mirofish_missing_returns_404(self, client):
        """非 MiroFish 标识且不存在 → 404"""
        rv = client.delete("/api/simulation/random_missing_id")
        assert rv.status_code == 404


# ---------------------------------------------------------------------------
# 2. save_world_input → project.files
# ---------------------------------------------------------------------------
class TestSaveWorldInputFilesSync:
    def test_file_manifest_synced_to_project(self, client):
        project = ProjectManager.create_project(name="文件项目")
        pid = project.project_id
        rv = client.post(
            f"/api/world/{pid}/input",
            data={
                "background_files": [_make_file("bg.txt", "东境由龙裔王国统治。", "bg.txt")],
                "story_files": [_make_file("ch1.txt", "第一章：清晨的龙脊城。", "ch1.txt")],
            },
            content_type="multipart/form-data",
        )
        assert rv.status_code == 200
        stats = rv.get_json()["stats"]
        assert len(stats["files"]) == 2

        reloaded = ProjectManager.get_project(pid)
        assert reloaded is not None
        assert len(reloaded.files) == 2
        filenames = {f.get("filename") for f in reloaded.files}
        assert filenames == {"bg.txt", "ch1.txt"}
        # text-only 保存不清掉已有文件清单
        rv2 = client.post(
            f"/api/world/{pid}/input",
            data={"background_text": "追加背景", "story_text": "追加正文"},
            content_type="multipart/form-data",
        )
        assert rv2.status_code == 200
        reloaded2 = ProjectManager.get_project(pid)
        assert {f.get("filename") for f in reloaded2.files} == filenames

    def test_text_only_keeps_empty_files(self, client):
        project = ProjectManager.create_project(name="纯文本项目")
        pid = project.project_id
        rv = client.post(
            f"/api/world/{pid}/input",
            data={"background_text": "背景文本", "story_text": "正文文本"},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 200
        reloaded = ProjectManager.get_project(pid)
        assert reloaded.files == []
        assert reloaded.total_text_length > 0


# ---------------------------------------------------------------------------
# 3. timeline _reconcile_threads 线性合并
# ---------------------------------------------------------------------------
class TestReconcileThreads:
    def test_single_structure_merges_all_to_main(self):
        events = [
            {"thread_id": "a", "thread_name": "主线", "dimension": "main"},
            {"thread_id": "b", "thread_name": "乌萨斯", "dimension": "d"},
        ]
        out = tl._reconcile_threads(events, {"type": "single"}, [])
        for e in out:
            assert e["thread_id"] == ""
            assert e["thread_name"] == ""
            assert e["dimension"] == "main"
            assert e["parallel_group"] == ""

    def test_multiline_merges_aliases(self):
        events = [
            {"thread_name": "乌萨斯", "thread_id": "usa"},
            {"thread_name": "乌萨斯主线", "thread_id": "usa2"},
            {"thread_name": "炎国", "thread_id": "yan"},
        ]
        threads = [
            {"name": "乌萨斯", "id": "usa", "dimension": "power"},
            {"name": "炎国", "id": "yan", "dimension": "power"},
        ]
        out = tl._reconcile_threads(events, {"type": "parallel"}, threads)
        # 乌萨斯 与 乌萨斯主线 应合并到同一 canon
        names = [e["thread_name"] for e in out]
        assert "乌萨斯" in names
        assert "乌萨斯主线" not in names  # 归一化到 canon 名
        tid_set = {e["thread_id"] for e in out}
        assert len(tid_set) == 2  # 两条平行线

    def test_empty_events_returns_empty(self):
        assert tl._reconcile_threads([], None, []) == []


# ---------------------------------------------------------------------------
# 4. extract progress 读写
# ---------------------------------------------------------------------------
class TestExtractProgress:
    def test_save_and_load_roundtrip(self):
        entries = [
            {"index": 0, "hash": "abc", "method": "llm", "events": [{"summary": "e0"}]},
            {"index": 1, "hash": "def", "method": "heuristic", "events": [{"summary": "e1"}]},
        ]
        assert tl._save_extract_progress(VALID_PID, "story", entries) is True
        loaded = tl._load_extract_progress(VALID_PID, "story")
        assert len(loaded) == 2
        assert loaded[0]["events"][0]["summary"] == "e0"

    def test_load_missing_returns_empty(self):
        assert tl._load_extract_progress(VALID_PID, "nope") == []

    def test_chunk_hash_stable_and_changes(self):
        h1 = tl._chunk_hash("同一个文本")
        h2 = tl._chunk_hash("同一个文本")
        h3 = tl._chunk_hash("不同文本")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 40  # sha1 hex


# ---------------------------------------------------------------------------
# 5. conflict defense_rounds 追加
# ---------------------------------------------------------------------------
class _FakeDefenseLLM:
    """返回 defense_accepted 裁定的 Fake LLM"""

    def __init__(self, verdict="defense_accepted"):
        self.verdict = verdict
        self.calls = []

    def chat_json(self, messages, temperature=0.2, max_tokens=1200, **kw):
        self.calls.append(messages)
        return {
            "verdict": self.verdict,
            "reply": "辩解成立，接受该处理。",
            "reasoning": "理由充分",
        }


def _seed_conflict(project_id):
    conflict = cd.ConflictItem(
        conflict_id="ci_123",
        topic="建国时间",
        conflict_type="time_conflict",
        background_fact="三百年前",
        story_fact="五百年前",
    )
    report = cd.ConflictReport(project_id=project_id, conflicts=[conflict])
    cd.save_conflict_report(project_id, report)
    return conflict


class TestConflictDefenseRounds:
    def test_patch_justified_appends_rounds(self, client, monkeypatch):
        project = _seed_project()
        _seed_conflict(project.project_id)

        from app.api import world as world_api
        fake = _FakeDefenseLLM()
        monkeypatch.setattr(world_api, "_build_llm_client_for_project", lambda pid: fake)

        rv = client.patch(
            f"/api/world/{project.project_id}/conflicts/ci_123",
            json={"status": "justified", "note": "这其实是指寓言层的时间。"},
        )
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True
        conflict = body["conflict"]
        assert conflict["status"] == "justified"
        assert conflict["effective"] is True
        # 至少追加 2 轮：user + assistant
        assert len(conflict["defense_rounds"]) >= 2
        roles = [r["role"] for r in conflict["defense_rounds"]]
        assert "user" in roles
        assert "assistant" in roles

        # 持久化验证
        reloaded = cd.load_conflict_report(project.project_id)
        assert reloaded is not None
        c0 = reloaded.conflicts[0]
        assert len(c0.defense_rounds) >= 2
        assert c0.effective is True

    def test_patch_rejected_keeps_open(self, client, monkeypatch):
        project = _seed_project()
        _seed_conflict(project.project_id)

        from app.api import world as world_api
        fake = _FakeDefenseLLM(verdict="defense_rejected")
        monkeypatch.setattr(world_api, "_build_llm_client_for_project", lambda pid: fake)

        rv = client.patch(
            f"/api/world/{project.project_id}/conflicts/ci_123",
            json={"status": "justified", "note": "辩解不充分"},
        )
        body = rv.get_json()
        assert body["success"] is True
        assert body["conflict"]["status"] == "open"
        assert body["conflict"]["effective"] is False

    def test_patch_invalid_status_rejected(self, client):
        project = _seed_project()
        _seed_conflict(project.project_id)
        rv = client.patch(
            f"/api/world/{project.project_id}/conflicts/ci_123",
            json={"status": "bogus"},
        )
        assert rv.status_code == 400

    def test_patch_justified_requires_note(self, client):
        project = _seed_project()
        _seed_conflict(project.project_id)
        rv = client.patch(
            f"/api/world/{project.project_id}/conflicts/ci_123",
            json={"status": "justified"},
        )
        assert rv.status_code == 400
        assert "note" in rv.get_json()["error"]

    def test_load_effective_resolutions(self):
        project = _seed_project()
        _seed_conflict(project.project_id)
        # open 状态不入 effective
        assert cd.load_effective_resolutions(project.project_id) == []
        report = cd.load_conflict_report(project.project_id)
        report.conflicts[0].status = "accepted"
        report.conflicts[0].effective = True
        cd.save_conflict_report(project.project_id, report)
        resolutions = cd.load_effective_resolutions(project.project_id)
        assert len(resolutions) == 1
        assert resolutions[0]["status"] == "accepted"
        assert resolutions[0]["effective"] is True


# ---------------------------------------------------------------------------
# 6. world_novel 生成/读取（mock LLM）
# ---------------------------------------------------------------------------
class _FakeNovelLLM:
    def __init__(self, text="第一章\n正文内容", chapters=None):
        self.text = text
        self.chapters = chapters or [{"title": "第一章", "content": "正文内容"}]

    def chat_json(self, messages, temperature=0.7, max_tokens=8192, **kw):
        return {"text": self.text, "chapters": self.chapters}


def _seed_simulation(project_id, sim_id="worldsim_20260101000000_deadbeef"):
    sim_dir = os.path.join(ws.WORLD_SIM_ROOT, project_id, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump([{"time": "T+1h", "type": "conflict", "summary": "守城战开始"}], f, ensure_ascii=False)
    with open(os.path.join(sim_dir, "world_config.json"), "w", encoding="utf-8") as f:
        json.dump({"world": {"name": "测试世界"}, "goal": "守住城门"}, f, ensure_ascii=False)
    state = ws.WorldSimulationState(
        simulation_id=sim_id,
        project_id=project_id,
        status="completed",
        result={"goal": "守住城门"},
    )
    ws.WorldSimulationService._save_state(state)
    return sim_id


class TestWorldNovel:
    def test_generate_and_load(self):
        project = _seed_project()
        sim_id = _seed_simulation(project.project_id)
        fake = _FakeNovelLLM()
        novel = wn.WorldNovelService.generate_novel(project.project_id, sim_id, llm=fake)
        assert novel.get("text") == "第一章\n正文内容"
        assert len(novel.get("chapters")) == 1
        # 已落盘
        assert os.path.exists(
            os.path.join(ws.WORLD_SIM_ROOT, project.project_id, sim_id, "novel.json")
        )
        assert os.path.exists(
            os.path.join(ws.WORLD_SIM_ROOT, project.project_id, sim_id, "novel.md")
        )
        loaded = wn.WorldNovelService.load_novel(project.project_id, sim_id)
        assert loaded is not None
        assert loaded["text"] == "第一章\n正文内容"

    def test_generate_unknown_simulation_raises(self):
        project = _seed_project()
        fake = _FakeNovelLLM()
        with pytest.raises(ValueError):
            wn.WorldNovelService.generate_novel(project.project_id, "worldsim_missing", llm=fake)

    def test_load_missing_returns_none(self):
        project = _seed_project()
        assert wn.WorldNovelService.load_novel(project.project_id, "worldsim_none") is None


# ---------------------------------------------------------------------------
# 7. assistant 动作分发
# ---------------------------------------------------------------------------
class TestAssistantActions:
    def test_dispatch_unknown_action_raises(self):
        from app.api import assistant as aa
        with pytest.raises(ValueError):
            aa._execute_assistant_action(VALID_PID, "no_such_action", {})

    def test_dispatch_get_project_status(self):
        from app.api import assistant as aa
        project = _seed_project()
        result = aa._execute_assistant_action(project.project_id, "get_project_status", {})
        assert "context" in result
        assert "项目" in result["context"]

    def test_dispatch_batch_delete_events(self):
        from app.api import assistant as aa
        project = _seed_project()
        ev = tl._normalize_event(
            {"summary": "要删事件", "time_text": "1090 年", "ev_type": "milestone"},
            project.project_id, "bg", 0, "llm", 1,
        )
        tl._save_timeline(project.project_id, [ev])
        result = aa._execute_assistant_action(
            project.project_id, "batch_delete_events", {"event_ids": [ev["id"]]}
        )
        assert result.get("deleted") == 1
        assert tl.load_timeline(project.project_id, None)["events"] == []

    def test_dispatch_update_timeline_event(self):
        from app.api import assistant as aa
        project = _seed_project()
        ev = tl._normalize_event(
            {"summary": "旧", "time_text": "1090 年", "ev_type": "milestone"},
            project.project_id, "bg", 0, "llm", 1,
        )
        tl._save_timeline(project.project_id, [ev])
        result = aa._execute_assistant_action(
            project.project_id, "update_timeline_event",
            {"event_id": ev["id"], "patch": {"summary": "新"}},
        )
        assert result["updated"]["summary"] == "新"

    def test_dispatch_save_world_input(self):
        from app.api import assistant as aa
        project = _seed_project()
        result = aa._execute_assistant_action(
            project.project_id, "save_world_input",
            {"background": "新的背景设定", "story": ""},
        )
        assert result.get("chunks") >= 0
        bible = wb.WorldBibleService.get_bible(project.project_id)
        assert "新的背景设定" in bible.background_text

    def test_dispatch_update_conflict_status(self, monkeypatch):
        from app.api import assistant as aa
        project = _seed_project()
        _seed_conflict(project.project_id)
        fake = _FakeDefenseLLM(verdict="defense_accepted")
        monkeypatch.setattr(aa, "_build_llm_client_for_project", lambda pid: fake)
        result = aa._execute_assistant_action(
            project.project_id, "update_conflict_status",
            {"conflict_id": "ci_123", "status": "justified", "note": "寓言层时间"},
        )
        assert result["status"] == "justified"
        assert result["effective"] is True


# ---------------------------------------------------------------------------
# 8. graph build_progress 读写/resume 跳过
# ---------------------------------------------------------------------------
class TestBuildProgress:
    def test_save_load_roundtrip(self):
        chunks = [{"index": 0, "hash": "a", "status": "done", "episode_uuid": "u1"}]
        assert wgr.save_build_progress(VALID_PID, chunks, graph_id="g1") is True
        loaded = wgr.load_build_progress(VALID_PID)
        assert loaded is not None
        assert loaded["graph_id"] == "g1"
        assert len(loaded["chunks"]) == 1
        assert loaded["chunks"][0]["status"] == "done"

    def test_load_missing_returns_none(self):
        assert wgr.load_build_progress("proj_ffffffffffff") is None

    def test_chunk_hash(self):
        assert wgr.chunk_hash("hello") == wgr.chunk_hash("hello")
        assert wgr.chunk_hash("hello") != wgr.chunk_hash("world")

    def test_mark_chunks_done_resume_skip(self):
        # 先标记部分 chunk done
        texts = ["片段A", "片段B"]
        wgr.mark_chunks_done(VALID_PID, texts, [0, 1], ["u0", "u1"], graph_id="gx")
        progress = wgr.load_build_progress(VALID_PID)
        assert progress is not None
        done = {c["index"]: c for c in progress["chunks"]}
        assert done[0]["hash"] == wgr.chunk_hash("片段A")
        assert done[0]["status"] == "done"
        # 源文本未变 → hash 匹配，resume 可跳过已完成 chunk
        assert done[0]["hash"] == wgr.chunk_hash("片段A")
        assert done[1]["hash"] == wgr.chunk_hash("片段B")
