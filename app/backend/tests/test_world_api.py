"""世界设定库 API 测试"""

import json

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    """构造测试 Flask 客户端，隔离世界数据目录"""
    import app.services.world_bible as wb
    import app.services.conflict_detector as cd

    original_wb = wb.WORLD_DATA_ROOT
    original_cd = cd.WORLD_DATA_ROOT
    wb.WORLD_DATA_ROOT = str(tmp_path / "world")
    cd.WORLD_DATA_ROOT = str(tmp_path / "world")

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

    wb.WORLD_DATA_ROOT = original_wb
    cd.WORLD_DATA_ROOT = original_cd


BG = (
    "龙裔王国建于三百年前，首都是龙脊城。王国信奉烈焰女神。"
    "魔法需要付出代价：施法者每使用一次高阶魔法，就会消耗自身寿命。"
)
STORY = (
    "清晨，龙脊城的街道上，平民艾拉抱怨道：'五百年前建立的龙裔王国，如今连城门都破了。'"
    "法师卡尔随手施展禁咒级火球术，毫发无损。"
)


def test_input_requires_at_least_one(client):
    rv = client.post("/api/world/p1/input", json={"background": "", "story": ""})
    assert rv.status_code == 400
    assert "不能同时为空" in rv.get_json()["error"]


def test_input_background_only(client):
    rv = client.post("/api/world/p1/input", json={"background": BG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["stats"]["has_background"] is True
    assert body["stats"]["has_story"] is False


def test_input_both_sources(client):
    rv = client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["background_chunks"] >= 1
    assert stats["story_chunks"] >= 1


def test_settings_roundtrip(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.get("/api/world/p1/settings")
    assert rv.status_code == 200
    stats = rv.get_json()["stats"]
    assert stats["total_chunks"] >= 2


def test_settings_missing_project(client):
    rv = client.get("/api/world/nope/settings")
    assert rv.status_code == 200
    assert rv.get_json()["stats"] is None


def test_chunks_list_and_source_filter(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.get("/api/world/p1/chunks?source=background")
    body = rv.get_json()
    assert body["success"] is True
    assert all(c["source"] == "background" for c in body["chunks"])
    assert body["total"] == 2


def test_search_endpoint(client):
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    rv = client.post("/api/world/p1/search", json={"query": "龙脊城"})
    assert rv.status_code == 200
    results = rv.get_json()["results"]
    assert len(results) >= 1
    assert all("龙脊城" in r["text"] for r in results)


def test_search_empty_query(client):
    rv = client.post("/api/world/p1/search", json={"query": ""})
    assert rv.status_code == 400


def test_conflict_detect_requires_input(client):
    rv = client.post("/api/world/p1/conflicts/detect")
    assert rv.status_code == 400
    assert "尚未提交" in rv.get_json()["error"]


def test_conflict_detect_requires_both_sources(client):
    client.post("/api/world/p1/input", json={"background": BG})
    rv = client.post("/api/world/p1/conflicts/detect")
    assert rv.status_code == 400
    assert "同时有背景" in rv.get_json()["error"]


def test_conflict_detect_starts_task_and_status_update(client):
    """启动任务 + 写一份报告 + 更新状态 + 读取（不实际调用 LLM）"""
    client.post("/api/world/p1/input", json={"background": BG, "story": STORY})

    # 手工落盘一份报告（模拟任务完成后的状态）
    from app.services.conflict_detector import (
        ConflictItem, ConflictReport, save_conflict_report,
    )
    report = ConflictReport(
        project_id="p1",
        conflicts=[ConflictItem(
            conflict_id="c1", topic="建国时间", conflict_type="time_conflict",
            background_fact="三百年前", story_fact="五百年前",
            reason="不一致", severity="high", suggestion="以背景为准",
        )],
    )
    save_conflict_report("p1", report)

    # 读取报告
    rv = client.get("/api/world/p1/conflicts")
    assert rv.status_code == 200
    body = rv.get_json()["report"]
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["conflict_id"] == "c1"

    # 更新状态
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "accepted"})
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    rv = client.get("/api/world/p1/conflicts")
    assert rv.get_json()["report"]["conflicts"][0]["status"] == "accepted"

    # 非法状态
    rv = client.patch("/api/world/p1/conflicts/c1", json={"status": "bogus"})
    assert rv.status_code == 400

    # 不存在的冲突
    rv = client.patch("/api/world/p1/conflicts/none", json={"status": "open"})
    assert rv.status_code == 404


def test_conflicts_none_when_no_report(client):
    rv = client.get("/api/world/p1/conflicts")
    assert rv.status_code == 200
    assert rv.get_json()["report"] is None


def test_delete_world_data(client):
    client.post("/api/world/p1/input", json={"background": BG})
    rv = client.delete("/api/world/p1")
    assert rv.status_code == 200
    rv = client.get("/api/world/p1/settings")
    assert rv.get_json()["stats"] is None
