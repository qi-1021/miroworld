"""世界模拟服务测试（不联网，不启动子进程）"""

import json
import os

import pytest

from app.services.world_bible import WorldBibleService
from app.services.world_simulation import (
    WorldSimulationService,
    WorldSimulationState,
)


@pytest.fixture()
def world_root(tmp_path):
    """隔离世界数据目录"""
    import app.services.world_bible as wb
    import app.services.world_simulation as ws

    original_wb = wb.WORLD_DATA_ROOT
    original_ws = ws.WORLD_SIM_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    ws.WORLD_SIM_ROOT = str(tmp_path / "world-sim")
    yield ws
    wb.WORLD_DATA_ROOT = original_wb
    ws.WORLD_SIM_ROOT = original_ws


class FakeLLM:
    """模拟 LLM：返回预设的世界配置"""

    def __init__(self, config=None):
        self.config = config or {
            "world": {"name": "测试世界", "time_step_minutes": 30, "total_steps": 4, "initial_time": "2026-01-01 08:00"},
            "locations": [
                {"id": "market", "name": "集市", "description": "热闹的广场"},
                {"id": "gate", "name": "城门", "description": "城防要地"},
            ],
            "connections": [["market", "gate"]],
            "characters": [
                {"id": "kara", "name": "卡拉", "persona": "铁匠", "location": "market", "goal": "卖剑", "knowledge": ["铁匠"]},
                {"id": "aira", "name": "艾拉", "persona": "平民", "location": "gate", "goal": "看城门", "knowledge": ["城门"]},
            ],
            "rules": [{"id": "no_fire", "description": "城镇内禁止火焰魔法"}],
        }
        self.model = "fake-model"
        self.base_url = "https://fake"
        self.api_key = "fake-key"
        self.calls = 0

    def chat_json(self, messages, temperature=0.3, max_tokens=8192, **kwargs):
        self.calls += 1
        return json.loads(json.dumps(self.config))


def test_generate_world_config_with_fake_llm(world_root):
    WorldBibleService.save_input(
        "p1",
        background="龙裔王国建于三百年前，首都龙脊城。魔法需要代价。",
        story="清晨，卡拉在集市打铁。艾拉去看城门。",
    )
    llm = FakeLLM()
    config = WorldSimulationService._generate_world_config(
        "p1", "背景文本", "正文文本", llm
    )
    assert config["world"]["name"] == "测试世界"
    assert len(config["characters"]) == 2
    assert len(config["locations"]) == 2
    assert config["llm"]["model"] == "fake-model"
    assert config["llm"]["api_key"] == "fake-key"


def test_generate_world_config_invalid(world_root):
    llm = FakeLLM(config={"world": {}})  # 缺 characters/locations
    with pytest.raises(ValueError, match="缺少必需字段"):
        WorldSimulationService._generate_world_config("p1", "bg", "st", llm)


def test_start_requires_world_input(world_root):
    with pytest.raises(ValueError, match="尚未提交世界输入"):
        WorldSimulationService.start_simulation("nope")


def test_state_save_and_load(world_root):
    state = WorldSimulationState(
        simulation_id="ws1", project_id="p1", status="completed",
        result={"event_count": 3},
    )
    WorldSimulationService._save_state(state)
    loaded = WorldSimulationService.get_state("ws1")
    assert loaded is not None
    assert loaded.simulation_id == "ws1"
    assert loaded.status == "completed"
    assert loaded.result["event_count"] == 3
    assert WorldSimulationService.get_state("missing") is None


def test_list_simulations(world_root):
    for i in range(3):
        state = WorldSimulationState(
            simulation_id=f"ws{i}", project_id="p1", status="completed",
        )
        WorldSimulationService._save_state(state)
    sims = WorldSimulationService.list_simulations("p1")
    assert len(sims) == 3
    # 其他项目隔离
    other = WorldSimulationState(simulation_id="wsx", project_id="p2", status="created")
    WorldSimulationService._save_state(other)
    assert len(WorldSimulationService.list_simulations("p1")) == 3
    assert len(WorldSimulationService.list_simulations("p2")) == 1


def test_get_simulation_python_falls_back(world_root, monkeypatch):
    monkeypatch.delenv("SIMULATION_PYTHON", raising=False)
    python = WorldSimulationService._get_simulation_python()
    assert python  # 应为 .venv-simulation 路径或 'python'


def test_build_llm_client_falls_back_to_registry(world_root):
    """项目无绑定时应回退到注册表第一个已验证模型（或默认配置）"""
    client = WorldSimulationService._build_llm_client("p1")
    assert client is not None


# ---------------- 事件回写图谱 ----------------

def _fake_project(graph_id):
    """构造带指定 graph_id 的 Project 对象（绕过文件 IO）"""
    from app.models.project import Project, ProjectStatus
    return Project(
        project_id="p1",
        name="测试",
        status=ProjectStatus.GRAPH_COMPLETED,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        graph_id=graph_id,
    )


def test_write_events_to_graph_ok(world_root, monkeypatch):
    """有一条目：有图谱 + 有事件 → 正常回写，返回 ok 与 episode_uuid"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    monkeypatch.setattr(
        ProjectManager, "get_project",
        classmethod(lambda cls, pid: _fake_project("graph-1")),
    )
    captured = {}

    class FakeClient:
        def add_episode(self, graph_id, data, episode_type="text"):
            captured["graph_id"] = graph_id
            captured["data"] = data
            captured["episode_type"] = episode_type
            return "episode-cf45"

    monkeypatch.setattr(zep_factory, "get_zep_client", lambda: FakeClient())

    events = [
        {
            "time": "2026-01-01 08:00",
            "character_name": "卡拉",
            "location": "集市",
            "action_desc": "打铁",
            "result": "打造出利剑",
            "approved": True,
        },
        {
            "time": "2026-01-01 08:30",
            "character_name": "艾拉",
            "location": "城门",
            "action_desc": "放火",
            "result": "被规则阻止",
            "approved": False,
        },
    ]
    result = WorldSimulationService._write_events_to_graph("p1", events)
    assert result["status"] == "ok"
    assert result["graph_id"] == "graph-1"
    assert result["episode_uuid"] == "episode-cf45"
    assert result["event_count"] == 2
    # 校验客户端收到的参数
    assert captured["graph_id"] == "graph-1"
    assert captured["episode_type"] == "text"
    assert "卡拉" in captured["data"]
    assert "（被规则阻止）" in captured["data"]  # 未通过的事件带标记


def test_write_events_to_graph_no_graph(world_root, monkeypatch):
    """无图谱：项目存在但 graph_id 为空 → 跳过回写"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    monkeypatch.setattr(
        ProjectManager, "get_project",
        classmethod(lambda cls, pid: _fake_project(None)),
    )
    called = {"flag": False}

    def fake_client():
        called["flag"] = True
        raise AssertionError("不应在有图的情况下不调用 add_episode")

    monkeypatch.setattr(zep_factory, "get_zep_client", fake_client)
    result = WorldSimulationService._write_events_to_graph(
        "p1", [{"time": "t", "character_name": "卡拉", "action_desc": "打铁"}]
    )
    assert result["status"] == "skipped"
    assert "尚未构建图谱" in result["reason"]
    assert not called["flag"]  # 未构造客户端


def test_write_events_to_graph_no_project(world_root, monkeypatch):
    """项目不存在（get_project 返回 None）→ 视为无图谱跳过"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    monkeypatch.setattr(
        ProjectManager, "get_project",
        classmethod(lambda cls, pid: None),
    )
    monkeypatch.setattr(
        zep_factory, "get_zep_client",
        lambda: (_ for _ in ()).throw(AssertionError("不应构造客户端")),
    )
    result = WorldSimulationService._write_events_to_graph(
        "p1", [{"character_name": "卡拉"}]
    )
    assert result["status"] == "skipped"


def test_write_events_to_graph_no_events(world_root, monkeypatch):
    """无事件：事件列表为空 → 直接跳过，不触碰项目/客户端"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    called = {"get_project": False, "client": False}

    def fake_get_project(pid):
        called["get_project"] = True
        return _fake_project("graph-1")

    monkeypatch.setattr(ProjectManager, "get_project", classmethod(fake_get_project))
    monkeypatch.setattr(
        zep_factory, "get_zep_client",
        lambda: (called.__setitem__("client", True) or None),
    )
    result = WorldSimulationService._write_events_to_graph("p1", [])
    assert result["status"] == "skipped"
    assert "无事件" in result["reason"]
    assert not called["get_project"]
    assert not called["client"]


def test_write_events_to_graph_error(world_root, monkeypatch):
    """异常：add_episode 抛异常 → 返回 error 而不是抛出"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    monkeypatch.setattr(
        ProjectManager, "get_project",
        classmethod(lambda cls, pid: _fake_project("graph-1")),
    )

    class BoomClient:
        def add_episode(self, *args, **kwargs):
            raise RuntimeError("Neo4j 连接断开")

    monkeypatch.setattr(zep_factory, "get_zep_client", lambda: BoomClient())
    result = WorldSimulationService._write_events_to_graph(
        "p1", [{"character_name": "卡拉"}]
    )
    assert result["status"] == "error"
    assert "Neo4j 连接断开" in result["error"]


def test_write_events_to_graph_get_project_raises(world_root, monkeypatch):
    """读取项目异常 → 返回 error"""
    from app.models.project import ProjectManager
    from app.services import zep_factory

    def boom(cls, pid):
        raise FileNotFoundError("meta 丢失")

    monkeypatch.setattr(ProjectManager, "get_project", classmethod(boom))
    monkeypatch.setattr(
        zep_factory, "get_zep_client",
        lambda: (_ for _ in ()).throw(AssertionError("不应构造客户端")),
    )
    result = WorldSimulationService._write_events_to_graph(
        "p1", [{"character_name": "卡拉"}]
    )
    assert result["status"] == "error"
    assert "meta 丢失" in result["error"]


# ---------------- 世界模拟 IPC 控制 ----------------

def _make_state(world_root, sim_id="ws_ctl"):
    """构造一个 running 状态的模拟并落盘"""
    from app.services.world_simulation import WorldSimulationState
    state = WorldSimulationState(
        simulation_id=sim_id,
        project_id="p1",
        status="running",
    )
    WorldSimulationService._save_state(state)
    return state


def test_control_rejects_invalid_action(world_root):
    _make_state(world_root)
    with pytest.raises(ValueError, match="不支持的控制动作"):
        WorldSimulationService.control_simulation("p1", "ws_ctl", "dance")


def test_control_pause_requires_state(world_root):
    # 模拟不存在
    with pytest.raises(ValueError, match="模拟不存在"):
        WorldSimulationService.control_simulation("p1", "missing", "pause")


def test_control_pause_writes_command(world_root):
    _make_state(world_root)
    result = WorldSimulationService.control_simulation("p1", "ws_ctl", "pause")
    sim_dir = WorldSimulationService._sim_dir("p1", "ws_ctl")
    cmd_dir = os.path.join(sim_dir, "ipc_commands")
    assert os.path.isdir(cmd_dir)
    # 命令文件存在
    files = [f for f in os.listdir(cmd_dir) if f.endswith(".json")]
    assert len(files) == 1
    with open(os.path.join(cmd_dir, files[0]), 'r', encoding='utf-8') as f:
        cmd = json.load(f)
    assert cmd["command_type"] == "pause"
    assert cmd["command_id"] == result["command_id"]
    # 状态更新为 paused
    state = WorldSimulationService.get_state("ws_ctl")
    assert state.status == "paused"
    assert state.paused is True


def test_control_resume_and_stop_write_commands(world_root):
    _make_state(world_root)
    WorldSimulationService.control_simulation("p1", "ws_ctl", "pause")
    WorldSimulationService.control_simulation("p1", "ws_ctl", "resume")
    state = WorldSimulationService.get_state("ws_ctl")
    assert state.status == "running"
    assert state.paused is False

    WorldSimulationService.control_simulation("p1", "ws_ctl", "stop")
    state = WorldSimulationService.get_state("ws_ctl")
    assert state.status == "stopped"
    assert state.paused is False


def test_control_interview_requires_prompt_and_character(world_root):
    _make_state(world_root)
    with pytest.raises(ValueError, match="必须提供 prompt"):
        WorldSimulationService.control_simulation(
            "p1", "ws_ctl", "interview", character_name="卡拉"
        )
    with pytest.raises(ValueError, match="必须提供 character_name"):
        WorldSimulationService.control_simulation(
            "p1", "ws_ctl", "interview", prompt="你在哪？"
        )


def test_control_interview_reads_response(world_root):
    """interview：模拟端在后台写入响应后，control 应读到并返回结果"""
    import threading
    import time as _t
    _make_state(world_root)
    sim_dir = WorldSimulationService._sim_dir("p1", "ws_ctl")
    os.makedirs(os.path.join(sim_dir, "ipc_responses"), exist_ok=True)

    # 后台线程：检测到命令文件后写入对应响应（模拟子进程行为）
    def simulate_subprocess():
        cmd_dir = os.path.join(sim_dir, "ipc_commands")
        for _ in range(200):
            files = [f for f in os.listdir(cmd_dir) if f.endswith(".json")] if os.path.isdir(cmd_dir) else []
            if not files:
                _t.sleep(0.02)
                continue
            cid = files[0].replace(".json", "")
            resp = {
                "command_id": cid,
                "status": "completed",
                "result": {"character_name": "卡拉", "answer": "我在集市。", "prompt": "你在哪？"},
                "error": None,
                "timestamp": "",
            }
            with open(os.path.join(sim_dir, "ipc_responses", f"{cid}.json"), 'w', encoding='utf-8') as f:
                json.dump(resp, f, ensure_ascii=False, indent=2)
            return  # 只处理一条命令

    thread = threading.Thread(target=simulate_subprocess, daemon=True)
    thread.start()
    out = WorldSimulationService.control_simulation(
        "p1", "ws_ctl", "interview", character_name="卡拉", prompt="你在哪？",
        timeout=5.0, poll_interval=0.05,
    )
    thread.join(timeout=6)
    assert out["status"] == "completed"
    assert out["result"]["answer"] == "我在集市。"


def test_control_interview_timeout(world_root):
    """interview：无响应时应抛超时"""
    _make_state(world_root)
    with pytest.raises(TimeoutError):
        WorldSimulationService.control_simulation(
            "p1", "ws_ctl", "interview",
            character_name="卡拉", prompt="你在哪？",
            timeout=0.2, poll_interval=0.05,
        )
