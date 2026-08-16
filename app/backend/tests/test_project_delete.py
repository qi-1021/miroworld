"""
项目删除彻底性测试：错误任务（错误项目/孤儿媒体模拟）删除修复的回归覆盖。

背景：首页「历史项目数据库」可能出现只存在于状态/缓存里、磁盘已无关联目录的
“错误任务”（proj_xxx 占位、或残留的媒体模拟 state.json 引用已删项目）。
本次修复：
1) graph 删除接口对 proj_ 占位做幂等删除（返回 already_absent:True），避免 404 一直删不掉；
2) delete_project 级联删除关联媒体模拟（uploads/simulations/<sim_id>），
   否则历史列表会因残留媒体模拟 state 而永远显示“错误任务”。
"""

import json
import os

import pytest

from app import create_app
from app.models.project import ProjectManager
from app.services import simulation_manager as sm
from app.services import timeline_service as tl
from app.services import world_bible as wb
from app.services import world_graph_refill as wgr
from app.services import world_simulation as ws


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """隔离各数据根目录，避免污染真实数据。"""
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "uploads-sim"))
    monkeypatch.setattr(wb, "WORLD_DATA_ROOT", str(tmp_path / "world"))
    monkeypatch.setattr(tl, "TIMELINE_ROOT", str(tmp_path / "world-timeline"))
    monkeypatch.setattr(ws, "WORLD_SIM_ROOT", str(tmp_path / "world-sim"))
    monkeypatch.setattr(wgr, "WORLD_GRAPH_ROOT", str(tmp_path / "world-graph"))


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _seed_project_with_media_sim():
    """创建一个项目并挂载一个媒体模拟，返回 (project, media_sim_manager, media_sim_id)。"""
    project = ProjectManager.create_project(name="级联删除测试")
    manager = sm.SimulationManager()
    sim_state = manager.create_simulation(project_id=project.project_id, graph_id="g1")
    return project, manager, sim_state.simulation_id


# ---------------------------------------------------------------------------
# graph 删除接口：proj_ 占位幂等删除
# ---------------------------------------------------------------------------
class TestGraphProjectDeleteIdempotent:
    def test_project_delete_removes_media_sim_cascade(self, client):
        """DELETE /api/graph/project/<pid>：删除项目应同时级联删除其媒体模拟。"""
        project, manager, sim_id = _seed_project_with_media_sim()
        pid = project.project_id

        rv = client.delete(f"/api/graph/project/{pid}")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True

        # 项目目录与项目 json 移除
        assert not os.path.isdir(ProjectManager._get_project_dir(pid))
        # 媒体模拟目录移除，历史列表不再出现
        assert not os.path.isdir(os.path.join(manager.SIMULATION_DATA_DIR, sim_id))
        assert [s.simulation_id for s in manager.list_simulations()] == []

    def test_proj_placeholder_already_absent(self, client):
        """proj_xxx 但磁盘（项目/世界/时间线/模拟/图谱）均无目录 → 幂等 200 already_absent。"""
        rv = client.delete("/api/graph/project/proj_ffffffffffff")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True
        assert body["already_absent"] is True

    def test_proj_placeholder_with_only_world_data_still_deletes(self, client):
        """proj_xxx 磁盘无项目目录、但只残留世界设定库 → 仍返回删除成功。"""
        pid = "proj_0123456789ab"
        os.makedirs(os.path.join(wb.WORLD_DATA_ROOT, pid), exist_ok=True)
        rv = client.delete(f"/api/graph/project/{pid}")
        assert rv.status_code == 200
        body = rv.get_json()
        assert body["success"] is True
        assert not os.path.exists(os.path.join(wb.WORLD_DATA_ROOT, pid))

    def test_non_mirofish_missing_returns_404(self, client):
        """非 proj_ 前缀且磁盘无数据 → 404（不误删普通标识）。"""
        rv = client.delete("/api/graph/project/not_a_project")
        assert rv.status_code == 404


# ---------------------------------------------------------------------------
# delete_project 级联清理媒体模拟
# ---------------------------------------------------------------------------
class TestProjectDeleteCascadeMediaSim:
    def test_media_sim_cascade_direct(self):
        """ProjectManager.delete_project 直接级联删除关联媒体模拟（含目录与内存缓存）。"""
        project, manager, sim_id = _seed_project_with_media_sim()
        # 先删项目主目录，制造“残缺项目”
        import shutil
        shutil.rmtree(ProjectManager._get_project_dir(project.project_id))

        assert ProjectManager.delete_project(project.project_id) is True
        assert not os.path.isdir(os.path.join(manager.SIMULATION_DATA_DIR, sim_id))
        # 内存缓存也清掉（state 里仍挂着该项目则 list_simulations 应为空）
        assert [s.simulation_id for s in manager.list_simulations()] == []

    def test_delete_project_with_no_self_dir_cascade(self, client):
        """项目目录缺失（只有媒体模拟在引用）时 delete_project 也能清理媒体模拟。"""
        project, manager, sim_id = _seed_project_with_media_sim()
        # 先删项目目录（模拟项目已不在磁盘）
        import shutil
        shutil.rmtree(ProjectManager._get_project_dir(project.project_id))
        assert not os.path.isdir(ProjectManager._get_project_dir(project.project_id))

        # 直接调用 delete_project（等价于删除项目占位时的清理）
        assert ProjectManager.delete_project(project.project_id) is True
        assert not os.path.isdir(os.path.join(manager.SIMULATION_DATA_DIR, sim_id))


# ---------------------------------------------------------------------------
# 历史列表不再出现已删除项目的“错误任务”
# ---------------------------------------------------------------------------
class TestHistoryNoOrphanMediaSim:
    def test_history_omits_media_sim_after_project_delete(self, client):
        """项目删除后，GET /history 不再返回引用该项目的媒体模拟条目。"""
        project, manager, sim_id = _seed_project_with_media_sim()
        pid = project.project_id

        # 删除前，历史应包含该媒体模拟
        before = client.get("/api/simulation/history").get_json()["data"]
        assert any(e.get("simulation_id") == sim_id for e in before)

        # 删除项目
        rv = client.delete(f"/api/graph/project/{pid}")
        assert rv.status_code == 200

        # 删除后，历史列表不再出现
        after = client.get("/api/simulation/history").get_json()["data"]
        assert not any(e.get("simulation_id") == sim_id for e in after)

    def test_history_omits_orphan_media_sim_with_missing_project(self, client):
        """项目目录被外部删除、仅残留媒体模拟 state 时，删除项目占位也能清理历史。"""
        project, manager, sim_id = _seed_project_with_media_sim()
        pid = project.project_id
        # 模拟“项目目录被外部误删”
        import shutil
        shutil.rmtree(ProjectManager._get_project_dir(pid))

        # 历史仍会因残留媒体模拟而显示（媒体模拟 state.project_id 引用该 pid）
        before = client.get("/api/simulation/history").get_json()["data"]
        assert any(e.get("simulation_id") == sim_id for e in before)

        # 走 graph 删除接口（前端对含 project_id 的普通卡片就是这么删的）
        rv = client.delete(f"/api/graph/project/{pid}")
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

        after = client.get("/api/simulation/history").get_json()["data"]
        assert not any(e.get("simulation_id") == sim_id for e in after)
