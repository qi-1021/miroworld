"""世界报告生成服务测试（不联网，mock LLM 与模拟状态）"""

import json
import os
from pathlib import Path

import pytest

from app.services.world_report import WorldReportService, DEFAULT_SECTION_TITLES


@pytest.fixture()
def report_root(tmp_path, monkeypatch):
    """将世界模拟数据根目录重定向到临时目录。"""
    import app.services.world_report as wr
    original = wr.WORLD_SIM_ROOT
    wr.WORLD_SIM_ROOT = str(tmp_path / "world-sim")
    yield wr.WORLD_SIM_ROOT
    wr.WORLD_SIM_ROOT = original


class FakeLLM:
    """模拟 LLM：返回预设的报告 JSON。"""

    def __init__(self, text=None, sections=None, raise_exc=False):
        self.text = text or _DEFAULT_MARKDOWN
        self.sections = sections
        self.raise_exc = raise_exc
        self.calls = 0

    def chat_json(self, messages, temperature=0.4, max_tokens=8192, **kwargs):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("LLM 调用失败")
        result = {"text": self.text}
        if self.sections is not None:
            result["sections"] = self.sections
        return result


_DEFAULT_MARKDOWN = (
    "## 世界编年史\n\n第一天，艾拉前往城门查看。\n\n"
    "## 角色动向\n\n艾拉：关注城门修缮。\n\n"
    "## 世界状态与规则遵守\n\n规则基本被遵守。\n\n"
    "## 推演与建议\n\n下一步可考察城门修复情况。"
)


def _write_sim(report_root, project_id, simulation_id, events=None, config=None):
    """在临时数据根下写一条模拟的 events.json / world_config.json。"""
    sim_dir = Path(report_root) / project_id / simulation_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "events.json").write_text(
        json.dumps(events if events is not None else [], ensure_ascii=False),
        encoding="utf-8",
    )
    if config is not None:
        (sim_dir / "world_config.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
    return sim_dir


def _mock_state(monkeypatch, project_id="p1", simulation_id="ws1"):
    """mock get_state，返回一个属于 p 项目的模拟状态。"""
    from app.services.world_simulation import WorldSimulationState

    state = WorldSimulationState(
        simulation_id=simulation_id,
        project_id=project_id,
        status="completed",
    )
    monkeypatch.setattr(
        "app.services.world_simulation.WorldSimulationService.get_state",
        classmethod(lambda cls, sid: state if sid == simulation_id else None),
    )
    return state


def test_generate_report_basic(report_root, monkeypatch):
    """生成报告：返回 text+sections，并落盘 report.md 与 report.json。"""
    events = [
        {
            "step": 1, "time": "01-01 08:30", "character_name": "艾拉",
            "location": "城门", "action_desc": "查看城门", "result": "发现破损",
            "approved": True,
        },
        {
            "step": 1, "time": "01-01 08:30", "character_name": "卡拉",
            "location": "集市", "action_desc": "施放火球", "result": "被规则阻止",
            "approved": False,
        },
    ]
    _write_sim(report_root, "p1", "ws1", events=events)
    _mock_state(monkeypatch)
    llm = FakeLLM()
    report = WorldReportService.generate_report("p1", "ws1", llm=llm)
    assert llm.calls == 1
    # 返回结构
    assert "text" in report
    assert "sections" in report
    assert report["text"] == _DEFAULT_MARKDOWN
    titles = {s["title"] for s in report["sections"]}
    assert DEFAULT_SECTION_TITLES[0] in titles

    sim_dir = Path(report_root) / "p1" / "ws1"
    assert (sim_dir / "report.md").exists()
    assert (sim_dir / "report.json").exists()
    assert (sim_dir / "report.md").read_text(encoding="utf-8") == _DEFAULT_MARKDOWN


def test_generate_report_writes_events_json(report_root, monkeypatch):
    """事件流写入 events.json，且报告内容由此驱动。"""
    events = [{"time": "01-01 09:00", "character_name": "艾拉",
               "location": "集市", "action_desc": "叫卖", "result": "暂无",
               "approved": True}]
    sim_dir = _write_sim(report_root, "p1", "ws1", events=events)
    _mock_state(monkeypatch)
    assert (sim_dir / "events.json").exists()
    llm = FakeLLM()
    WorldReportService.generate_report("p1", "ws1", llm=llm)
    # 事件已准备好供 LLM 消费（见 _mock 之外的 FakeLLM 兜底不校验内容）
    assert llm.calls == 1


def test_generate_report_loads_back(report_root, monkeypatch):
    """报告生成后可 load_report 读取。"""
    _write_sim(report_root, "p1", "ws1", events=[], config={"world": {"name": "测试"}})
    _mock_state(monkeypatch)
    WorldReportService.generate_report("p1", "ws1", llm=FakeLLM())
    loaded = WorldReportService.load_report("p1", "ws1")
    assert loaded is not None
    assert loaded["text"] == _DEFAULT_MARKDOWN
    assert len(loaded["sections"]) >= 1


def test_generate_report_missing_simulation(report_root, monkeypatch):
    """模拟不存在 → 抛 ValueError。"""
    _mock_state(monkeypatch)  # 只 mock 了 ws1
    with pytest.raises(ValueError, match="模拟不存在"):
        WorldReportService.generate_report("p1", "ws_missing", llm=FakeLLM())


def test_generate_report_project_mismatch(report_root, monkeypatch):
    """模拟所属项目不匹配 → 抛 ValueError。"""
    _write_sim(report_root, "p2", "ws1")
    _mock_state(monkeypatch, project_id="p1", simulation_id="ws1")  # 状态属 p1
    # 用另一个 project_id 请求，与状态所属项目 p1 不匹配
    with pytest.raises(ValueError, match="模拟不存在"):
        WorldReportService.generate_report("p2", "ws1", llm=FakeLLM())


def test_generate_report_empty_events(report_root, monkeypatch):
    """事件为空（边缘降级）也应正常生成报告。"""
    _write_sim(report_root, "p1", "ws1", events=[])
    _mock_state(monkeypatch)
    llm = FakeLLM()
    report = WorldReportService.generate_report("p1", "ws1", llm=llm)
    assert report["text"]
    assert llm.calls == 1


def test_generate_report_derives_sections_from_text(report_root, monkeypatch):
    """LLM 只返回 text（无 sections）时，自动按 ## 标题切分。"""
    _write_sim(report_root, "p1", "ws1")
    _mock_state(monkeypatch)
    llm = FakeLLM(sections=[])  # 空 sections → 触发兜底切分
    report = WorldReportService.generate_report("p1", "ws1", llm=llm)
    titles = [s["title"] for s in report["sections"]]
    assert "世界编年史" in titles
    assert "推演与建议" in titles


def test_generate_report_llm_exception_propagates(report_root, monkeypatch):
    """LLM 抛异常 → 异常向上抛出（由调用方处理降级）。"""
    _write_sim(report_root, "p1", "ws1", events=[])
    _mock_state(monkeypatch)
    with pytest.raises(RuntimeError, match="LLM 调用失败"):
        WorldReportService.generate_report("p1", "ws1", llm=FakeLLM(raise_exc=True))


def test_load_report_missing(report_root):
    """未生成报告时 load_report 返回 None。"""
    assert WorldReportService.load_report("nope", "ws") is None


def test_report_exists_after_generate(report_root, monkeypatch):
    """生成后 report_exists 为 True，未生成为 False。"""
    _write_sim(report_root, "p1", "ws1")
    _mock_state(monkeypatch)
    assert WorldReportService.report_exists("p1", "ws1") is False
    WorldReportService.generate_report("p1", "ws1", llm=FakeLLM())
    assert WorldReportService.report_exists("p1", "ws1") is True
