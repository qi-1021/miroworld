"""CLI 时间线结构判断/局部抽取 的轻量测试。"""

import json

import pytest


@pytest.fixture()
def _import_cli():
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "mirofish_cli",
        os.path.join(os.path.dirname(__file__), "../scripts/mirofish_cli.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_structure_text(_import_cli, monkeypatch):
    """CLI timeline structure-text 对一段文本做结构判断。"""
    cli = _import_cli
    calls = {}

    class _LLM:
        def chat(self, **kw):
            calls["system"] = kw["messages"][0]["content"]
            return ('{"type":"parallel","confidence":0.8,"reason":"三国并行",'
                    '"strategy":"按势力分线"}')

    monkeypatch.setattr(cli, "_build_llm_client", lambda *a, **k: _LLM())

    class _Args:
        action = "structure-text"
        text = "魏蜀吴三方多年并行征战，各自独立推进。"
        project_id = None

    result = cli.cmd_timeline(_Args())
    st = result.get("structure")
    assert st is not None
    assert st["type"] == "parallel"
    assert "按势力分线" in st["strategy"]
    assert "时间线结构" in calls["system"]


def test_cli_extract_text_llm(_import_cli, monkeypatch):
    """CLI timeline extract-text 对局部文本做完整抽取（含结构+线程提示）。"""
    cli = _import_cli

    class _LLM:
        def chat(self, **kw):
            system = kw["messages"][0]["content"]
            user = kw["messages"][1]["content"]
            if "结构类型" in system:
                return ('{"type":"single","confidence":0.9,"strategy":"单线"}')
            if "识别" in system and "线索" in system:
                return ('[{"id":"主线","name":"主线","dimension":"main",'
                        '"description":"单一主线"}]')
            # 抽取
            return ('[{"summary":"凯尔希发布命令","time_text":"次日","ev_type":"duty",'
                    '"location_text":"罗德岛","confidence":0.8}]')

    monkeypatch.setattr(cli, "_build_llm_client", lambda *a, **k: _LLM())

    class _Args:
        action = "extract-text"
        text = "次日，凯尔希在罗德岛发布命令。"
        source = "bg"
        project_id = None

    result = cli.cmd_timeline(_Args())
    assert int(result["event_count"]) >= 1
    assert result["events"][0]["summary"] == "凯尔希发布命令"
    assert result["structure"]["type"] == "single"
