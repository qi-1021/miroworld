"""端到端 CLI 冒烟测试（不依赖 LLM/网络）"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CLI = BACKEND / "scripts" / "mirofish_cli.py"


def _run_cli(*args):
    env = {"PYTHONPATH": str(BACKEND)}
    proc = subprocess.run(
        [sys.executable, str(CLI), *args, "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc


def test_cli_health():
    proc = _run_cli("health")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert "checks" in data["data"]


def test_cli_project_list():
    proc = _run_cli("project", "list")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["success"] is True


def test_cli_backup(tmp_path):
    out = tmp_path / "backup"
    proc = _run_cli("backup", "--output", str(out))
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert Path(data["data"]["backup_dir"]).exists()
