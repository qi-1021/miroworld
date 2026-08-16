"""
t3 时间线抽取质量：线程判定 + 长文本分块合并。

覆盖：
1. 自动结构判定 classify_structure —— 五种类型（linear/parallel/tree/network/meta）样例。
2. 线程防误拆 —— 主线占比 ≥60% 且其余线程 ≤3 事件时并入主线（线程别名审计）；
   平行双 POV（各 ≥4 事件）保留两线程。
3. 长文本分块（map-reduce）——split_long_blocks 按自然边界切块；_cross_chunk_merge 跨块去重/归并。
4. 断点续传跳过未变 chunk（monkeypatch LLM，不打真实模型）。
5. 单 chunk 失败恢复 —— LLM 网关可用但某块连续失败，跳过该块并记 partial，不毁全量。
"""
import json
import time
from types import SimpleNamespace

import pytest

from app import create_app
from app.services import timeline_service as svc
from app.services import world_bible


VALID_PID = "proj_0123456789ab"


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
    monkeypatch.setattr(svc, "FORK_GUIDANCE_WINDOW", 0.02)
    yield svc


def _wait(service, task_id, deadline=15, allow=("completed", "partial_failed", "failed")):
    s = None
    end = time.time() + deadline
    while time.time() < end:
        s = service.get_status(task_id)
        if s and s.get("status") in allow:
            return s
        time.sleep(0.03)
    return s


def _mk_ev(summary, thread_id="", thread_name="", dimension="main",
           parent_event_id="", linked=None, time_kind="unspecified", confidence=0.7):
    return {
        "summary": summary,
        "thread_id": thread_id,
        "thread_name": thread_name,
        "dimension": dimension,
        "parent_event_id": parent_event_id,
        "linked_event_ids": list(linked or []),
        "time_kind": time_kind,
        "confidence": confidence,
        "location_name": "",
    }


def _fake_bible(story_text):
    # 用 SimpleNamespace 而非 class 体，避免 class 体内 story_text = story_text
    # 不捕获外层函数局部变量导致的 NameError。
    return SimpleNamespace(background_text="", story_text=story_text)


class _OkLLM:
    """每次返回固定 1-2 个事件。"""
    def chat(self, **kw):
        return ('[{"summary":"事件A","time_text":"","ev_type":"milestone","confidence":0.8,'
                '"characters":["X"]},'
                '{"summary":"事件B","time_text":"","ev_type":"milestone","confidence":0.8}]')


class _FlakyLLM:
    """对包含 BAD 标记的 chunk 连续抛错，其余正常返回。"""
    def chat(self, **kw):
        user = kw.get("messages", [{}])[-1].get("content", "")
        if "BAD-CHUNK" in user:
            raise ConnectionError("bad chunk")
        return ('[{"summary":"事件A","time_text":"","ev_type":"milestone","confidence":0.8}]')


# ---------------------------------------------------------------------------
# 1. 自动结构判定 classify_structure（deterministic 五种类型）
# ---------------------------------------------------------------------------
class TestClassifyStructure:
    def test_linear_single_thread(self):
        events = [_mk_ev(f"e{i}", time_kind="year") for i in range(6)]
        st = svc.classify_structure(events)
        assert st["type"] == "linear"

    def test_linear_main_dominant_with_small_fragment(self):
        events = [_mk_ev(f"主线{i}") for i in range(7)]
        events += [_mk_ev("碎片1", thread_id="x", thread_name="叉线"),
                   _mk_ev("碎片2", thread_id="x", thread_name="叉线")]
        st = svc.classify_structure(events)
        assert st["type"] == "linear"

    def test_parallel_two_sustained_threads(self):
        events = ([_mk_ev(f"A{i}", thread_id="t1", thread_name="泰拉") for i in range(5)]
                  + [_mk_ev(f"B{i}", thread_id="t2", thread_name="龙国") for i in range(5)])
        st = svc.classify_structure(events)
        assert st["type"] == "parallel"

    def test_tree_with_parent_links(self):
        events = []
        for i in range(6):
            e = _mk_ev(f"e{i}")
            if i >= 1:
                e["parent_event_id"] = "tl_evt_parent"
            events.append(e)
        st = svc.classify_structure(events)
        assert st["type"] == "tree"

    def test_network_high_density_links(self):
        events = []
        for i in range(6):
            e = _mk_ev(f"e{i}", linked=[f"e{(i+1) % 6}", f"e{(i+2) % 6}", f"e{(i+3) % 6}"])
            events.append(e)
        st = svc.classify_structure(events)
        assert st["type"] == "network"

    def test_meta_nested_dimension_timeless(self):
        events = [_mk_ev(f"e{i}", thread_id="m", thread_name="寓言层",
                         dimension="allegory", time_kind="unspecified") for i in range(6)]
        st = svc.classify_structure(events)
        assert st["type"] == "meta"

    def test_empty_events_linear(self):
        assert svc.classify_structure([])["type"] == "linear"


# ---------------------------------------------------------------------------
# 2. 线程防误拆：主线防拆合并 + 平行 POV 保留
# ---------------------------------------------------------------------------
class TestThreadMerge:
    def test_main_dominant_merges_small_threads(self):
        """主线 8 事件 + 两条各 2 事件的小碎片线程 → 并入主线，原线程名保留为别名。"""
        events = [_mk_ev(f"主线{i}", thread_name="") for i in range(8)]
        events += [_mk_ev("甲1", thread_id="j1", thread_name="甲支线"),
                   _mk_ev("甲2", thread_id="j1", thread_name="甲支线")]
        events += [_mk_ev("乙1", thread_id="y1", thread_name="乙支线"),
                   _mk_ev("乙2", thread_id="y1", thread_name="乙支线")]
        out = svc._reconcile_threads([dict(e) for e in events], None, [])
        # 碎片线程被并入主线：不再有任何事件的主线程名是碎片线程
        primary = {e["thread_name"] for e in out}
        assert "甲支线" not in primary
        assert "乙支线" not in primary
        # 审计轨迹：原线程名记入 thread_aliases
        merged_aliases = [a for e in out for a in (e.get("thread_aliases") or [])]
        assert "甲支线" in merged_aliases
        assert "乙支线" in merged_aliases

    def test_parallel_dual_pov_preserved(self):
        """明确 parallel 结构 + 两条持续线程 → 独立保留，不合并。"""
        events = ([_mk_ev(f"阿米娅{i}", thread_id="t1", thread_name="阿米娅") for i in range(5)]
                  + [_mk_ev(f"博士{i}", thread_id="t2", thread_name="博士") for i in range(5)])
        out = svc._reconcile_threads([dict(e) for e in events], {"type": "parallel"}, [])
        names = {e["thread_name"] for e in out}
        assert names == {"阿米娅", "博士"}  # 两线程都保留

    def test_structural_parallel_not_collapsed_single_thin(self):
        """即使存在主线程 + 一条小支线，若结构判定为 parallel 也应保留（不误并）。"""
        events = ([_mk_ev(f"主线{i}") for i in range(6)]
                  + [_mk_ev("支线1", thread_id="s", thread_name="支线"),
                     _mk_ev("支线2", thread_id="s", thread_name="支线")])
        out = svc._reconcile_threads([dict(e) for e in events], {"type": "parallel"}, [])
        tnames = {e["thread_name"] for e in out}
        assert "支线" in tnames


# ---------------------------------------------------------------------------
# 3. 长文本分块（map-reduce）
# ---------------------------------------------------------------------------
class TestLongChunking:
    def test_split_long_blocks_at_boundaries(self):
        # 构造 >12000 字符、含章节标题的文本
        parts = [f"第{i+1}章 序幕\n" + ("鹿在雪原上行进。\n" * 400) for i in range(6)]
        text = "\n\n".join(parts)
        assert len(text) > svc.LONG_TEXT_CHUNK_CHARS
        blocks = svc.split_long_blocks(text)
        assert len(blocks) >= 2
        # 每块非空
        for b in blocks:
            assert b.strip()
        # 分块不改变文本总内容（近似：拼接长度 ≈ 原文本，因切分不含新增）
        assert sum(len(b) for b in blocks) <= len(text)

    def test_under_threshold_single_block(self):
        text = "短文本。"
        assert svc.split_long_blocks(text) == [text]
        assert svc.split_long_blocks("") == []

    def test_cross_chunk_merge_dedupes_and_sorts(self):
        e1 = _mk_ev("遇见旅人", time_kind="year")
        e2 = _mk_ev("遇见旅人", time_kind="year")  # 跨块重复
        e3 = _mk_ev("到达王城", thread_id="t1", thread_name="主线")
        merged = svc._cross_chunk_merge([e2, e1, e3])
        summaries = [m["summary"] for m in merged]
        assert summaries.count("遇见旅人") == 1  # 去重
        assert set(summaries) == {"遇见旅人", "到达王城"}

    def test_chunk_text_for_extract_long_uses_blocks(self):
        # 6 段，每段 ~4500 字符，总 >12000，触发长文本 map-reduce 分块
        parts = [f"第{i+1}章\n" + ("事件甲。\n" * 900) for i in range(6)]
        text = "".join(parts)
        assert len(text) > svc.LONG_TEXT_CHUNK_CHARS
        blocks = svc.split_long_blocks(text)
        assert len(blocks) >= 2
        chunks = svc.chunk_text_for_extract(text)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= svc.MAX_CHUNK_CHARS + 1  # 每小 chunk 受逐事件上限约束
            assert c.strip()


# ---------------------------------------------------------------------------
# 4. 断点续传跳过未变 chunk（monkeypatch LLM）
# ---------------------------------------------------------------------------
class TestResumeSkipsUnchanged:
    def test_resume_reuses_cached_chunks(self, tl_service, monkeypatch):
        text = "\n".join(
            f"事件{n}年，世界发生了第{n + 1}件大事，王国随即分裂为南北两部。"
            for n in range(300))
        _bible = _fake_bible(text)
        monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(
            lambda pid: _bible))

        chunks = svc.chunk_text_for_extract(text)
        assert len(chunks) > 2

        called_indices = []

        def _counting_extract(llm, chunk, thread_hint="", structure_hint=""):
            idx = next(i for i, c in enumerate(chunks) if c == chunk)
            called_indices.append(idx)
            return [{"summary": f"事件{idx}", "time_text": "", "ev_type": "milestone",
                     "confidence": 0.8}]

        monkeypatch.setattr(svc, "_llm_extract_chunk", _counting_extract)
        # 先跑一次全量，建立断点
        t0 = svc.start_extract(VALID_PID, "story")
        s0 = _wait(tl_service, t0)
        assert s0 and s0["status"] == "completed"

        called_indices.clear()

        monkeypatch.setattr(svc, "_llm_extract_chunk", _counting_extract)
        # resume：未变 chunk 应全部跳过（不再调用 LLM）
        t1 = svc.start_extract(VALID_PID, "story", resume=True)
        s1 = _wait(tl_service, t1)
        assert s1 and s1["status"] == "completed"
        assert called_indices == [], f"resume 不应重抽未变 chunk，但调用了 {called_indices}"
        # 事件仍完整
        events = svc.load_timeline(VALID_PID, "story")["events"]
        assert events, "resume 应保留已抽事件"


# ---------------------------------------------------------------------------
# 5. 单 chunk 失败恢复：不毁全量，跳过并记 partial
# ---------------------------------------------------------------------------
class TestChunkFailureRecovery:
    def test_single_chunk_failure_skips_instead_of_failing(self, tl_service, monkeypatch):
        # 文本足够分成多块：先放足够多的成功块（>MAX_CHUNK，确保 chunk0 全 good，建立 llm_any_ok）
        # 中间插入 1 个 BAD-CHUNK 块，它属于靠后 chunk → 该块失败被跳过，其余不受影响。
        good = "\n".join(f"序章{i}：晨光穿过石城石阶，队伍在薄雾中继续前行。\n" for i in range(120))
        text = good + "\nBAD-CHUNK 这一块永远失败。\n" + good
        assert len(good) > svc.MAX_CHUNK_CHARS  # chunk0 为纯 good
        _bible = _fake_bible(text)
        monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(
            lambda pid: _bible))
        monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _FlakyLLM())
        # 减少 attempt，加速测试
        monkeypatch.setattr(svc, "MAX_LLM_ATTEMPTS", 2)
        monkeypatch.setattr(svc, "CHUNK_RETRIES", 1)

        t = svc.start_extract(VALID_PID, "story")
        s = _wait(tl_service, t)
        assert s is not None
        # 单块失败 → partial（非 failed、非 completed）
        assert s["status"] == "partial_failed"
        assert s.get("skipped", 0) >= 1
        # 其余块的事件仍在
        events = svc.load_timeline(VALID_PID, "story")["events"]
        assert events, "失败块被跳过但不能毁掉其余块结果"
        # 日志说明跳过
        joined = "\n".join(s.get("steps") or [])
        assert "跳过" in joined or "partial" in joined

    def test_all_down_falls_back_heuristic(self, tl_service, monkeypatch):
        """LLM 整体宕机（无任何块成功）→ 启发式兜底，不整段失败。"""
        class _Down:
            def chat(self, **kw):
                raise ConnectionError("gateway down")
        _bible = _fake_bible("五岁那年，我来到罗德岛。此后多年我经历战争。随后我退役。")
        monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(
            lambda pid: _bible))
        monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _Down())

        t = svc.start_extract(VALID_PID, "story")
        s = _wait(tl_service, t)
        assert s and s["status"] == "partial_failed"
        assert s.get("heuristic", 0) >= 1
        assert svc.load_timeline(VALID_PID, "story")["events"]


# ---------------------------------------------------------------------------
# 6. finalize_structure 与 LLM 判定的合并
# ---------------------------------------------------------------------------
class TestFinalizeStructure:
    def test_deterministic_overrides_low_conf_llm(self):
        events = [_mk_ev(f"e{i}", time_kind="year") for i in range(6)]
        llm = {"type": "parallel", "confidence": 0.2, "reason": "LLM 猜"}
        out = svc.finalize_structure(events, [], llm)
        # 确定性判定 linear，置信度高于 LLM 的 0.2 → 采 linear
        assert out["type"] == "linear"
        assert out["method"] == "deterministic"

    def test_llm_high_conf_wins(self):
        events = [_mk_ev(f"e{i}") for i in range(4)]
        llm = {"type": "meta", "confidence": 0.95, "reason": "LLM 强判断"}
        out = svc.finalize_structure(events, [], llm)
        assert out["type"] == "meta"
        assert out["method"] == "llm"

    def test_single_and_linear_normalized(self):
        events = [_mk_ev(f"e{i}", time_kind="year") for i in range(5)]
        out = svc.finalize_structure(events, [], {"type": "single", "confidence": 0.9})
        assert out["type"] == "linear"


# ---------------------------------------------------------------------------
# 7. 结构落盘 roundtrip + 抽取后自动判定落盘
# ---------------------------------------------------------------------------
class TestStructurePersistence:
    def test_save_load_structure_keeps_method(self, tl_service):
        st = {"type": "linear", "confidence": 0.9, "reason": "主线主导",
              "strategy": "默认", "method": "deterministic"}
        assert svc.save_structure(VALID_PID, st) is True
        loaded = svc.load_structure(VALID_PID)
        assert loaded is not None
        assert loaded["type"] == "linear"
        assert loaded["method"] == "deterministic"
        assert loaded["reason"] == "主线主导"

    def test_extract_persists_auto_classified_structure(self, tl_service, monkeypatch):
        """抽取后 structure.json 应落盘自动判定的类型（线性故事 → linear）。"""
        text = "\n".join(f"事件{n}年，王国发生了第{n+1}件大事。\n" for n in range(40))
        _bible = _fake_bible(text)
        monkeypatch.setattr(world_bible.WorldBibleService, "get_bible", staticmethod(
            lambda pid: _bible))

        class _Ok:
            def chat(self, **kw):
                u = kw.get("messages", [{}])[-1].get("content", "")
                # 仅在结构判断 prompt 时返回对象；抽取 prompt（含结构 hint）返回事件数组
                if "判断下面文本的时间线结构类型" in u or "请判断下面文本的时间线结构类型" in u:
                    return '{"type":"single","confidence":0.8,"reason":"整体单线"}'
                return ('[{"summary":"事件A","time_text":"事件A","time_kind":"year",'
                        '"ev_type":"milestone","confidence":0.8}]')

        monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _Ok())
        t = svc.start_extract(VALID_PID, "story")
        s = _wait(tl_service, t)
        assert s and s["status"] == "completed"
        st = svc.load_structure(VALID_PID)
        assert st is not None
        assert st["type"] == "linear"
        assert st["method"] in ("deterministic", "deterministic+llm")
