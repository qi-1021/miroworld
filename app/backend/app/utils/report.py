"""
错误报告生成工具
================
面向非技术测试人员：一条命令/一次 API 调用即可生成本地报告压缩包
（系统信息 + 运行日志 + 失败任务记录），手动发送给维护者排查问题。

安全约定：
- 所有写入报告的文字内容都经过 sanitize_text 打码（API 密钥/密码等 → [REDACTED]）；
- 绝不收集 app/.env、app/data/model-config/、secrets.json 等敏感文件；
- 日志只取每个文件尾部最多 max_bytes_per_file 字节。
"""

from __future__ import annotations

import json
import locale
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

# 目录约定（与 logger.py / task.py 保持一致）
BACKEND_DIR = Path(__file__).resolve().parents[2]          # app/backend
DATA_DIR = BACKEND_DIR / "data"                            # app/backend/data
TASK_MANAGER_DIR = DATA_DIR / "task-manager"               # 失败任务记录目录
LOG_DIR = BACKEND_DIR / "logs"                             # 后端日志目录

# 路径参数类型：接受 str 或 Path
PathLike = Union[str, Path]

# 每个日志文件最多收集的字节数（默认 200KB，只取尾部）
DEFAULT_MAX_LOG_BYTES = 200 * 1024
# 失败任务日志尾部最多保留的行数
TASK_LOG_TAIL_LINES = 50


# ---------------------------------------------------------------------------
# 敏感信息打码
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{8,}", re.IGNORECASE),          # OpenAI 风格密钥
    re.compile(r"api[_-]?key\s*[=:]\s*\S+", re.IGNORECASE),    # 任意 *_API_KEY=xxx
    re.compile(r"LLM_API_KEY\s*[=:]\s*\S+", re.IGNORECASE),    # 显式兜底
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),                # Bearer Token
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),       # 密码
    re.compile(r"AKIA[A-Z0-9]{16}"),                            # AWS Access Key
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),                     # GitHub Token (ghp_/gho_/ghu_/ghs_/ghr_)
    re.compile(r"(client_)?secret\s*[=:]\s*\S+", re.IGNORECASE),  # 通用 secret 赋值
    re.compile(r"-----BEGIN .*PRIVATE KEY-----"),               # PEM 私钥头
    re.compile(r"(neo4j|mysql|postgres|mongodb)://\w+:\w+@"),   # 带密码的数据库连接串
]


def sanitize_text(text: Any) -> str:
    """把文本中的密钥/密码类内容替换为 [REDACTED]（大小写不敏感）。"""
    if text is None:
        return ""
    result = str(text)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


# ---------------------------------------------------------------------------
# 系统信息收集
# ---------------------------------------------------------------------------

def _run_version_cmd(cmd: list) -> str:
    """运行版本命令并返回第一行输出；失败/超时返回空串（容忍）。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def _disk_free(path: Path) -> int:
    """返回目录所在磁盘的剩余字节数；失败返回 0。"""
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def _get_locale() -> str:
    """返回当前语言环境（如 zh_CN.UTF-8）；失败返回空串。"""
    try:
        lang, enc = locale.getlocale()
        if lang:
            return f"{lang}.{enc}" if enc else lang
    except Exception:
        pass
    try:
        return locale.getdefaultlocale()[0] or ""
    except Exception:
        return ""


def collect_system_info() -> dict:
    """收集系统信息，供错误报告使用。"""
    info = {
        "platform": platform.platform(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "machine": platform.machine(),
        "python_version": sys.version.split()[0],
        "node_version": _run_version_cmd(["node", "--version"]),
        "java_version": _run_version_cmd(["java", "-version"]),
        "disk_free_bytes": _disk_free(DATA_DIR),
        "locale": _get_locale(),
        "current_time": datetime.now().isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
    }
    # 内存信息：psutil 可用时补充，否则跳过
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["memory_total_bytes"] = vm.total
        info["memory_available_bytes"] = vm.available
    except Exception:
        pass
    return info


def _format_system_info(info: dict) -> str:
    lines = [f"{k}: {v}" for k, v in info.items()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 日志收集
# ---------------------------------------------------------------------------

def _read_tail(path: Path, max_bytes: int) -> str:
    """读取文件尾部最多 max_bytes 字节（UTF-8，容忍乱码）。"""
    size = os.path.getsize(path)
    if size <= max_bytes:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    with open(path, "rb") as f:
        f.seek(-max_bytes, os.SEEK_END)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def collect_logs(log_dir: Optional[PathLike] = None,
                 max_bytes_per_file: int = DEFAULT_MAX_LOG_BYTES) -> list[dict]:
    """收集日志文件尾部内容。

    扫描 log_dir（默认 app/backend/logs）下所有 *.log 文件，
    并额外包含 install.log（若存在于项目根目录或日志目录）。
    返回 [{name, content}]；不可读文件自动跳过。
    """
    log_dir = Path(log_dir) if log_dir else Path(LOG_DIR)

    files: list[Path] = []
    if log_dir.is_dir():
        files.extend(sorted(log_dir.glob("*.log")))

    # install.log：项目根目录 / app 根目录 / 日志目录 三处候选
    for cand in (BACKEND_DIR.parents[1] / "install.log",
                 BACKEND_DIR.parent / "install.log",
                 log_dir / "install.log"):
        if cand.is_file() and cand not in files:
            files.append(cand)

    result: list[dict] = []
    for f in files:
        try:
            result.append({
                "name": f.name,
                "content": _read_tail(f, max_bytes_per_file),
            })
        except Exception:
            # 不可读文件跳过，不影响整体报告
            continue
    return result


# ---------------------------------------------------------------------------
# 失败任务收集
# ---------------------------------------------------------------------------

def collect_task_failures(persist_dir: Optional[PathLike] = None, limit: int = 20) -> list[dict]:
    """扫描任务持久化目录，收集 status == "failed" 的任务。

    返回 [{task_id, created_at, message, error, logs_tail}]，按创建时间倒序。
    """
    persist_dir = Path(persist_dir) if persist_dir else Path(TASK_MANAGER_DIR)
    failures: list[dict] = []
    if not persist_dir.is_dir():
        return failures

    for f in sorted(persist_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("status") != "failed":
            continue
        logs = data.get("logs") or []
        failures.append({
            "task_id": data.get("task_id", ""),
            "created_at": data.get("created_at", ""),
            "message": data.get("message", ""),
            "error": data.get("error", ""),
            "logs_tail": "\n".join(str(x) for x in logs[-TASK_LOG_TAIL_LINES:]),
        })
        if len(failures) >= limit:
            break

    # 按创建时间倒序（最新失败在前）
    failures.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return failures


def _format_task_failures(failures: list[dict]) -> str:
    if not failures:
        return "（没有发现失败的任务记录）"
    blocks = []
    for i, f in enumerate(failures, 1):
        blocks.append(
            f"--- 失败任务 {i} ---\n"
            f"任务ID: {f.get('task_id', '')}\n"
            f"创建时间: {f.get('created_at', '')}\n"
            f"状态消息: {f.get('message', '')}\n"
            f"错误信息:\n{f.get('error', '')}\n"
            f"日志尾部:\n{f.get('logs_tail', '')}\n"
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# 报告打包
# ---------------------------------------------------------------------------

def _default_output_dir() -> Path:
    """默认输出目录：macOS/Windows 桌面，其他系统用用户主目录。"""
    if sys.platform == "darwin":
        return Path.home() / "Desktop"
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return Path.home()


_README_TEXT = """Miroworld 错误报告
====================

这是什么？
本文件包是 Miroworld 自动生成的错误报告，用于帮助维护者定位您遇到的问题。

包含什么？
- system-info.txt：您的系统信息（操作系统、Python/Node 版本、磁盘空间等）
- logs/：后端运行日志（每个文件只包含最近一部分）
- task-failures.txt：最近失败的后台任务记录
- frontend-errors.txt：前端页面报错（如有）
- description.txt：您填写的问题描述（如有）

如何发送给维护者？
1. 将本压缩包（miroworld-report-*.zip）通过微信、邮件等方式发送给维护者；
2. 在消息中简单描述您遇到的问题（例如：点击"生成报告"后页面没有反应）；
3. 如果方便，请附上问题发生的大致时间，方便维护者对照日志。

隐私说明
- 本报告只包含系统信息与运行日志，不包含任何 API 密钥、密码等敏感信息；
- 报告中的密钥类内容会被自动打码（显示为 [REDACTED]）；
- 请勿在发送前自行修改报告内容。
"""


def build_report(output_dir: Optional[PathLike] = None,
                 description: str = "",
                 frontend_errors: Optional[list] = None) -> dict:
    """生成错误报告压缩包。

    在 output_dir（默认桌面）下用 tempfile.mkdtemp 创建唯一临时目录
    miroworld-report-*/，写入系统信息、日志、失败任务、前端错误、描述与 README，
    全部内容经 sanitize_text 打码后打包为同名 zip，随后删除临时目录。
    mkdtemp 保证并发调用也不会撞到同一个目录。

    返回 {"report_path", "report_dir", "files", "size_bytes"}。
    """
    output_dir = Path(output_dir) if output_dir else _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # mkdtemp 生成唯一目录名，避免并发请求互相覆盖临时文件
    folder = Path(tempfile.mkdtemp(prefix="miroworld-report-", dir=output_dir))
    folder_name = folder.name
    logs_sub = folder / "logs"
    logs_sub.mkdir(parents=True, exist_ok=True)

    # 1) 系统信息
    (folder / "system-info.txt").write_text(
        sanitize_text(_format_system_info(collect_system_info())),
        encoding="utf-8",
    )

    # 2) 日志（每个文件单独写入 logs/ 子目录）
    for entry in collect_logs():
        try:
            (logs_sub / entry["name"]).write_text(
                sanitize_text(entry["content"]), encoding="utf-8")
        except Exception:
            continue

    # 3) 失败任务记录
    (folder / "task-failures.txt").write_text(
        sanitize_text(_format_task_failures(collect_task_failures())),
        encoding="utf-8",
    )

    # 4) 前端错误（可选）
    if frontend_errors:
        items = frontend_errors if isinstance(frontend_errors, list) else [frontend_errors]
        lines = []
        for item in items:
            if isinstance(item, dict):
                lines.append(json.dumps(item, ensure_ascii=False))
            else:
                lines.append(str(item))
        (folder / "frontend-errors.txt").write_text(
            sanitize_text("\n".join(lines)), encoding="utf-8")

    # 5) 问题描述（可选）
    if description:
        (folder / "description.txt").write_text(
            sanitize_text(str(description)), encoding="utf-8")

    # 6) README 使用说明
    (folder / "README.txt").write_text(
        sanitize_text(_README_TEXT), encoding="utf-8")

    # 打包 zip（arcname 带顶层目录名，解压后自动生成一个文件夹）
    zip_path = output_dir / f"{folder_name}.zip"
    files: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                rel = f.relative_to(folder).as_posix()
                files.append(rel)
                zf.write(f, arcname=f"{folder_name}/{rel}")

    size_bytes = zip_path.stat().st_size

    # 删除临时目录
    shutil.rmtree(folder, ignore_errors=True)

    return {
        "report_path": str(zip_path.resolve()),
        "report_dir": str(output_dir.resolve()),
        "files": files,
        "size_bytes": size_bytes,
    }