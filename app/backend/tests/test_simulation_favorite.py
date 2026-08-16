"""模拟流向收藏（收藏 / 最佳流向 / 备注）API 与服务测试。

覆盖：
- SimulationFavoriteService 纯存储层（读/写/互斥/兼容旧数据）
- PATCH /api/simulation/<id>/favorite 接口
- GET /api/simulation/history?favorite=1 只看收藏过滤
- GET /api/simulation/<id> 暴露收藏字段
- DELETE 模拟时清理收藏记录
"""

import json
import os

import pytest

from app import create_app
from app.services.simulation_favorite import (
    SimulationFavoriteService,
    FAVORITES_ROOT_ENV,
)


@pytest.fixture()
def fav_service(tmp_path):
    """隔离收藏存储，返回一个全新的服务实例。"""
    os.environ[FAVORITES_ROOT_ENV] = str(tmp_path / "sim-favorites")
    SimulationFavoriteService.reset()
    yield SimulationFavoriteService()
    SimulationFavoriteService.reset()
    os.environ.pop(FAVORITES_ROOT_ENV, None)


@pytest.fixture()
def client(tmp_path):
    """构造测试 Flask 客户端，隔离收藏存储与模拟数据目录。"""
    from app.services import simulation_manager as sm

    os.environ[FAVORITES_ROOT_ENV] = str(tmp_path / "sim-favorites")
    SimulationFavoriteService.reset()

    orig_sim = sm.SimulationManager.SIMULATION_DATA_DIR
    sm.SimulationManager.SIMULATION_DATA_DIR = str(tmp_path / "uploads-sim")

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

    sm.SimulationManager.SIMULATION_DATA_DIR = orig_sim
    SimulationFavoriteService.reset()
    os.environ.pop(FAVORITES_ROOT_ENV, None)


def _media_state(sim_id, project_id="p1", status="completed"):
    from app.services.simulation_manager import SimulationManager
    sim_dir = os.path.join(SimulationManager.SIMULATION_DATA_DIR, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump({
            "simulation_id": sim_id,
            "project_id": project_id,
            "status": status,
        }, f)


# ================= 服务层 =================

def test_favorite_defaults_false(fav_service):
    meta = fav_service.get("sim_never_set")
    assert meta["favorite"] is False
    assert meta["is_best_flow"] is False
    assert meta["remark"] == ""


def test_favorite_set_get_persists_to_disk(fav_service, tmp_path):
    meta = fav_service.set_favorite("sim_abc", True)
    assert meta["favorite"] is True

    # 新实例（同存储根）也应读到已持久化的数据
    SimulationFavoriteService.reset()
    svc2 = SimulationFavoriteService()
    assert svc2.get("sim_abc")["favorite"] is True
    store_file = os.path.join(tmp_path / "sim-favorites", "favorites.json")
    assert os.path.isfile(store_file)


def test_remark_roundtrip(fav_service):
    fav_service.set_remark("sim_r", "这是关键推演")
    assert fav_service.get("sim_r")["remark"] == "这是关键推演"
    # 空串清除
    fav_service.set_remark("sim_r", "")
    assert fav_service.get("sim_r")["remark"] == ""


def test_best_flow_mutual_exclusive_same_project(fav_service):
    # 显式传入同一 project_id，两条记录应互斥：后设置的生效，前者被清掉
    fav_service.set_best_flow("sim_a", True, project_id="p1")
    fav_service.set_best_flow("sim_b", True, project_id="p1")
    assert fav_service.get("sim_a")["is_best_flow"] is False
    assert fav_service.get("sim_b")["is_best_flow"] is True


def test_best_flow_distinct_projects_not_exclusive(fav_service):
    fav_service.set_best_flow("sim_a", True, project_id="p1")
    fav_service.set_best_flow("sim_b", True, project_id="p2")
    assert fav_service.get("sim_a")["is_best_flow"] is True
    assert fav_service.get("sim_b")["is_best_flow"] is True


def test_update_merges_partial(fav_service):
    fav_service.update("sim_x", favorite=True)
    fav_service.update("sim_x", remark="备注")
    meta = fav_service.get("sim_x")
    assert meta["favorite"] is True
    assert meta["remark"] == "备注"


def test_list_favorited(fav_service):
    fav_service.set_favorite("sim_a", True)
    fav_service.set_favorite("sim_b", False)
    assert fav_service.list_favorited() == ["sim_a"]


def test_project_resolution_world_placeholder(fav_service):
    assert SimulationFavoriteService.resolve_project_id("world_proj_9") == "proj_9"


# ================= API 层 =================

def test_patch_favorite_endpoint(client):
    _media_state("sim_fav1", project_id="p1")
    rv = client.patch("/api/simulation/sim_fav1/favorite", json={"favorite": True})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    assert body["data"]["favorite"] is True


def test_patch_favorite_requires_bool(client):
    _media_state("sim_fav2", project_id="p1")
    rv = client.patch("/api/simulation/sim_fav2/favorite", json={"favorite": "yes"})
    assert rv.status_code == 400


def test_patch_best_flow_mutual_exclusion_api(client):
    """同一项目内设置最佳流向，应清除同项目其它条目的最佳标记（API 级）。"""
    _media_state("sim_a", project_id="p1")
    _media_state("sim_b", project_id="p1")
    client.patch("/api/simulation/sim_a/favorite", json={"best_flow": True})
    rv = client.patch("/api/simulation/sim_b/favorite", json={"best_flow": True})
    assert rv.get_json()["data"]["is_best_flow"] is True

    # 读回 sim_a：其最佳标记应已被清掉
    ra = client.get("/api/simulation/sim_a")
    assert ra.get_json()["data"]["is_best_flow"] is False


def test_get_simulation_exposes_favorite_fields(client):
    _media_state("sim_c", project_id="p1")
    client.patch("/api/simulation/sim_c/favorite", json={"favorite": True, "remark": "重点"})
    rv = client.get("/api/simulation/sim_c")
    data = rv.get_json()["data"]
    assert data["favorite"] is True
    assert data["is_best_flow"] is False
    assert data["remark"] == "重点"


def test_history_favorite_filter(client):
    _media_state("sim_keep", project_id="p1")
    _media_state("sim_drop", project_id="p1")
    client.patch("/api/simulation/sim_keep/favorite", json={"favorite": True})

    # 全部
    all_rv = client.get("/api/simulation/history")
    all_ids = {e["simulation_id"] for e in all_rv.get_json()["data"]}
    assert "sim_keep" in all_ids and "sim_drop" in all_ids

    # 只看收藏
    fav_rv = client.get("/api/simulation/history?favorite=1")
    fav_ids = {e["simulation_id"] for e in fav_rv.get_json()["data"]}
    assert "sim_keep" in fav_ids
    assert "sim_drop" not in fav_ids
    # 收藏条目带收藏标记
    keep_entry = next(e for e in fav_rv.get_json()["data"] if e["simulation_id"] == "sim_keep")
    assert keep_entry["favorite"] is True


def test_history_entries_carry_favorite_metadata(client):
    _media_state("sim_m", project_id="p1")
    # 未收藏的条目也应暴露 favorite=false / is_best_flow=false / remark=""
    rv = client.get("/api/simulation/history")
    entry = next(e for e in rv.get_json()["data"] if e["simulation_id"] == "sim_m")
    assert entry["favorite"] is False
    assert entry["is_best_flow"] is False
    assert entry["remark"] == ""


def test_delete_simulation_cleans_favorite(client):
    _media_state("sim_del", project_id="p1")
    client.patch("/api/simulation/sim_del/favorite", json={"favorite": True})
    assert SimulationFavoriteService().get("sim_del")["favorite"] is True

    rv = client.delete("/api/simulation/sim_del")
    assert rv.status_code == 200
    assert SimulationFavoriteService().get("sim_del")["favorite"] is False


def test_backward_compat_missing_store(fav_service, tmp_path):
    """存储文件不存在/损坏时，收藏功能应降级为空默认值而非报错。"""
    bad_dir = tmp_path / "sim-favorites"
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "favorites.json"), "w", encoding="utf-8") as f:
        f.write("{ not valid json ")
    SimulationFavoriteService.reset()
    svc = SimulationFavoriteService()
    assert svc.get("any_sim")["favorite"] is False
    # 仍能正常写入修复
    svc.set_favorite("any_sim", True)
    assert svc.get("any_sim")["favorite"] is True
