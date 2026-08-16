"""世界模拟质量/世界线操作回归测试（不联网，不启动真实子进程）"""

import json
import os
import time

import pytest

from app.services.world_simulation import (
    WorldSimulationService,
    WorldSimulationState,
)


@pytest.fixture()
def world_root(tmp_path):
    import app.services.world_simulation as ws

    original = ws.WORLD_SIM_ROOT
    ws.WORLD_SIM_ROOT = str(tmp_path / "world-sim")
    yield ws
    ws.WORLD_SIM_ROOT = original


def _make_state(project_id, sim_id, events, config=None, status="completed"):
    import app.services.world_simulation as ws_mod
    sim_dir = os.path.join(ws_mod.WORLD_SIM_ROOT, project_id, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    config_path = os.path.join(sim_dir, "world_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config or {"world": {"name": "测试世界", "total_steps": 6}}, f, ensure_ascii=False)
    events_path = os.path.join(sim_dir, "events.json")
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)
    state = WorldSimulationState(
        simulation_id=sim_id,
        project_id=project_id,
        status=status,
        config_path=config_path,
        events_path=events_path,
    )
    WorldSimulationService._save_state(state)
    return state


def _wait_status(sim_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = WorldSimulationService.get_state(sim_id)
        if s and s.status in ("completed", "failed"):
            return s
        time.sleep(0.05)
    return WorldSimulationService.get_state(sim_id)


def test_continue_simulation_keeps_history(world_root, monkeypatch):
    base = _make_state("p1", "sim_base", [{"step": 1, "id": "e1", "character_name": "卡拉"}])

    def fake_run(config_path, events_path, ipc_dir=None, extra_args=None):
        # 续推：读 resume_events + 追加新事件
        resume_path = extra_args[1]
        with open(resume_path, "r", encoding="utf-8") as f:
            kept = json.load(f)
        with open(events_path, "w", encoding="utf-8") as f:
            json.dump(kept + [{"step": 2, "id": "e2", "character_name": "艾拉"}], f, ensure_ascii=False)
        return "ok"

    monkeypatch.setattr(WorldSimulationService, "_run_simulation_subprocess", staticmethod(fake_run))
    state = WorldSimulationService.continue_simulation("sim_base", additional_steps=1)
    final = _wait_status(state.simulation_id)
    assert final.status == "completed"
    assert len(final.result["events"]) == 2
    assert final.result["meta"]["continue_base"] == "sim_base"


def test_rollback_keeps_events_before_target(world_root, monkeypatch):
    base = _make_state("p1", "sim_base", [
        {"step": 1, "id": "e1"}, {"step": 2, "id": "e2"}, {"step": 3, "id": "e3"},
    ])

    def fake_run(config_path, events_path, ipc_dir=None, extra_args=None):
        resume_path = extra_args[1]
        with open(resume_path, "r", encoding="utf-8") as f:
            kept = json.load(f)
        with open(events_path, "w", encoding="utf-8") as f:
            json.dump(kept + [{"step": 2, "id": "e2b"}], f, ensure_ascii=False)
        return "ok"

    monkeypatch.setattr(WorldSimulationService, "_run_simulation_subprocess", staticmethod(fake_run))
    state = WorldSimulationService.rollback_simulation("sim_base", target_step=2, additional_steps=1)
    final = _wait_status(state.simulation_id)
    assert final.status == "completed"
    # 只保留 step<2 的 1 条 + 新推 1 条
    assert len(final.result["events"]) == 2
    assert final.result["meta"]["target_step"] == 2


def test_merge_simulations_offsets_steps(world_root):
    _make_state("p1", "sim_a", [{"step": 1, "id": "a1"}, {"step": 2, "id": "a2"}])
    _make_state("p1", "sim_b", [{"step": 1, "id": "b1"}])
    merged = WorldSimulationService.merge_simulations("sim_a", "sim_b")
    assert merged.result["event_count"] == 3
    steps = [e["step"] for e in merged.result["events"]]
    assert steps == [1, 2, 3]
    assert merged.result["meta"]["merge_base"] == "sim_a"
    assert merged.result["meta"]["merge_branch"] == "sim_b"


def test_copy_simulation_to_project(world_root):
    _make_state("p1", "sim_a", [{"step": 1, "id": "a1"}])
    copied = WorldSimulationService.copy_simulation_to_project("sim_a", "p2")
    assert copied.project_id == "p2"
    assert copied.status == "completed"
    assert copied.result["meta"]["copy_from"] == "sim_a"
