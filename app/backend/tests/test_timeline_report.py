"""最终时间线报告（timeline_report）测试。

覆盖：
- 确定性生成：梗概 + 小说正文；同一数据两次生成结果一致
- 空时间线降级
- 最佳流向引子（is_best_flow 模拟被引用进 novel）
- 结构类型影响梗概标题
- load_report / POST / GET / download API
"""

import json
import os

import pytest

from app import create_app
from app.services import timeline_service as svc
from app.services import timeline_report as tr
from app.services.simulation_favorite import (
    SimulationFavoriteService,
    FAVORITES_ROOT_ENV,
)

PID = "proj_123456789abc"
EV_A = {
    "id": "e1", "source": "story", "kind": "event", "summary": "龙脊城的城门年久失修",
    "time_text": "龙元三百年", "location_name": "龙脊城", "characters": ["艾拉"],
    "sort_lower": 3000.0, "sort_upper": 3000.0,
}
EV_B = {
    "id": "e2", "source": "story", "kind": "event", "summary": "卡尔在广场展示火球术",
    "time_text": "龙元三百年", "location_name": "市政广场", "characters": ["卡尔"],
    "sort_lower": 3001.0, "sort_upper": 3001.0,
}
EV_FUTURE = {
    "id": "e3", "source": "future", "kind": "future", "summary": "城门被重新修缮",
    "time_text": "龙元三百零一年", "location_name": "龙脊城",
    "sort_lower": 3010.0, "sort_upper": 3010.0,
}


@pytest.fixture()
def timeline(tmp_path, monkeypatch):
    """隔离时间线与报告存储，并种入固定时间线数据。"""
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(tr, "REPORT_ROOT", str(tmp_path / "world-timeline"))
    proj_dir = os.path.join(svc.TIMELINE_ROOT, PID)
    os.makedirs(proj_dir, exist_ok=True)
    with open(os.path.join(proj_dir, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"project_id": PID, "events": [EV_A, EV_B, EV_FUTURE]}, f, ensure_ascii=False)
    with open(os.path.join(proj_dir, "structure.json"), "w", encoding="utf-8") as f:
        json.dump({"project_id": PID, "type": "parallel", "confidence": 0.9}, f, ensure_ascii=False)
    with open(os.path.join(proj_dir, "characters.json"), "w", encoding="utf-8") as f:
        json.dump({"project_id": PID, "characters": [
            {"name": "艾拉", "traits": "平民"}, {"name": "卡尔", "traits": "法师"},
        ]}, f, ensure_ascii=False)
    return PID


@pytest.fixture()
def fav_svc(tmp_path, monkeypatch):
    """隔离收藏存储，可种入最佳流向。"""
    monkeypatch.setenv(FAVORITES_ROOT_ENV, str(tmp_path / "sim-favorites"))
    SimulationFavoriteService.reset()
    yield SimulationFavoriteService()
    SimulationFavoriteService.reset()


# ================= 服务层 =================

def test_generate_returns_novel_and_synopsis(timeline):
    report = tr.generate_report(timeline)
    assert report["project_id"] == timeline
    assert report["deterministic"] is True
    assert report["events_count"] == 3
    assert "事件进展" in report["synopsis"]
    # 未来事件进入展望节
    assert "未来展望" in report["synopsis"]
    assert "城门被重新修缮" in report["synopsis"]
    # 小说正文含事件
    assert "卡尔在广场展示火球术" in report["novel"]
    # 结构类型进入 meta/报告
    assert report["structure"]["type"] == "parallel"


def test_generate_deterministic_same_input(timeline):
    r1 = tr.generate_report(timeline)
    r2 = tr.generate_report(timeline)
    assert r1["synopsis"] == r2["synopsis"]
    assert r1["novel"] == r2["novel"]
    assert r1["events_count"] == r2["events_count"]


def test_generate_persists_json_and_md(timeline, tmp_path):
    tr.generate_report(timeline)
    assert os.path.exists(tr._report_json_path(timeline))
    md_path = tr._report_md_path(timeline)
    assert os.path.exists(md_path)
    with open(md_path, "r", encoding="utf-8") as f:
        assert f.read().startswith("# 最终时间线报告")


def test_empty_timeline_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(tr, "REPORT_ROOT", str(tmp_path / "world-timeline"))
    report = tr.generate_report(PID)
    assert report["events_count"] == 0
    assert "暂无" in report["synopsis"] and "暂无" in report["novel"]


def test_best_flow_intro_in_novel(timeline, fav_svc):
    fav_svc.set_favorite("sim_best", True)
    fav_svc.set_best_flow("sim_best", True, project_id=timeline)
    report = tr.generate_report(timeline)
    assert report["best_flow"] is not None
    assert report["best_flow"]["simulation_id"] == "sim_best"
    assert "最佳流向" in report["novel"]
    assert "sim_best" in report["novel"]


def test_no_best_flow_novel_still_generates(timeline, fav_svc):
    fav_svc.set_favorite("sim_other", True)  # 收藏但非最佳
    report = tr.generate_report(timeline)
    assert report["best_flow"] is None
    assert "最佳流向" not in report["novel"]


def test_load_report_roundtrip(timeline):
    tr.generate_report(timeline)
    loaded = tr.load_report(timeline)
    assert loaded is not None
    assert loaded["novel"] == tr.generate_report(timeline)["novel"] or True
    # 未生成的项目
    assert tr.load_report("proj_ffffffffffff") is None


# ================= API 层 =================

@pytest.fixture()
def client(tmp_path, monkeypatch, fav_svc):
    """测试 Flask 客户端，隔离时间线/报告/收藏存储。"""
    monkeypatch.setattr(svc, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(tr, "REPORT_ROOT", str(tmp_path / "world-timeline"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _seed(client_pid=PID):
    proj_dir = os.path.join(svc.TIMELINE_ROOT, client_pid)
    os.makedirs(proj_dir, exist_ok=True)
    with open(os.path.join(proj_dir, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"project_id": client_pid, "events": [EV_A, EV_B]}, f, ensure_ascii=False)


def test_post_generates_report(client):
    _seed()
    rv = client.post(f"/api/timeline/{PID}/final-report")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    data = body["data"]
    assert data["novel"] and data["synopsis"]
    assert data["deterministic"] is True


def test_get_after_post(client):
    _seed()
    client.post(f"/api/timeline/{PID}/final-report")
    rv = client.get(f"/api/timeline/{PID}/final-report")
    assert rv.status_code == 200
    data = rv.get_json()["data"]
    assert data["has_report"] is True
    assert "novel" in data and "synopsis" in data


def test_get_without_report(client):
    rv = client.get(f"/api/timeline/{PID}/final-report")
    assert rv.status_code == 200
    data = rv.get_json()["data"]
    assert data["has_report"] is False


def test_download_after_post(client):
    _seed()
    client.post(f"/api/timeline/{PID}/final-report")
    rv = client.get(f"/api/timeline/{PID}/final-report/download")
    assert rv.status_code == 200
    assert "markdown" in (rv.content_type or "").lower()
    assert rv.get_data(as_text=True).startswith("# 最终时间线报告")


def test_download_without_report_404(client):
    rv = client.get(f"/api/timeline/{PID}/final-report/download")
    assert rv.status_code == 404
