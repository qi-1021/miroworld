"""TaskManager 内存有界化测试。"""

from datetime import datetime, timedelta

from app.models.task import TaskManager, TaskStatus


def _reset(tm):
    with tm._task_lock:
        tm._tasks.clear()


def test_create_task_prunes_old_completed():
    tm = TaskManager()
    _reset(tm)

    # 先创建 205 个任务，再在锁内改成 completed 并设置递增时间
    done_ids = [tm.create_task(f"t{i}") for i in range(205)]
    base = datetime.now() - timedelta(days=1)
    with tm._task_lock:
        for i, tid in enumerate(done_ids):
            task = tm._tasks[tid]
            task.status = TaskStatus.COMPLETED
            task.updated_at = base + timedelta(seconds=i)

    # 一个正在运行的任务（最旧也应保留）
    running_id = tm.create_task("run")
    with tm._task_lock:
        tm._tasks[running_id].status = TaskStatus.PROCESSING

    # 再创建新任务，触发 prune（保留最多 200 个已完成/失败）
    new_id = tm.create_task("new")

    with tm._task_lock:
        statuses = {tid: t.status for tid, t in tm._tasks.items()}
    done_count = sum(1 for s in statuses.values() if s in (TaskStatus.COMPLETED, TaskStatus.FAILED))
    assert done_count <= 200
    assert statuses[running_id] == TaskStatus.PROCESSING
    assert statuses[new_id] == TaskStatus.PENDING


def test_prune_does_not_remove_pending_or_running():
    tm = TaskManager()
    _reset(tm)

    pending_ids = [tm.create_task(f"p{i}") for i in range(10)]
    running_id = tm.create_task("r")
    with tm._task_lock:
        for tid in pending_ids:
            tm._tasks[tid].status = TaskStatus.PENDING
        tm._tasks[running_id].status = TaskStatus.PROCESSING

    assert tm._prune_tasks(max_keep=5) == 0
    assert running_id in tm._tasks
