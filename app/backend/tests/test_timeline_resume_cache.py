"""t24 时间线抽取 resume 复用 structure/threads 缓存测试。

验证：resume=True 时，_extract_task_body 复用已保存的
structure.json / threads.json 缓存，跳过重复 LLM 识别——
即「重跑已断点的抽取」不应再次调用 detect_structure_type / _identify_threads
（这两个是耗时的 LLM 第一遍识别）。

另外验证：Config.DEBUG 默认关闭（防 Flask reloader 杀长任务）。

monkeypatch 全部建图/抽取依赖，不打真实 LLM。
"""

import time
from types import SimpleNamespace

import pytest

from app import create_app
from app.services import timeline_service as svc
from app.services import world_bible
from app.config import Config

VALID_PID = "proj_0123456789ab"


@pytest.fixture()
def tl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    with svc._task_lock:
        svc._tasks.clear()
        svc._tasks_loaded = False
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


def _install_extract_mocks(monkeypatch):
    """安装抽取全链路 mock，返回一个可写计数容器。"""
    calls = {"detect_structure": 0, "identify_threads": 0}

    def _fake_bible():
        return SimpleNamespace(
            background_text="背景文本：龙脊城的城门年久失修，随后卡尔在广场展示火球术。",
            story_text="",
        )

    monkeypatch.setattr(world_bible.WorldBibleService, "get_bible",
                        staticmethod(lambda pid: _fake_bible()))

    class _LLM:
        def chat(self, **kw):
            user = kw.get("messages", [{}])[-1].get("content", "")
            if "判断下面文本的时间线结构类型" in user or \
               "请判断下面文本的时间线结构类型" in user:
                # 结构判断 prompt → 返回结构 JSON
                return '{"type":"single","confidence":0.8,"reason":"整体单线"}'
            if "识别下面世界背景中的时间线线索" in user:
                # 线程识别 prompt → 返回线程数组
                return ('[{"id":"主线","name":"主线","dimension":"main",'
                        '"parallel_group":"","description":"主线"}]')
            # 其余是逐块抽取 prompt → 返回事件数组
            return ('[{"summary":"事件A","time_text":"","ev_type":"milestone",'
                    '"confidence":0.8,"characters":[]}]')

    monkeypatch.setattr(svc, "_build_llm_client", lambda *a, **k: _LLM())

    def _fake_extract_chunk(llm, chunk, thread_hint="", structure_hint=""):
        return [{"summary": "抽取事件", "time_text": "", "ev_type": "milestone",
                 "confidence": 0.8, "characters": []}]

    monkeypatch.setattr(svc, "_llm_extract_chunk", _fake_extract_chunk)
    # 兜底（正常不会被调用）
    monkeypatch.setattr(svc, "_heuristic_extract_chunk", lambda chunk, i, source: [])

    # 计数包装：resume 复用时不应被调用
    real_detect = svc.detect_structure_type
    real_threads = svc._identify_threads

    def _wrap_detect(llm, text):
        calls["detect_structure"] += 1
        return real_detect(llm, text)

    def _wrap_threads(llm, text):
        calls["identify_threads"] += 1
        return real_threads(llm, text)

    monkeypatch.setattr(svc, "detect_structure_type", _wrap_detect)
    monkeypatch.setattr(svc, "_identify_threads", _wrap_threads)

    return calls


# ---------------------------------------------------------------------------
# 1. resume 复用 structure/threads 缓存
# ---------------------------------------------------------------------------

def test_resume_reuses_cached_structure_and_threads(tl_service, monkeypatch):
    """""" 
    calls = _install_extract_mocks(monkeypatch)

    # 先以 bg 全量抽取一次，落盘 structure.json / threads.json / chunk 断点
    t0 = svc.start_extract(VALID_PID, "bg", resume=False)
    s0 = _wait(tl_service, t0)
    assert s0 and s0["status"] == "completed", s0
    # 首跑应做过结构判断与线程识别
    assert calls["detect_structure"] >= 1
    assert calls["identify_threads"] >= 1

    # 关键：清空计数，再以 resume=True 重跑
    # 已保存的 structure/threads 应被复用，跳过重复 LLM 识别
    calls["detect_structure"] = 0
    calls["identify_threads"] = 0

    t1 = svc.start_extract(VALID_PID, "bg", resume=True)
    s1 = _wait(tl_service, t1)
    assert s1 and s1["status"] == "completed", s1

    # resume 复用了缓存 → detect_structure_type / _identify_threads 不再被调用
    assert calls["detect_structure"] == 0, \
        f"resume 应复用已保存 structure，却再次调用 detect_structure_type（{calls['detect_structure']}）"
    assert calls["identify_threads"] == 0, \
        f"resume 应复用已保存 threads，却再次调用 _identify_threads（{calls['identify_threads']}）"


def test_first_run_without_cache_still_recognizes(tl_service, monkeypatch):
    """无缓存的首跑（即使 resume=True）仍需识别 structure/threads。"""
    calls = _install_extract_mocks(monkeypatch)
    # 没有预先保存 structure/threads → resume 时看不到缓存，应做识别
    t = svc.start_extract(VALID_PID, "bg", resume=True)
    s = _wait(tl_service, t)
    assert s and s["status"] == "completed", s
    assert calls["detect_structure"] >= 1, "无缓存时 resume 也应做结构判断"
    assert calls["identify_threads"] >= 1, "无缓存时 resume 也应做线程识别"


# ---------------------------------------------------------------------------
# 2. Config.DEBUG 默认关闭（防 reloader 杀长任务）
# ---------------------------------------------------------------------------

def test_debug_defaults_false():
    import os
    # 显式确认默认值（未设 FLASK_DEBUG 时回退 False）
    saved = os.environ.pop("FLASK_DEBUG", None)
    try:
        # reload 模块以重算类属性（干净环境）
        import importlib
        import app.config as cfg
        importlib.reload(cfg)
        assert cfg.Config.DEBUG is False
    finally:
        if saved is not None:
            os.environ["FLASK_DEBUG"] = saved
        import importlib
        import app.config as cfg
        importlib.reload(cfg)


def test_debug_env_override_true():
    import os
    import importlib
    import app.config as cfg
    saved = os.environ.get("FLASK_DEBUG")
    os.environ["FLASK_DEBUG"] = "true"
    try:
        importlib.reload(cfg)
        assert cfg.Config.DEBUG is True
    finally:
        if saved is None:
            os.environ.pop("FLASK_DEBUG", None)
        else:
            os.environ["FLASK_DEBUG"] = saved
        importlib.reload(cfg)
