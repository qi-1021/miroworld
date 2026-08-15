"""原子 JSON 写入工具测试。"""

import json
import os

import pytest

from app.utils.atomic_json import (
    atomic_write_json,
    atomic_write_json_safe,
    atomic_write_text,
)


def test_atomic_write_json_roundtrip(tmp_path):
    path = str(tmp_path / "sub" / "state.json")
    payload = {"status": "running", "计数": 3}
    atomic_write_json(path, payload)
    assert json.load(open(path, encoding="utf-8")) == payload
    # 同目录不应留下临时文件
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["state.json"]


def test_atomic_write_text_roundtrip(tmp_path):
    path = str(tmp_path / "note.txt")
    atomic_write_text(path, "第一行\n第二行\n")
    assert open(path, encoding="utf-8").read() == "第一行\n第二行\n"


def test_atomic_write_json_failure_keeps_old_file(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    atomic_write_json(path, {"ok": True})

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(path, {"ok": False})

    # 旧文件保持完整，临时文件被清理
    assert json.load(open(path, encoding="utf-8")) == {"ok": True}
    names = [p.name for p in tmp_path.iterdir()]
    assert names == ["state.json"]
    assert real_replace  # 避免 unused 误报


def test_atomic_write_json_safe_returns_false_on_failure(tmp_path):
    path = str(tmp_path / "state.json")
    atomic_write_json(path, {"ok": True})
    # set() 不可 JSON 序列化 → 返回 False 且旧内容保持
    assert atomic_write_json_safe(path, {"bad": {1, 2}}) is False
    assert json.load(open(path, encoding="utf-8")) == {"ok": True}
