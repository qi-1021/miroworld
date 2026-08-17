"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import os
import json
import uuid
import threading
import contextvars
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..utils.atomic_json import atomic_write_json

# 当前线程 / 协程上下文的任务 ID 追踪
_current_task_var = contextvars.ContextVar('current_task_id', default=None)


def set_current_task_id(task_id: Optional[str]):
    """设置当前上下文关联的任务 ID"""
    _current_task_var.set(task_id)


def get_current_task_id() -> Optional[str]:
    """获取当前上下文关联的任务 ID"""
    return _current_task_var.get()


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息
    logs: list = field(default_factory=list)  # 实时阶段过程日志
    llm_exchanges: list = field(default_factory=list)  # 实时大模型输入与输出明细

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "logs": self.logs,
            "llm_exchanges": self.llm_exchanges,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """从字典恢复任务对象。"""
        from datetime import datetime
        return cls(
            task_id=data["task_id"],
            task_type=data.get("task_type", ""),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            progress=data.get("progress", 0),
            message=data.get("message", ""),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            progress_detail=data.get("progress_detail", {}),
            logs=data.get("logs", []),
            llm_exchanges=data.get("llm_exchanges", []),
        )


class TaskManager:
    """
    任务管理器
    线程安全的任务状态管理
    """

    _instance = None
    _lock = threading.Lock()
    # 生产环境由 create_app 设置为 data/task-manager；测试默认 None 不落盘
    PERSIST_DIR: Optional[str] = None

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
        return cls._instance

    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务

        Args:
            task_type: 任务类型
            metadata: 额外元数据

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()

        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )

        with self._task_lock:
            self._tasks[task_id] = task

        # 创建新任务时顺带清理最旧的已完成/失败任务，避免长期运行内存无限增长
        self._prune_tasks()

        # 生产环境持久化，重启后任务可恢复（避免前端查询 404）
        self._persist_task(task_id)

        return task_id

    def _prune_tasks(self, max_keep: int = 200) -> int:
        """清理最旧的已完成/失败任务，保留运行/等待任务。

        Args:
            max_keep: 最多保留多少个已完成/失败任务（默认 200）

        Returns:
            本次清理数量
        """
        with self._task_lock:
            done = [
                (tid, task.updated_at)
                for tid, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            ]
            if len(done) <= max_keep:
                return 0
            done.sort(key=lambda item: item[1])
            removed = len(done) - max_keep
            for tid, _ in done[:removed]:
                self._tasks.pop(tid, None)
            return removed

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._task_lock:
            return self._tasks.get(task_id)

    def _task_path(self, task_id: str) -> str:
        return os.path.join(self.PERSIST_DIR, f"{task_id}.json")

    def _persist_task(self, task_id: str) -> None:
        """将单个任务原子写入 PERSIST_DIR（未配置时 no-op）。"""
        if not self.PERSIST_DIR:
            return
        try:
            os.makedirs(self.PERSIST_DIR, exist_ok=True)
            with self._task_lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                data = task.to_dict()
            atomic_write_json(self._task_path(task_id), data)
        except Exception as e:
            logger = __import__('logging').getLogger('mirofish.task')
            logger.warning(f"持久化任务失败（忽略）: {task_id}, {e}")

    def load_persisted(self) -> int:
        """从磁盘加载任务状态（生产环境启动时调用）。

        - PENDING/PROCESSING 在重启后已无法继续执行 → 标记 FAILED（error 说明服务重启中断）；
        - COMPLETED/FAILED 原样保留；
        - 已存在于内存的任务不覆盖。
        """
        if not self.PERSIST_DIR or not os.path.isdir(self.PERSIST_DIR):
            return 0
        loaded = 0
        for fn in os.listdir(self.PERSIST_DIR):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self.PERSIST_DIR, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict) or not data.get("task_id"):
                    continue
                task = Task.from_dict(data)
                if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
                    task.status = TaskStatus.FAILED
                    task.error = "服务重启，任务中断"
                    task.message = "任务已中断，请重新发起"
                with self._task_lock:
                    if task.task_id not in self._tasks:
                        self._tasks[task.task_id] = task
                        loaded += 1
            except Exception as e:
                logger = __import__('logging').getLogger('mirofish.task')
                logger.warning(f"恢复任务状态失败（跳过）: {path}, {e}")
        return loaded

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None,
        log: Optional[str] = None,
    ):
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
            log: 追加的日志行
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task.updated_at = datetime.now()
                now_str = datetime.now().strftime("%H:%M:%S")
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                    if message.strip():
                        entry = f"[{now_str}] {message.strip()}"
                        if not task.logs or task.logs[-1] != entry:
                            task.logs.append(entry)
                if log is not None and log.strip():
                    task.logs.append(f"[{now_str}] {log.strip()}")
                if len(task.logs) > 2000:
                    task.logs = task.logs[-2000:]
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                    task.logs.append(f"[{now_str}] ❌ 错误: {error}")
                if progress_detail is not None:
                    task.progress_detail = progress_detail

        # 生产环境持久化：每次状态变更都落盘
        self._persist_task(task_id)

    def add_log(self, task_id: str, log: str):
        """为任务追加单条实时日志"""
        self.update_task(task_id, log=log)

    def add_llm_exchange(self, task_id: str, exchange: Dict[str, Any]):
        """追加大模型输入输出交互明细（保持内存轻量，杜绝轮询网络传输暴增）"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task.updated_at = datetime.now()
                task.llm_exchanges.append(exchange)
                if len(task.llm_exchanges) > 60:
                    task.llm_exchanges = task.llm_exchanges[-60:]
        self._persist_task(task_id)


    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="任务完成",
            result=result
        )

    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message="任务失败",
            error=error
        )

    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """列出任务"""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)

        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]


def record_current_task_llm(stage: str, model: str, prompt: str, response: str, duration: float = 0.0):
    """便捷辅助函数：记录当前上下文任务的 LLM 输入与输出"""
    task_id = get_current_task_id()
    if not task_id:
        return
    now_str = datetime.now().strftime("%H:%M:%S")
    prompt_clean = str(prompt or "").strip()
    resp_clean = str(response or "").strip()
    exchange = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": now_str,
        "stage": stage,
        "model": model,
        "duration_sec": round(duration, 2),
        "prompt_preview": (prompt_clean[:300] + "...") if len(prompt_clean) > 300 else prompt_clean,
        "full_prompt": prompt_clean,
        "response_preview": (resp_clean[:350] + "...") if len(resp_clean) > 350 else resp_clean,
        "full_response": resp_clean,
    }
    TaskManager().add_llm_exchange(task_id, exchange)

