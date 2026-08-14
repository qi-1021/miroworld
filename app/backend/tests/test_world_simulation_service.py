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
