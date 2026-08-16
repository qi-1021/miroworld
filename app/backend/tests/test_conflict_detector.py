"""冲突检测服务测试（LLM 用 Fake 替换，不联网）"""

import json

import pytest

from app.services.conflict_detector import (
    ConflictDetector,
    ConflictItem,
    ConflictReport,
    FactItem,
    save_conflict_report,
    load_conflict_report,
)


class FakeLLM:
    """模拟 LLM：按提示词内容返回预设的 JSON 响应"""

    def __init__(self, extract_facts=None, compare_conflicts=None):
        self.extract_facts = extract_facts or {
            "facts": [
                {"subject": "龙裔王国", "predicate": "建于", "object": "三百年前",
                 "quote": "龙裔王国建于三百年前"},
                {"subject": "高阶魔法", "predicate": "消耗", "object": "施法者寿命",
                 "quote": "施法者每使用一次高阶魔法，就会消耗自身寿命"},
            ]
        }
        self.compare_conflicts = compare_conflicts or {
            "conflicts": [
                {
                    "topic": "龙裔王国的建国时间",
                    "conflict_type": "time_conflict",
                    "background_fact": "龙裔王国建于三百年前",
                    "story_fact": "龙裔王国建于五百年前",
                    "background_quote": "龙裔王国建于三百年前",
                    "story_quote": "五百年前建立的龙裔王国",
                    "reason": "背景与正文对建国时间的陈述不一致",
                    "severity": "high",
                    "suggestion": "以背景设定为准，修改正文为三百年前",
                }
            ]
        }
        self.calls = []

    def chat_json(self, messages, temperature=0.3, max_tokens=8192, **kwargs):
        self.calls.append(messages)
        content = messages[-1]["content"]
        if "背景事实清单" in content:
            return self.compare_conflicts
        if "抽取**明确的设定事实**" in content or "抽取明确的设定事实" in content:
            return self.extract_facts
        return {"facts": []}


BG_TEXT = (
    "艾泽拉斯大陆的东方是东境，由龙裔王国统治。龙裔王国建于三百年前，首都是龙脊城。"
    "王国信奉烈焰女神，禁止信仰冰霜教派。魔法需要付出代价：施法者每使用一次高阶魔法，"
    "就会消耗自身寿命。"
)

STORY_TEXT = (
    "清晨，龙脊城的街道上，平民艾拉正在抱怨。'五百年前建立的龙裔王国，如今连城门都破了。'"
    "她低声说。路过的法师卡尔随手施展了禁咒级火球术，毫发无损。"
)


def test_detect_returns_report_with_conflicts():
    llm = FakeLLM()
    detector = ConflictDetector(llm_client=llm)

    report = detector.detect("p1", BG_TEXT, STORY_TEXT)

    assert report.status == "completed"
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c.topic == "龙裔王国的建国时间"
    assert c.conflict_type == "time_conflict"
    assert c.severity == "high"
    assert c.suggestion
    assert c.background_quote
    assert c.story_quote
    assert report.meta["background_facts"] >= 1


def test_detect_requires_both_inputs():
    detector = ConflictDetector(llm_client=FakeLLM())
    report = detector.detect("p1", BG_TEXT, "")
    assert report.status == "failed"
    assert "非空" in report.error


def test_detect_empty_facts_skips_compare():
    llm = FakeLLM(extract_facts={"facts": []})
    detector = ConflictDetector(llm_client=llm)
    report = detector.detect("p1", BG_TEXT, STORY_TEXT)
    assert report.status == "completed"
    assert report.conflicts == []
    # 不应调用对比阶段
    assert not any("背景事实清单" in m[-1]["content"] for m in llm.calls)


def test_extract_facts_deduplicates_and_limits():
    llm = FakeLLM(extract_facts={
        "facts": [
            {"subject": "A", "predicate": "P", "object": "X", "quote": "q1"},
            {"subject": "A", "predicate": "P", "object": "X", "quote": "q2"},  # 重复
            {"subject": "", "predicate": "P", "object": "Y", "quote": "q3"},  # 无主体
            {"subject": "B", "predicate": "Q", "object": "Z", "quote": "q4"},
        ]
    })
    detector = ConflictDetector(llm_client=llm)
    facts = detector._extract_facts(BG_TEXT * 30, source="background")  # 多批
    assert len(facts) >= 2
    keys = {(f.subject, f.predicate, f.object) for f in facts}
    assert ("A", "P", "X") in keys
    assert ("B", "Q", "Z") in keys
    assert all(f.source == "background" for f in facts)


def test_split_batches():
    detector = ConflictDetector(llm_client=FakeLLM())
    text = "\n".join(f"第{i}段内容，描述一些设定。" for i in range(50))
    batches = detector._split_batches(text, max_chars=300)
    assert len(batches) > 1
    assert all(len(b) <= 300 for b in batches)
    assert "".join(batches) == text or "".join(batches).replace("\n", "") == text.replace("\n", "")


def test_prioritize_facts_keeps_related_subjects():
    detector = ConflictDetector(llm_client=FakeLLM())
    bg = [
        FactItem(subject="龙裔王国", predicate="建于", object="三百年前"),
        FactItem(subject="东境", predicate="位于", object="大陆东方"),
        FactItem(subject="烈焰女神", predicate="被信奉", object="王国"),
    ]
    st = [FactItem(subject="龙裔王国", predicate="建于", object="五百年前")]
    ordered = detector._prioritize_facts(bg, st, limit=2)
    assert ordered[0].subject == "龙裔王国"


def test_compare_facts_output_shape():
    llm = FakeLLM()
    detector = ConflictDetector(llm_client=llm)
    bg = [FactItem(subject="龙裔王国", predicate="建于", object="三百年前")]
    st = [FactItem(subject="龙裔王国", predicate="建于", object="五百年前")]
    conflicts, suppressed = detector._compare_facts(bg, st)
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], ConflictItem)
    assert conflicts[0].conflict_id
    assert suppressed == 0


def test_report_save_and_load(tmp_path):
    import app.services.conflict_detector as cd
    original = cd.WORLD_DATA_ROOT
    cd.WORLD_DATA_ROOT = str(tmp_path / "world")

    report = ConflictReport(
        project_id="p1",
        conflicts=[ConflictItem(
            conflict_id="abc123", topic="t", conflict_type="other",
            background_fact="b", story_fact="s",
        )],
        created_at="2026-01-01T00:00:00",
    )
    save_conflict_report("p1", report)
    loaded = load_conflict_report("p1")
    assert loaded is not None
    assert loaded.conflicts[0].conflict_id == "abc123"
    assert loaded.conflicts[0].status == "open"
    assert load_conflict_report("nope") is None

    cd.WORLD_DATA_ROOT = original


def test_report_roundtrip_json():
    report = ConflictReport(
        project_id="p1",
        conflicts=[ConflictItem(
            conflict_id="abc123", topic="t", conflict_type="other",
            background_fact="b", story_fact="s", status="accepted",
        )],
    )
    data = report.to_dict()
    restored = ConflictReport.from_dict(data)
    assert restored.conflicts[0].status == "accepted"
    assert restored.to_dict() == data


def test_report_roundtrip_justified_resolution_note():
    report = ConflictReport(
        project_id="p1",
        conflicts=[ConflictItem(
            conflict_id="abc123", topic="t", conflict_type="other",
            background_fact="b", story_fact="s", status="justified",
            resolution_note="正文是寓言层，不与背景时间线同维度，因此不构成矛盾。",
        )],
    )
    data = report.to_dict()
    restored = ConflictReport.from_dict(data)
    assert restored.conflicts[0].status == "justified"
    assert restored.conflicts[0].resolution_note == "正文是寓言层，不与背景时间线同维度，因此不构成矛盾。"
    assert restored.to_dict() == data


def test_detect_with_progress_reports_phases():
    llm = FakeLLM()
    detector = ConflictDetector(llm_client=llm)
    phases = []
    report = detector.detect_with_progress(
        "p1", BG_TEXT, STORY_TEXT,
        progress_cb=lambda msg, p: phases.append((msg, p)),
    )
    assert report.status == "completed"
    assert any("背景" in m for m, _ in phases)
    assert any("正文" in m for m, _ in phases)
    assert phases[-1][1] == 100
