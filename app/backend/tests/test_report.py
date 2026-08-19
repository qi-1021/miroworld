"""
错误报告生成测试：系统信息收集、敏感信息打码、报告打包（不含密钥）、CLI 子命令。
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.utils import report as report_util

BACKEND = Path(__file__).resolve().parents[1]
CLI = BACKEND / "scripts" / "mirofish_cli.py"


# ---------------------------------------------------------------------------
# 系统信息收集
# ---------------------------------------------------------------------------
class TestSystemInfo:
    def test_system_info_collect(self):
        info = report_util.collect_system_info()
        assert isinstance(info, dict)
        assert info["platform"]
        assert info["python_version"]
        assert info["hostname"]


# ---------------------------------------------------------------------------
# 敏感信息打码
# ---------------------------------------------------------------------------
class TestSanitize:
    def test_secrets_redacted(self):
        text = (
            "sk-abc12345def67890\n"
            "api_key=secretvalue123\n"
            "LLM_API_KEY=sk-abcdefghijklmnop\n"
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.token\n"
            "password=hunter2\n"
        )
        cleaned = report_util.sanitize_text(text)
        assert "sk-abc12345def67890" not in cleaned
        assert "secretvalue123" not in cleaned
        assert "sk-abcdefghijklmnop" not in cleaned
        assert "eyJhbGciOiJIUzI1NiJ9.token" not in cleaned
        assert "hunter2" not in cleaned
        assert "[REDACTED]" in cleaned

    def test_normal_text_unchanged(self):
        normal = "这是一个正常的文本，包含 password 字样但没有等号，也没有密钥。"
        assert report_util.sanitize_text(normal) == normal

    def test_case_insensitive(self):
        cleaned = report_util.sanitize_text("API_KEY=TopSecretValue")
        assert "TopSecretValue" not in cleaned
        assert "[REDACTED]" in cleaned

    def test_new_secret_patterns(self):
        """常见密钥模式：AWS、GitHub、secret 赋值、PEM 私钥、带密码的数据库连接串。"""
        cases = [
            "AKIA1234567890123456",
            "ghp_xxxxxxxxxxxx",
            "secret=abc123",
            "client_secret=xyz789",
            "-----BEGIN PRIVATE KEY-----",
            "neo4j://user:pass@host",
            "mysql://root:secret@localhost:3306/db",
        ]
        for sample in cases:
            cleaned = report_util.sanitize_text(sample)
            assert sample not in cleaned, f"密钥应被打码: {sample!r} -> {cleaned!r}"
            assert "[REDACTED]" in cleaned, f"应包含打码标记: {sample!r} -> {cleaned!r}"


# ---------------------------------------------------------------------------
# 报告打包
# ---------------------------------------------------------------------------
class TestBuildReport:
    def _prepare_fixture(self, tmp_path):
        """构造含假 .env（带密钥）的数据目录与日志目录，供 build_report 使用。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # 敏感文件：绝不能进入报告
        (data_dir / ".env").write_text(
            "LLM_API_KEY=sk-super-secret-key-123\n", encoding="utf-8")
        (data_dir / "model-config").mkdir()
        (data_dir / "model-config" / "secrets.json").write_text(
            '{"api_key": "sk-model-config-secret"}\n', encoding="utf-8")

        # 失败任务：error 里带密钥，需被打码
        tm_dir = data_dir / "task-manager"
        tm_dir.mkdir()
        (tm_dir / "failed-task.json").write_text(json.dumps({
            "task_id": "task_failed_1",
            "task_type": "graph_build",
            "status": "failed",
            "created_at": "2026-08-19T10:00:00",
            "updated_at": "2026-08-19T10:00:05",
            "message": "任务失败",
            "error": "LLM_API_KEY=sk-abcdefghijklmnop 调用失败",
            "logs": ["[10:00:00] 开始", "[10:00:05] ❌ 错误: 失败"],
        }), encoding="utf-8")

        # 日志目录：日志内容也带密钥，需被打码
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "backend.log").write_text(
            "api_key=secretvalue123\n正常日志内容\n", encoding="utf-8")

        report_util.TASK_MANAGER_DIR = tm_dir
        report_util.LOG_DIR = log_dir

    def test_build_report(self, tmp_path):
        self._prepare_fixture(tmp_path)
        out_dir = tmp_path / "out"

        result = report_util.build_report(
            output_dir=out_dir, description="测试问题描述")

        # 返回结构
        assert result["report_path"].endswith(".zip")
        assert result["report_dir"] == str(out_dir.resolve())
        assert isinstance(result["size_bytes"], int) and result["size_bytes"] > 0
        assert "system-info.txt" in result["files"]
        assert "README.txt" in result["files"]
        assert "logs/backend.log" in result["files"]

        zip_path = Path(result["report_path"])
        assert zip_path.exists()

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            joined = "\n".join(names)
            # 必需文件齐全
            assert any(n.endswith("system-info.txt") for n in names)
            assert any(n.endswith("README.txt") for n in names)
            assert any(n.endswith("task-failures.txt") for n in names)
            assert any(n.endswith("description.txt") for n in names)
            assert any(n.endswith("logs/backend.log") for n in names)

            # 绝不包含敏感文件
            assert not any(".env" in n for n in names)
            assert not any("secrets.json" in n for n in names)
            assert not any("model-config" in n for n in names)

            # 内容不含任何密钥
            content = "\n".join(
                zf.read(n).decode("utf-8", errors="replace") for n in names
            )
            assert "sk-super-secret-key-123" not in content
            assert "sk-model-config-secret" not in content
            assert "sk-abcdefghijklmnop" not in content
            assert "secretvalue123" not in content
            assert "[REDACTED]" in content

        # 临时目录已被清理，只留下 zip
        assert not (out_dir / "miroworld-report-").exists()

    def test_build_report_with_frontend_errors(self, tmp_path):
        self._prepare_fixture(tmp_path)
        out_dir = tmp_path / "out2"

        result = report_util.build_report(
            output_dir=out_dir,
            frontend_errors=["TypeError: xxx is undefined", {"code": "E1"}],
        )

        with zipfile.ZipFile(result["report_path"]) as zf:
            names = zf.namelist()
            assert any(n.endswith("frontend-errors.txt") for n in names)
            content = "\n".join(
                zf.read(n).decode("utf-8", errors="replace") for n in names
            )
            assert "TypeError: xxx is undefined" in content
            assert "E1" in content


# ---------------------------------------------------------------------------
# CLI report 子命令
# ---------------------------------------------------------------------------
class TestCliReport:
    def test_cli_report(self, tmp_path):
        out = tmp_path / "cli-out"
        proc = subprocess.run(
            [sys.executable, str(CLI), "report", "--output", str(out), "--json"],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(BACKEND)},
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["success"] is True
        assert payload["data"]["report_path"].endswith(".zip")
        assert Path(payload["data"]["report_path"]).exists()
        assert payload["data"]["size_bytes"] > 0
