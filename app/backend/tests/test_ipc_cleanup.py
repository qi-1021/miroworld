"""模拟 IPC 残留文件清理测试。"""

import json
import os
import time

from app.services.simulation_ipc import SimulationIPCClient
from app.services.world_simulation import WorldSimulationService, IPC_COMMANDS_DIR, IPC_RESPONSES_DIR


def _write_json(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"x": 1}, f)


def _age_file(path, seconds):
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_simulation_ipc_cleanup_removes_old_only(tmp_path):
    client = SimulationIPCClient(str(tmp_path))
    old_cmd = os.path.join(client.commands_dir, "old_cmd.json")
    new_cmd = os.path.join(client.commands_dir, "new_cmd.json")
    old_resp = os.path.join(client.responses_dir, "old_resp.json")
    _write_json(old_cmd)
    _write_json(new_cmd)
    _write_json(old_resp)
    _age_file(old_cmd, 7200)
    _age_file(old_resp, 7200)

    removed = client._cleanup_stale_files(max_age_seconds=3600)
    assert removed == 2
    assert os.path.exists(new_cmd)
    assert not os.path.exists(old_cmd)
    assert not os.path.exists(old_resp)


def test_world_simulation_ipc_cleanup(tmp_path):
    sim_dir = str(tmp_path / "sim")
    commands = os.path.join(sim_dir, IPC_COMMANDS_DIR)
    responses = os.path.join(sim_dir, IPC_RESPONSES_DIR)
    old = os.path.join(commands, "old.json")
    new = os.path.join(responses, "new.json")
    _write_json(old)
    _write_json(new)
    _age_file(old, 7200)

    removed = WorldSimulationService._cleanup_stale_ipc_files(
        sim_dir, max_age_seconds=3600
    )
    assert removed == 1
    assert not os.path.exists(old)
    assert os.path.exists(new)
