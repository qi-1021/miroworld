"""
t27 后台任务持久化 + 重启恢复测试：

1. 任务创建/更新时落盘（data/world-timeline/tasks/<task_id>.json 存在，内容一致）。
2. 重启恢复：持久化 status=running 的任务加载后变为 interrupted（stage=已中断、error 服务重启）。
3. completed 任务加载后保持 completed。
4. 加载幂等（_ensure_tasks_loaded 只加载一次）。
5. 懒加载入口触发（start_* / get_status 首次调用触发加载）。
"""
import json
import os

import pytest

from app.services import timeline_service as svc


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(svc, "_TASKS_DIR", str(tmp_path / "world-timeline" / "tasks"))
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False
    yield svc
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False


def _write_task(svc, task_id, status, **extra):
    os.makedirs(svc._TASKS_DIR, exist_ok=True)
    task = {"id": task_id, "status": status, "total_chunks": 0, "done_chunks": 0,
            "llm_ok": 0, "heuristic": 0, "message": "m", "stage": "s", "steps": [],
            "progress": 0, "started_at": "2026-08-15T10:00:00", "elapsed": 0.0, "error": ""}
    task.update(extra)
    with open(os.path.join(svc._TASKS_DIR, task_id + ".json"), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False)


def _reset_and_load(svc):
    """模拟重启：清空内存、置 _tasks_loaded=False，再触发加载。"""
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False
    svc._ensure_tasks_loaded()


# ---------------------------------------------------------------------------
# 1. 持久化文件存在
# ---------------------------------------------------------------------------
def test_task_persisted_on_create(tl_service):
    task_id = svc._new_task("tl_task", "任务已创建")
    path = os.path.join(svc._TASKS_DIR, task_id + ".json")
    assert os.path.exists(path), "创建任务应落盘"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["id"] == task_id
    assert data["status"] == "running"


def test_task_persisted_on_update(tl_service):
    task_id = svc._new_task("tl_fork", "分叉中")
    path = os.path.join(svc._TASKS_DIR, task_id + ".json")
    svc._update_task(task_id, stage="调用推演模型", progress=50)
    svc._task_log(task_id, "步骤日志")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["stage"] == "调用推演模型"
    assert data["progress"] == 50
    assert data["steps"] and "步骤日志" in data["steps"][-1]


# ---------------------------------------------------------------------------
# 2. 重启恢复：running → interrupted
# ---------------------------------------------------------------------------
def test_restart_running_becomes_interrupted(tl_service):
    _write_task(tl_service, "tl_task_abc", "running")
    _reset_and_load(tl_service)
    st = svc.get_status("tl_task_abc")
    assert st is not None
    assert st["status"] == "interrupted"
    assert st["stage"] == "已中断"
    assert st["error"] == "服务重启，任务中断"
    assert "请重新发起" in st["message"]
    assert any("服务重启" in s for s in st["steps"])


# ---------------------------------------------------------------------------
# 3. completed 保持
# ---------------------------------------------------------------------------
def test_restart_completed_kept(tl_service):
    _write_task(tl_service, "tl_task_done", "completed", progress=100)
    _reset_and_load(tl_service)
    st = svc.get_status("tl_task_done")
    assert st is not None
    assert st["status"] == "completed"
    assert st["progress"] == 100


# ---------------------------------------------------------------------------
# 4. 幂等
# ---------------------------------------------------------------------------
def test_lazy_load_idempotent(tl_service):
    _write_task(tl_service, "tl_task_x", "running")
    _reset_and_load(tl_service)
    # 第一次加载后 running 变 interrupted（内存态）
    assert svc.get_status("tl_task_x")["status"] == "interrupted"
    # 再次调用 _ensure_tasks_loaded 不应重复覆盖内存态（幂等，_tasks_loaded=True 短路）
    svc._task_log("tl_task_x", "又加了日志")
    with svc._task_lock:
        before = svc._tasks["tl_task_x"]["status"]
    svc._ensure_tasks_loaded()
    with svc._task_lock:
        after = svc._tasks["tl_task_x"]["status"]
    assert before == after == "interrupted"
    # 落盘文件里 status 应已被更新为 interrupted
    with open(os.path.join(tl_service._TASKS_DIR, "tl_task_x.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "interrupted"


# ---------------------------------------------------------------------------
# 5. 懒加载入口触发
# ---------------------------------------------------------------------------
def test_lazy_load_triggers_from_get_status(tl_service):
    _write_task(tl_service, "tl_task_y", "running")
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False
    # 首次 get_status 触发加载
    st = svc.get_status("tl_task_y")
    assert st is not None and st["status"] == "interrupted"
    assert svc._tasks_loaded is True


def test_lazy_load_triggers_from_new_task(tl_service):
    _write_task(tl_service, "tl_task_z", "running")
    with svc._task_lock:
        svc._tasks.clear()
    svc._tasks_loaded = False
    # start_fork / _new_task 触发加载（old task 被载入但保留，新任务被创建）
    task_id = svc._new_task("tl_fork", "新分叉")
    assert svc.get_status("tl_task_z")["status"] == "interrupted"
    assert svc.get_status(task_id)["status"] == "running"
