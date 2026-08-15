"""时间线任务状态文件保留清理测试。"""

import json
import os
import time

from app.services import timeline_service as svc


def _write_task(tmp_tasks, task_id, status, mtime_age_days):
    os.makedirs(tmp_tasks, exist_ok=True)
    path = os.path.join(tmp_tasks, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"id": task_id, "status": status}, f)
    old = time.time() - mtime_age_days * 86400
    os.utime(path, (old, old))
    return path


def test_prune_removes_old_non_running_only(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "_TASKS_DIR", str(tmp_path / "tasks"))
    _write_task(tmp_path / "tasks", "old_done", "completed", 200)
    _write_task(tmp_path / "tasks", "old_failed", "failed", 200)
    _write_task(tmp_path / "tasks", "recent", "completed", 1)
    _write_task(tmp_path / "tasks", "running_old", "running", 200)

    removed = svc.prune_old_task_files(retention_days=90)
    assert removed == 2
    remaining = sorted(os.listdir(tmp_path / "tasks"))
    assert remaining == ["recent.json", "running_old.json"]


def test_prune_skips_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "_TASKS_DIR", str(tmp_path / "no_such"))
    assert svc.prune_old_task_files(retention_days=30) == 0


def test_prune_uses_env_default(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "_TASKS_DIR", str(tmp_path / "tasks"))
    _write_task(tmp_path / "tasks", "old", "completed", 200)
    _write_task(tmp_path / "tasks", "new", "completed", 1)
    monkeypatch.setenv("TIMELINE_TASK_RETENTION_DAYS", "90")
    assert svc.prune_old_task_files() == 1
