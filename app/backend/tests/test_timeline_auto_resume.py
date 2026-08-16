"""
t26 时间线抽取自动断点续传 + 世界图谱 build-progress 重启可靠性测试。

覆盖：
- start_extract 不传 resume/force 时自动检测已有断点并续传（页面刷新/重启不丢进度）。
- force=true 时强制全新抽取（忽略已有断点）。
- resume=true 时强制续传。
- 无断点时正常新建（fresh）。
- has_resumable_progress 判定。
- 世界图谱 mark_chunks_done → 新实例 load_build_progress 能读到上次保存的批次（重启场景）。
"""
import json

import pytest

from app.services import timeline_service as svc
from app.services import world_graph_refill as wgr


VALID_PID = "proj_0123456789ab"


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    yield svc


def _seed_progress(service, source="story", status="ok", count=3, has_events=True):
    """写一个含 done 条目的 progress 文件。"""
    entries = [{
        "index": i, "hash": f"h{i}", "method": "llm", "status": status,
        "events": ([{"summary": f"事件{i}"}] if has_events else []),
    } for i in range(count)]
    assert service._save_extract_progress(VALID_PID, source, entries) is True
    return entries


def _capture_start(service, monkeypatch):
    """把 start_extract 的 _extract_task_body 替换为记录 resume 的桩。"""
    calls = {}
    def _fake_body(project_id, source, task_id, resume=False):
        calls["resume"] = resume
        calls["source"] = source
    monkeypatch.setattr(service, "_extract_task_body", _fake_body)
    monkeypatch.setattr(service, "_new_task", lambda *a, **k: f"tl_task_test")
    return calls


class TestTimelineAutoResume:
    def test_auto_resumes_when_progress_exists(self, tl_service, monkeypatch):
        """已有断点 + 不传 resume/force → 自动续传。"""
        _seed_progress(tl_service, "story")
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story")
        assert calls["resume"] is True

    def test_auto_resume_when_no_progress_is_fresh(self, tl_service, monkeypatch):
        """无断点 + 不传 → 全新抽取（resume=False）。"""
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story")
        assert calls["resume"] is False

    def test_force_overrides_existing_progress(self, tl_service, monkeypatch):
        """有断点 + force=true → 强制全新抽取（忽略断点）。"""
        _seed_progress(tl_service, "story")
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story", force=True)
        assert calls["resume"] is False

    def test_explicit_resume(self, tl_service, monkeypatch):
        """有断点 + resume=true → 强制续传。"""
        _seed_progress(tl_service, "story")
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story", resume=True)
        assert calls["resume"] is True

    def test_explicit_resume_false_is_fresh(self, tl_service, monkeypatch):
        """有断点 + resume=False → 强制全新抽取（不自动续传，供"重抽"语义/旧调用兼容）。"""
        _seed_progress(tl_service, "story")
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story", resume=False)
        assert calls["resume"] is False

    def test_bg_and_story_separate_progress(self, tl_service, monkeypatch):
        """bg 与 story 的断点各自独立：仅 bg 有断点，story 不带 resume → fresh。"""
        _seed_progress(tl_service, "bg")
        calls = _capture_start(tl_service, monkeypatch)
        tl_service.start_extract(VALID_PID, "story")  # story 无断点
        assert calls["resume"] is False
        tl_service.start_extract(VALID_PID, "bg")     # bg 有断点
        assert calls["resume"] is True

    def test_has_resumable_progress(self, tl_service):
        assert svc.has_resumable_progress(VALID_PID, "story") is False
        _seed_progress(tl_service, "story", status="ok")
        assert svc.has_resumable_progress(VALID_PID, "story") is True

    def test_skipped_only_not_resumable(self, tl_service):
        """只有 status=skipped（无事件、无成功 chunk）不算可续传进度。"""
        _seed_progress(tl_service, "story", status="skipped", has_events=False)
        assert svc.has_resumable_progress(VALID_PID, "story") is False


# ---------------------------------------------------------------------------
# 世界图谱 build-progress 重启可靠性
# ---------------------------------------------------------------------------
@pytest.fixture()
def graph_root(tmp_path, monkeypatch):
    monkeypatch.setattr(wgr, "WORLD_GRAPH_ROOT", str(tmp_path / "world-graph"))
    yield str(tmp_path / "world-graph")


class TestWorldGraphProgress:
    def test_mark_done_then_reload_new_instance(self, graph_root):
        """批次完成 marker 落盘后，新实例 load（模拟重启）仍能读到 done。"""
        chunks = ["第一章内容", "第二章内容", "第三章内容"]
        uuid_ = "mirofish_graph_123"
        # 第一批完成
        wgr.mark_chunks_done(VALID_PID, chunks[:2], [0, 1],
                             ["ep_uuid_0", "ep_uuid_1"], graph_id=uuid_)
        # 重启：新建实例（进程内存无关，直接再 load）
        progress = wgr.load_build_progress(VALID_PID)
        assert progress is not None
        by_idx = {int(c["index"]): c for c in progress.get("chunks", [])}
        assert by_idx[0]["status"] == "done"
        assert by_idx[1]["status"] == "done"
        assert progress.get("graph_id") == uuid_

    def test_incremental_mark_done_accumulates(self, graph_root):
        """分批标记：后一批在已有断点上追加，不覆盖已 done。"""
        chunks = ["a", "b", "c"]
        wgr.mark_chunks_done(VALID_PID, ["a"], [0], ["u0"])
        wgr.mark_chunks_done(VALID_PID, ["b", "c"], [1, 2], ["u1", "u2"])
        progress = wgr.load_build_progress(VALID_PID)
        by_idx = {int(c["index"]): c for c in progress.get("chunks", [])}
        assert set(by_idx) == {0, 1, 2}
        assert all(by_idx[k]["status"] == "done" for k in (0, 1, 2))

    def test_no_progress_returns_none(self, graph_root):
        assert wgr.load_build_progress(VALID_PID) is None

    def test_save_then_new_instance_load(self, graph_root):
        """save_build_progress → 新 load 读到同一 chunk 列表（磁盘持久化）。"""
        state = [{"index": 0, "hash": "h", "status": "done", "episode_uuid": "u"}]
        assert wgr.save_build_progress(VALID_PID, state, graph_id="g1") is True
        pr = wgr.load_build_progress(VALID_PID)
        assert pr["chunks"][0]["hash"] == "h"
        assert pr["graph_id"] == "g1"
