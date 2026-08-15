"""报告日志轮转/截断测试。"""

import json
import os

from app.services import report_agent


def _make_logger(tmp_path, monkeypatch):
    monkeypatch.setattr(report_agent.Config, "UPLOAD_FOLDER", str(tmp_path))
    logger = report_agent.ReportLogger("report_retention_test")
    # 调低阈值，便于测试
    logger._AGENT_LOG_MAX_BYTES = 256
    logger._AGENT_LOG_KEEP_LINES = 3
    return logger


def test_jsonl_trim_keeps_recent_lines(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    # 写 10 行，每行都超过阈值
    lines = [json.dumps({"i": i, "pad": "x" * 100}) + "\n" for i in range(10)]
    with open(logger.log_file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger._maybe_trim_jsonl()

    with open(logger.log_file_path, "r", encoding="utf-8") as f:
        kept = [json.loads(line) for line in f if line.strip()]
    assert [x["i"] for x in kept] == [7, 8, 9]


def test_jsonl_trim_does_nothing_when_small(tmp_path, monkeypatch):
    logger = _make_logger(tmp_path, monkeypatch)
    with open(logger.log_file_path, "w", encoding="utf-8") as f:
        f.write('{"i":1}\n{"i":2}\n')

    logger._maybe_trim_jsonl()

    with open(logger.log_file_path, "r", encoding="utf-8") as f:
        assert len(f.readlines()) == 2
