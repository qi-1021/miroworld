"""TaskManager 磁盘持久化与重启恢复测试。"""

import os

from app.models.task import TaskManager, TaskStatus


def _reset(tm):
    with tm._task_lock:
        tm._tasks.clear()


def test_persist_and_restore_completed(tmp_path):
    tm = TaskManager()
    _reset(tm)
    old_dir = tm.PERSIST_DIR
    tm.PERSIST_DIR = str(tmp_path)
    try:
        tid = tm.create_task("graph_build")
        tm.complete_task(tid, {"graph_id": "g1"})

        # 模拟重启：清空内存后从磁盘恢复
        _reset(tm)
        assert tm.load_persisted() == 1
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"graph_id": "g1"}
    finally:
        tm.PERSIST_DIR = old_dir
        _reset(tm)


def test_restore_marks_processing_as_failed(tmp_path):
    tm = TaskManager()
    _reset(tm)
    old_dir = tm.PERSIST_DIR
    tm.PERSIST_DIR = str(tmp_path)
    try:
        tid = tm.create_task("graph_build")
        tm.update_task(tid, status=TaskStatus.PROCESSING, progress=40)

        _reset(tm)
        assert tm.load_persisted() == 1
        task = tm.get_task(tid)
        assert task.status == TaskStatus.FAILED
        assert "服务重启" in task.error
    finally:
        tm.PERSIST_DIR = old_dir
        _reset(tm)


def test_persist_noop_when_dir_none():
    tm = TaskManager()
    _reset(tm)
    old_dir = tm.PERSIST_DIR
    tm.PERSIST_DIR = None
    try:
        tid = tm.create_task("x")
        tm.complete_task(tid, {})
        assert tm.load_persisted() == 0
    finally:
        tm.PERSIST_DIR = old_dir
        _reset(tm)
