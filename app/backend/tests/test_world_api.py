"""世界设定库 API 测试"""

import json
import os

import pytest

from app import create_app
from app.services.world_bible import WorldBibleService


@pytest.fixture()
def client(tmp_path):
    """构造测试 Flask 客户端，隔离世界数据目录"""
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd

    original_wb = wb.WORLD_DATA_ROOT
    original_cd = cd.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    cd.WORLD_DATA_ROOT = str(tmp_path / "world")

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

    wb.WORLD_DATA_ROOT = original_wb
    cd.WORLD_DATA_ROOT = original_cd


BG = (
    "龙裔王国建于三百年前，首都是龙脊城。王国信奉烈焰女神。"
    "魔法需要付出代价：施法者每使用一次高阶魔法，就会消耗自身寿命。"
)
STORY = (
    "清晨，龙脊城的街道上，平民艾拉抱怨道：'五百年前建立的龙裔王国，如今连城门都破了。'"
    "法师卡尔随手施展禁咒级火球术，毫发无损。"
)


def test_input_requires_at_least_one(client):
    rv = client.post("/api/world/p1/input", json={"background": "", "story": ""})
    assert rv.status_code == 400
    assert "不能同时为空" in rv.get_json()["error"]


def test_input_background_only(client):
    rv = client.post("/api/world/p1/input", json={"background": BG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["stats"]["has_background"] is True
    assert body["stats"]["has_story"] is False


def test_input_both_sources(client):
    rv = client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["background_chunks"] >= 1
    assert stats["story_chunks"] >= 1


def test_settings_roundtrip(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.get("/api/world/p1/settings")
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["total_chunks"] >= 2


def test_settings_missing_project(client):
    rv = client.get("/api/world/nope/settings")
    assert rv.status_code == 200
    assert rv.get_json()["stats"] is None


def test_chunks_list_and_source_filter(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.get("/api/world/p1/chunks?source=background")
    body = rv.get_json()
    assert body["success"] is True
    assert all(c["source"] == "background" for c in body["chunks"])
    assert body["total"] == 2


def test_search_endpoint(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.post("/api/world/p1/search", json={"query": "龙脊城"})
    assert rv.status_code == 200
    results = rv.get_json()["results"]
    assert len(results) >= 1
    assert all("龙脊城" in r["text"] for r in results)


def test_search_empty_query(client):
    rv = client.post("/api/world/p1/search", json={"query": ""})
    assert rv.status_code == 400


def test_conflict_detect_requires_input(client):
    rv = client.post("/api/world/p1/conflicts/detect")
    assert rv.status_code == 400
    assert "尚未提交" in rv.get_json()["error"]


def test_conflict_detect_requires_both_sources(client):
    client.post("/api/world/p1/input", json={"background": BG})
    rv = client.post("/api/world/p1/conflicts/detect")
    assert rv.status_code == 400
    assert "同时有背景" in rv.get_json()["error"]


def test_conflict_detect_starts_task_and_status_update(client):
    """启动任务 + 写一份报告 + 更新状态 + 读取（不实际调用 LLM）"""
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})

    # 手工落盘一份报告（模拟任务完成后的状态）
    from app.services.conflict_detector import (
        ConflictItem, ConflictReport, save_conflict_report,
    )
    report = ConflictReport(
        project_id="p1",
        conflicts=[ConflictItem(
            conflict_id="c1", topic="建国时间", conflict_type="time_conflict",
            background_fact="三百年前", story_fact="五百年前",
            reason="不一致", severity="high", suggestion="以背景为准",
        )],
    )
    save_conflict_report("p1", report)

    # 读取报告
    rv = client.get("/api/world/p1/conflicts")
    assert rv.status_code == 200
    body = rv.get_json()["report"]
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["conflict_id"] == "c1"

    # 更新状态
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "accepted"})
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    rv = client.get("/api/world/p1/conflicts")
    assert rv.get_json()["report"]["conflicts"][0]["status"] == "accepted"

    # 非法状态
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "bogus"})
    assert rv.status_code == 400

    # 不存在的冲突
    rv = client.patch("/api/world/p1/conflicts/none", json={"status": "open"})
    assert rv.status_code == 404


def test_conflicts_none_when_no_report(client):
    rv = client.get("/api/world/p1/conflicts")
    assert rv.status_code == 200
    assert rv.get_json()["report"] is None


def test_delete_world_data(client):
    client.post("/api/world/p1/input", json={"background": BG})
    rv = client.delete("/api/world/p1")
    assert rv.status_code == 200
    rv = client.get("/api/world/p1/settings")
    assert rv.get_json()["stats"] is None


# ---------------- 多文件上传 ----------------

def _make_file(name, content, filename=None):
    import io
    return (io.BytesIO(content.encode('utf-8')), filename or name)


def test_multipart_multi_file_upload(client):
    """背景 + 章节各传多个文件"""
    rv = client.post(
        "/api/world/p1/input",
        data={
            "background_files": [
                _make_file("bg1.txt", "龙裔王国建于三百年前，首都是龙脊城。", "bg1.txt"),
                _make_file("bg2.md", "# 规则\n魔法需要付出代价。", "bg2.md"),
            ],
            "story_files": [
                _make_file("ch1.txt", "第一章：清晨的龙脊城街道。", "ch1.txt"),
                _make_file("ch2.txt", "第二章：铁匠卡拉支起摊位。", "ch2.txt"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    stats = body["stats"]
    assert stats["has_background"] is True
    assert stats["has_story"] is True
    assert stats["background_chunks"] >= 1
    assert stats["story_chunks"] >= 1
    # 文件清单
    files = stats["files"]
    assert len(files) == 4
    bg_files = [f for f in files if f["source"] == "background"]
    st_files = [f for f in files if f["source"] == "story"]
    assert len(bg_files) == 2
    assert len(st_files) == 2
    assert {f["filename"] for f in bg_files} == {"bg1.txt", "bg2.md"}
    # 文本已合并入库
    bible = WorldBibleService.get_bible("p1")
    assert "龙裔王国" in bible.background_text
    assert "魔法需要付出代价" in bible.background_text
    assert "第一章" in bible.story_text
    assert "第二章" in bible.story_text


def test_multipart_background_only(client):
    rv = client.post(
        "/api/world/p1/input",
        data={"background_files": [_make_file("bg.txt", "东境由龙裔王国统治。", "bg.txt")]},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["has_background"] is True
    assert stats["has_story"] is False


def test_multipart_unsupported_extension_skipped(client):
    """不支持的文件类型应被跳过；全被跳过时报错"""
    rv = client.post(
        "/api/world/p1/input",
        data={"background_files": [_make_file("bg.exe", "nope", "bg.exe")]},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 400
    assert "不能同时为空" in rv.get_json()["error"]


def test_multipart_with_text_fields(client):
    """文件 + 直接文本混合"""
    rv = client.post(
        "/api/world/p1/input",
        data={
            "background_files": [_make_file("bg.txt", "龙裔王国建于三百年前。", "bg.txt")],
            "background_text": "王国信奉烈焰女神。",
            "story_text": "清晨的龙脊城。",
        },
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["has_background"] is True
    assert stats["has_story"] is True
    bible = WorldBibleService.get_bible("p1")
    assert "烈焰女神" in bible.background_text
    assert "清晨的龙脊城" in bible.story_text


# ---------------------------------------------------------------- 世界模拟控制 API

@pytest.fixture()
def world_sim_client(tmp_path):
    """构造 Flask 客户端，同时隔离世界设定目录与模拟目录"""
    import app.services.world_bible as wb
    import app.services.world_simulation as ws

    original_wb = wb.WORLD_DATA_ROOT
    original_ws = ws.WORLD_SIM_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    ws.WORLD_SIM_ROOT = str(tmp_path / "world-sim")

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

    wb.WORLD_DATA_ROOT = original_wb
    ws.WORLD_SIM_ROOT = original_ws


def _world_sim_state(sim_id="wctl", project="p1", status="running"):
    """构造并保存一个世界模拟状态"""
    from app.services.world_simulation import (
        WorldSimulationService,
        WorldSimulationState,
    )
    state = WorldSimulationState(
        simulation_id=sim_id,
        project_id=project,
        status=status,
    )
    WorldSimulationService._save_state(state)
    return state


def test_control_requires_valid_action(world_sim_client):
    _world_sim_state()
    rv = world_sim_client.post(
        "/api/world/p1/simulation/wctl/control",
        json={"action": "teleport"},
    )
    assert rv.status_code == 400
    assert "action 必须是" in rv.get_json()["error"]


def test_control_missing_simulation(world_sim_client):
    rv = world_sim_client.post(
        "/api/world/p1/simulation/nope/control",
        json={"action": "pause"},
    )
    assert rv.status_code == 400
    assert "模拟不存在" in rv.get_json()["error"]


def test_control_pause(world_sim_client):
    _world_sim_state()
    rv = world_sim_client.post(
        "/api/world/p1/simulation/wctl/control",
        json={"action": "pause"},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["action"] == "pause"
    # 命令文件已写入
    from app.services.world_simulation import WorldSimulationService
    cmd_dir = os.path.join(
        WorldSimulationService._sim_dir("p1", "wctl"), "ipc_commands"
    )
    assert os.path.isdir(cmd_dir)
    assert len([f for f in os.listdir(cmd_dir) if f.endswith(".json")]) == 1


def test_control_stop(world_sim_client):
    _world_sim_state()
    rv = world_sim_client.post(
        "/api/world/p1/simulation/wctl/control",
        json={"action": "stop"},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["action"] == "stop"
    assert body["command_id"]


def test_control_interview_requires_fields(world_sim_client):
    _world_sim_state()
    rv = world_sim_client.post(
        "/api/world/p1/simulation/wctl/control",
        json={"action": "interview", "character_name": "卡拉"},
    )
    assert rv.status_code == 400
    assert "prompt" in rv.get_json()["error"]


def test_control_resume_not_writing_extra(world_sim_client):
    _world_sim_state()
    rv = world_sim_client.post(
        "/api/world/p1/simulation/wctl/control",
        json={"action": "resume"},
    )
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True


# ---------------------------------------------------------------- 世界报告 API

def test_generate_report_endpoint(client, monkeypatch):
    """POST /api/world/<pid>/report → 调用服务并返回报告。"""
    from app.services.world_report import WorldReportService

    canned = {
        "text": "## 世界编年史\n\n内容",
        "sections": [{"title": "世界编年史", "content": "内容"}],
    }
    called = {}
    monkeypatch.setattr(
        WorldReportService, "generate_report",
        classmethod(lambda cls, pid, sid: (called.update(pid=pid, sid=sid), canned)[1]),
    )
    rv = client.post("/api/world/p1/report", json={"simulation_id": "ws1"})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["report"]["text"] == canned["text"]
    assert called == {"pid": "p1", "sid": "ws1"}


def test_generate_report_endpoint_missing_sim_id(client):
    """simulation_id 为空 → 400。"""
    rv = client.post("/api/world/p1/report", json={})
    assert rv.status_code == 400
    assert "simulation_id" in rv.get_json()["error"]


def test_generate_report_endpoint_not_found(client, monkeypatch):
    """模拟不存在 → 404。"""
    from app.services.world_report import WorldReportService

    monkeypatch.setattr(
        WorldReportService, "generate_report",
        classmethod(lambda cls, pid, sid: (_ for _ in ()).throw(ValueError("模拟不存在"))),
    )
    rv = client.post("/api/world/p1/report", json={"simulation_id": "ws_x"})
    assert rv.status_code == 404
    assert "模拟不存在" in rv.get_json()["error"]


def test_get_report_endpoint(client, monkeypatch):
    """GET /api/world/<pid>/report/<sid> → 返回已生成报告。"""
    from app.services.world_report import WorldReportService

    canned = {
        "text": "## 世界编年史\n\n内容",
        "sections": [{"title": "世界编年史", "content": "内容"}],
    }
    monkeypatch.setattr(
        WorldReportService, "load_report",
        classmethod(lambda cls, pid, sid: canned),
    )
    rv = client.get("/api/world/p1/report/ws1")
    assert rv.status_code == 200
    assert rv.get_json()["report"]["text"] == canned["text"]


def test_get_report_endpoint_not_generated(client, monkeypatch):
    """报告未生成 → 404。"""
    from app.services.world_report import WorldReportService

    monkeypatch.setattr(
        WorldReportService, "load_report",
        classmethod(lambda cls, pid, sid: None),
    )
    rv = client.get("/api/world/p1/report/ws1")
    assert rv.status_code == 404
    assert "尚未生成" in rv.get_json()["error"]


def test_simulate_whatif_endpoint(world_sim_client, monkeypatch):
    """POST /api/world/<pid>/simulate/whatif → 调用服务并返回新模拟状态。"""
    from app.services.world_simulation import WorldSimulationService, WorldSimulationState

    called = {}

    def fake_simulate(cls, base_simulation_id, question, steps):
        called.update(base=base_simulation_id, question=question, steps=steps)
        return WorldSimulationState(
            simulation_id="ws_base_whatif", project_id="p1", status="running",
            result={"meta": {"whatif_base": base_simulation_id,
                             "whatif_question": question}},
        )

    monkeypatch.setattr(WorldSimulationService, "simulate_whatif", classmethod(fake_simulate))
    rv = world_sim_client.post(
        "/api/world/p1/simulate/whatif",
        json={"base_simulation_id": "ws_base", "question": "若魔法不需要代价？", "steps": 2},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["simulation"]["simulation_id"] == "ws_base_whatif"
    assert body["simulation"]["result"]["meta"]["whatif_question"] == "若魔法不需要代价？"
    assert called == {"base": "ws_base", "question": "若魔法不需要代价？", "steps": 2}


def test_simulate_whatif_endpoint_missing_fields(world_sim_client, monkeypatch):
    """缺少 question → 400。"""
    from app.services.world_simulation import WorldSimulationService

    monkeypatch.setattr(
        WorldSimulationService, "simulate_whatif",
        classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(ValueError("假设问题不能为空"))),
    )
    rv = world_sim_client.post(
        "/api/world/p1/simulate/whatif",
        json={"base_simulation_id": "ws_base", "question": ""},
    )
    assert rv.status_code == 400
    assert "假设问题不能为空" in rv.get_json()["error"]


# ==================== 任务目标（goal） ====================


def test_input_goal_saved_and_returned_in_settings(client):
    """任务目标随世界输入保存，settings 返回 goal。"""
    rv = client.post(
        "/api/world/p1/input",
        json={"background": BG, "story": STORY, "goal": "推演三年后谁将统一大陆"},
    )
    assert rv.status_code == 200
    rv = client.get("/api/world/p1/settings")
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["goal"] == "推演三年后谁将统一大陆"


def test_input_goal_multipart_form(client):
    """multipart 表单中 goal 字段同样入库。"""
    rv = client.post(
        "/api/world/p1/input",
        data={"background_text": BG, "goal": "推演城门能否守住"},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 200
    rv = client.get("/api/world/p1/settings")
    assert rv.get_json()["stats"]["goal"] == "推演城门能否守住"


def test_input_goal_empty_not_stored(client):
    """goal 为空时不写入 metadata。"""
    rv = client.post("/api/world/p1/input", json={"background": BG, "goal": "  "})
    assert rv.status_code == 200
    rv = client.get("/api/world/p1/settings")
    assert rv.get_json()["stats"]["goal"] == ""


def test_settings_includes_graph_info(client):
    """settings 附带图谱状态字段（无项目 → None）。"""
    client.post("/api/world/p1/input", json={"background": BG})
    rv = client.get("/api/world/p1/settings")
    stats = rv.get_json()["stats"]
    assert "graph_id" in stats
    assert "graph_status" in stats
    assert stats["graph_id"] is None


# ==================== 世界知识图谱 ====================


def test_world_graph_build_requires_input(client):
    """未提交设定库 → 构建图谱返回 400，不创建任务。"""
    rv = client.post("/api/world/p1/graph/build", json={})
    assert rv.status_code == 400
    assert "尚未提交世界输入" in rv.get_json()["error"]


def test_world_graph_get_without_graph(client):
    """未构建图谱 → graph 为 None。"""
    rv = client.get("/api/world/p1/graph")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["graph"] is None
    assert body["graph_id"] is None


def test_simulate_passes_goal(client, monkeypatch):
    """simulate 端点把 goal 透传给 start_simulation。"""
    from app.services.world_simulation import WorldSimulationService

    captured = {}

    def fake_start(cls, project_id, total_steps=6, time_step_minutes=30, goal=None,
                   time_mode="minutes", time_jumps=None, include_timeline=False):
        captured["goal"] = goal
        captured["time_mode"] = time_mode
        captured["time_jumps"] = time_jumps
        captured["include_timeline"] = include_timeline
        from app.services.world_simulation import WorldSimulationState
        return WorldSimulationState(
            simulation_id="ws_goal", project_id=project_id, status="preparing"
        )

    monkeypatch.setattr(WorldSimulationService, "start_simulation", classmethod(fake_start))
    rv = client.post(
        "/api/world/p1/simulate",
        json={"total_steps": 5, "goal": "推演结局"},
    )
    assert rv.status_code == 200
    assert captured["goal"] == "推演结局"
    assert captured["time_mode"] == "minutes"
    assert captured["time_jumps"] == []
    assert captured["include_timeline"] is False


def test_simulate_goal_default_none(client, monkeypatch):
    """不传 goal 时 start_simulation 收到 None。"""
    from app.services.world_simulation import WorldSimulationService

    captured = {}

    def fake_start(cls, project_id, total_steps=6, time_step_minutes=30, goal=None,
                   time_mode="minutes", time_jumps=None, include_timeline=False):
        captured["goal"] = goal
        from app.services.world_simulation import WorldSimulationState
        return WorldSimulationState(
            simulation_id="ws_goal2", project_id=project_id, status="preparing"
        )

    monkeypatch.setattr(WorldSimulationService, "start_simulation", classmethod(fake_start))
    rv = client.post("/api/world/p1/simulate", json={"total_steps": 5})
    assert rv.status_code == 200
    assert captured["goal"] is None


def test_simulate_passes_narrative_time_mode(client, monkeypatch):
    """narrative 模式把 time_mode/time_jumps 透传给 start_simulation。"""
    from app.services.world_simulation import WorldSimulationService

    captured = {}

    def fake_start(cls, project_id, total_steps=6, time_step_minutes=30, goal=None,
                   time_mode="minutes", time_jumps=None, include_timeline=False):
        captured["time_mode"] = time_mode
        captured["time_jumps"] = time_jumps
        from app.services.world_simulation import WorldSimulationState
        return WorldSimulationState(
            simulation_id="ws_narr", project_id=project_id, status="preparing"
        )

    monkeypatch.setattr(WorldSimulationService, "start_simulation", classmethod(fake_start))
    rv = client.post(
        "/api/world/p1/simulate",
        json={"time_mode": "narrative", "time_jumps": ["数日后", "三个月后", "一年后"]},
    )
    assert rv.status_code == 200
    assert captured["time_mode"] == "narrative"
    assert captured["time_jumps"] == ["数日后", "三个月后", "一年后"]


def test_simulate_passes_include_timeline(client, monkeypatch):
    """include_timeline 透传给 start_simulation。"""
    from app.services.world_simulation import WorldSimulationService

    captured = {}

    def fake_start(cls, project_id, total_steps=6, time_step_minutes=30, goal=None,
                   time_mode="minutes", time_jumps=None, include_timeline=False):
        captured["include_timeline"] = include_timeline
        from app.services.world_simulation import WorldSimulationState
        return WorldSimulationState(
            simulation_id="ws_tl", project_id=project_id, status="preparing"
        )

    monkeypatch.setattr(WorldSimulationService, "start_simulation", classmethod(fake_start))
    rv = client.post("/api/world/p1/simulate", json={"include_timeline": True})
    assert rv.status_code == 200
    assert captured["include_timeline"] is True
