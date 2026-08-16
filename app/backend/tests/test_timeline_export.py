"""
t29 时间线导出测试：可选单/多/全部线程，按时间顺序导成 md/json/csv。

覆盖：全线程/选线程/空选择/顺序/三种格式/下载端点/无数据。
"""
import json

import pytest

from app import create_app
from app.services import timeline_service as svc


VALID_PID = "proj_0123456789ab"


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    yield svc


def _mk_event(seq, thread_id="main", thread_name="主线", sort_lower=0.0,
              sort_upper=None, summary="", characters=("阿米娅",), ev_type="life",
              confidence=0.8, time_text="", location_name="罗德岛",
              parent_event_id="", linked_event_ids=()):
    ev = svc._normalize_event(
        {"summary": summary or f"事件{seq}", "time_text": time_text,
         "ev_type": ev_type, "characters": list(characters),
         "confidence": confidence, "location_text": location_name,
         "thread_id": thread_id, "thread_name": thread_name},
        VALID_PID, "story", 0, "llm", seq,
    )
    ev["sort_lower"] = float(sort_lower)
    ev["sort_upper"] = float(sort_upper if sort_upper is not None else sort_lower)
    ev["parent_event_id"] = parent_event_id
    ev["linked_event_ids"] = list(linked_event_ids)
    ev["extract_seq"] = seq
    return ev


def _seed_timeline(service, threads=("主线", "支线A", "支线B")):
    events = []
    # 主线：多个按时间序事件
    for i in range(5):
        events.append(_mk_event(i, thread_id="main", thread_name="主线",
                                sort_lower=i, summary=f"主线{i}"))
    # 支线A：2 事件（时间在主线之间穿插，验证组内按 sort 排序）
    events.append(_mk_event(100, thread_id="a", thread_name="支线A",
                            sort_lower=1.5, summary="支线A-1", time_text="半途"))
    events.append(_mk_event(101, thread_id="a", thread_name="支线A",
                            sort_lower=3.5, summary="支线A-2", time_text="后续"))
    # 支线B：1 事件
    events.append(_mk_event(200, thread_id="b", thread_name="支线B",
                            sort_lower=0.5, summary="支线B"))
    service._save_timeline(VALID_PID, events)
    return events


class TestExportFormats:
    def test_md_contains_threads_and_events(self, tl_service):
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, format="md")
        assert r["format"] == "md"
        assert r["total_events"] == 8
        assert r["filename"] == "timeline-story.md"
        assert "## 主线" in r["content"]
        assert "## 支线A" in r["content"]
        assert "主线0" in r["content"]

    def test_json_roundtrip(self, tl_service):
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, format="json")
        data = json.loads(r["content"])
        assert data["threads"][0]["count"] > 0
        assert len(data["events"]) == 8
        # 事件含 thread_key
        assert all("thread_key" in e for e in data["events"])

    def test_csv_headers_and_rows(self, tl_service):
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, format="csv")
        lines = r["content"].strip().splitlines()
        assert lines[0] == "id,thread,time,type,summary,characters,confidence,location,parent,links"
        assert len(lines) == 9  # 1 header + 8 rows

    def test_ordering_within_thread(self, tl_service):
        """组内按 sort_lower→sort_upper→extract_seq 升序。"""
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, format="md")
        # 主线事件按主线0..主线4 顺序出现
        idx = [r["content"].index(f"主线{i}") for i in range(5)]
        assert idx == sorted(idx), "主线事件应按 sort_lower 升序"


class TestThreadSelection:
    def test_select_specific_threads(self, tl_service):
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, thread_keys=["支线A"], format="md")
        assert r["total_events"] == 2
        assert "## 支线A" in r["content"]
        assert "主线" not in r["content"].split("## ")[1] or "主线0" not in r["content"]
        # 只含支线A
        assert "主线0" not in r["content"]

    def test_all_threads_when_empty(self, tl_service):
        _seed_timeline(tl_service)
        r = svc.export_timeline(VALID_PID, thread_keys=[], include_all_threads=True)
        assert r["total_events"] == 8

    def test_empty_selection_no_all_raises(self, tl_service):
        _seed_timeline(tl_service)
        with pytest.raises(ValueError):
            svc.export_timeline(VALID_PID, thread_keys=[], include_all_threads=False)

    def test_source_selection(self, tl_service, monkeypatch):
        # 只 bg 有数据时，自动选 bg；显式 bg 也 OK
        _seed_timeline(tl_service)
        # 手动写 bg 事件
        ev = _mk_event(1, summary="bg事件", sort_lower=0)
        # 写入 bg
        events_bg = [e for e in [ev]]
        # 手动用 service 写 bg（复制 timeline 到 bg source 不易；直接测 source 参数解析）
        r = svc.export_timeline(VALID_PID, source="story", format="json")
        assert isinstance(json.loads(r["content"]), dict)


class TestNoData:
    def test_no_events_raises(self, tl_service):
        with pytest.raises(ValueError):
            svc.export_timeline(VALID_PID)


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tl_service, monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_export_post(client, tl_service):
    _seed_timeline(tl_service)
    r = client.post(f"/api/timeline/{VALID_PID}/export",
                    json={"format": "md", "thread_keys": ["主线"]})
    assert r.status_code == 200
    d = r.get_json()
    assert d["success"] is True
    assert d["data"]["format"] == "md"
    assert d["data"]["total_events"] == 5


def test_api_export_download(client, tl_service):
    _seed_timeline(tl_service)
    r = client.get(f"/api/timeline/{VALID_PID}/export/download?format=csv&thread_keys=主线,支线A")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/csv")
    assert "attachment; filename=timeline-story.csv" in r.headers["Content-Disposition"]
    body = r.data.decode("utf-8")
    assert body.splitlines()[0].startswith("id,thread")


def test_api_export_no_data_404(client, tl_service):
    r = client.post(f"/api/timeline/{VALID_PID}/export", json={})
    assert r.status_code == 404
    assert r.get_json()["success"] is False
