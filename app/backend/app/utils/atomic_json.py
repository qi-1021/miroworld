"""原子文件写入工具。

本地应用频繁把运行状态/任务/报告写回磁盘；直接用 open(path, 'w') 写一半崩溃
会留下损坏的 JSON，导致下次启动读取失败。本模块统一提供：
- atomic_write_json：同目录临时文件 + fsync + os.replace（崩溃时旧文件完整保留）
- atomic_write_text：纯文本版本（报告 md、日志快照等）

使用方式与 json.dump 类似；失败会抛出异常，由调用方决定是告警降级还是向上传播。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional


def atomic_write_text(path: str, text: str) -> None:
    """原子写入文本文件（先写同目录临时文件，再 os.replace）。"""
    path = os.path.abspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, payload: Any, indent: int = 2) -> None:
    """原子写入 JSON 文件。"""
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write_text(path, text)


def atomic_write_json_safe(
    path: str,
    payload: Any,
    indent: int = 2,
    logger: Optional[Any] = None,
    what: str = "文件",
) -> bool:
    """原子写入 JSON；失败只记录警告并返回 False（用于状态旁路，不阻断主流程）。"""
    try:
        atomic_write_json(path, payload, indent=indent)
        return True
    except Exception as exc:
        if logger is not None:
            logger.warning(f"写入{what}失败（忽略继续）: {exc}")
        return False


def atomic_write_bytes(path: str, data: bytes) -> None:
    """原子写入二进制文件（如 .npy 向量矩阵）。"""
    path = os.path.abspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
