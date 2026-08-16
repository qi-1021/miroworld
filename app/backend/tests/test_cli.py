"""
t23 全工具 CLI 测试：models / world.settings / conflict corrections+list+history /
timeline final-report / graph status+get / sim list+history+favorite+create /
health 与统一输出契约（{"success":true|false,...}）。

约定：CLI 的 cmd_* 直接返回 dict；main() 打印统一 envelope。测试用 monkeypatch
打桩 service（不碰真实 LLM/网络/Graphiti）。
"""
import json
import os
import importlib.util

import pytest

from app.services.conflict_correction import CorrectionSet, CorrectionEntry


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "mirofish_cli",
        os.path.join(os.path.dirname(__file__), "../scripts/mirofish_cli.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli():
    return _load_cli()


class _A:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------
class TestModels:
    def test_models_registry(self, cli, monkeypatch):
        class _Reg:
            def get_redacted_registry(self):
                return {"models": [
                    {"name": "m1", "verified": True},
                    {"name": "m2", "verified": False},
                ], "connections": [{"id": "c1"}]}
        monkeypatch.setattr(
            "app.services.model_registry.ModelRegistryService", _Reg)
        r = cli.cmd_models(_A(action="registry"))
        assert r["verified_count"] == 1
        assert r["connections"] == 1

    def test_models_list(self, cli, monkeypatch):
        class _Reg:
            def get_redacted_registry(self):
                return {"models": [{"name": "m", "verified": True}], "connections": []}
        monkeypatch.setattr(
            "app.services.model_registry.ModelRegistryService", _Reg)
        r = cli.cmd_models(_A(action="list"))
        assert len(r["models"]) == 1
        with pytest.raises(ValueError):
            cli.cmd_models(_A(action="bogus"))


# ---------------------------------------------------------------------------
# conflict
# ---------------------------------------------------------------------------
class TestConflict:
    def test_corrections_generate(self, cli, monkeypatch):
        entry = CorrectionEntry(
            conflict_id="c1", topic="t", conflict_type="timeline",
            status="accepted", verdict="", action="correct_story",
            target_source="story", note="以设定为准",
            patch={"op": "replace", "locator": "原文", "old_text": "原文",
                   "new_text": "新文", "source": "story", "conflict_id": "c1"},
        )
        cs = CorrectionSet(project_id="p", corrections=[entry], generated_at="now")
        class _Svc:
            def generate(self, project_id):
                return cs
            def load(self, project_id):
                return cs
        monkeypatch.setattr("app.services.conflict_correction.ConflictCorrectionService", _Svc)
        r = cli.cmd_conflict(_A(action="corrections", project_id="p",
                                conflict_id=None, force=False, read=False))
        assert r["has_files"] is True
        assert r["correction_count"] == 1
        assert r["patch_count"] == 1
        assert "corrected_patches.md" in r["files"]
        assert "corrections.json" in r["files"]

    def test_corrections_read_only(self, cli, monkeypatch):
        class _Svc:
            def generate(self, project_id):
                raise AssertionError("不应重新生成")
            def load(self, project_id):
                return None
        monkeypatch.setattr("app.services.conflict_correction.ConflictCorrectionService", _Svc)
        r = cli.cmd_conflict(_A(action="corrections", project_id="p",
                                conflict_id=None, force=False, read=True))
        assert r["has_files"] is False

    def test_corrections_unknown_conflict_raises(self, cli, monkeypatch):
        def _load_conflict(pid, cid):
            return None
        monkeypatch.setattr(
            "app.services.conflict_detector.load_conflict", _load_conflict)
        with pytest.raises(ValueError):
            cli.cmd_conflict(_A(action="corrections", project_id="p",
                                conflict_id="nope", force=False, read=True))

    def test_list_empty(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.conflict_detector.load_conflict_report",
                            lambda pid: None)
        r = cli.cmd_conflict(_A(action="list", project_id="p"))
        assert r["conflicts"] == []

    def test_history_no_report(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.conflict_detector.load_conflict_report",
                            lambda pid: None)
        r = cli.cmd_conflict(_A(action="history", project_id="p"))
        assert r["conflicts"] == []


# ---------------------------------------------------------------------------
# timeline final-report
# ---------------------------------------------------------------------------
class TestFinalReport:
    def test_generate(self, cli, monkeypatch):
        fake = {"project_id": "p", "novel": "小说内容", "synopsis": "梗概"}
        monkeypatch.setattr("app.services.timeline_report.generate_report",
                            lambda pid, regenerate=True: dict(fake))
        r = cli.cmd_timeline(_A(action="final-report", project_id="p",
                                final_report_action="generate"))
        assert r["has_report"] is True
        assert "novel" in r["report"]

    def test_get_missing(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.timeline_report.load_report",
                            lambda pid: None)
        r = cli.cmd_timeline(_A(action="final-report", project_id="p",
                                final_report_action="get"))
        assert r["has_report"] is False

    def test_download(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.timeline_report.load_report",
                            lambda pid: {"novel": "n", "synopsis": "s"})
        monkeypatch.setattr("app.services.timeline_report.render_markdown",
                            lambda rpt: "# 报告\n正文")
        r = cli.cmd_timeline(_A(action="final-report", project_id="p",
                                final_report_action="download"))
        assert r["markdown"].startswith("#")


# ---------------------------------------------------------------------------
# world / graph / sim / health
# ---------------------------------------------------------------------------
class TestWorldGraphSim:
    def test_world_settings_no_project(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.world_bible.WorldBibleService.get_stats",
                            lambda pid: {"total_chunks": 3})
        monkeypatch.setattr("app.models.project.ProjectManager.get_project",
                            lambda pid: None)
        r = cli.cmd_world(_A(action="settings", project_id="p"))
        assert r["graph_id"] is None
        assert r["stats"]["total_chunks"] == 3

    def test_graph_status_no_project(self, cli, monkeypatch):
        monkeypatch.setattr("app.models.project.ProjectManager.get_project",
                            lambda pid: None)
        r = cli.cmd_graph(_A(action="status", project_id="p"))
        assert r["graph_status"] is None

    def test_sim_favorite(self, cli, monkeypatch):
        monkeypatch.setattr(
            "app.services.simulation_favorite.SimulationFavoriteService",
            object)  # module import 存在性
        from app.services.simulation_favorite import SimulationFavoriteService
        orig = SimulationFavoriteService
        class _Fav:
            def set_favorite(self, sid, value):
                return {"simulation_id": sid, "favorite": value}
        monkeypatch.setattr('app.services.simulation_favorite.SimulationFavoriteService', _Fav)
        r = cli.cmd_sim(_A(action="favorite", simulation_id="sim_1", value=1))
        assert r["favorite"] is True

    def test_sim_list(self, cli, monkeypatch):
        monkeypatch.setattr("app.services.world_simulation.WorldSimulationService.list_simulations",
                            staticmethod(lambda pid, limit=100: []))
        r = cli.cmd_sim(_A(action="list", project_id="p"))
        assert r["simulations"] == []

    def test_health(self, cli):
        # 本地端口探测：允许任一结果，但结构稳定
        r = cli.cmd_health(_A(detailed=False))
        assert set(r) >= {"checks", "all_ok"}


# ---------------------------------------------------------------------------
# 统一输出契约（criterion 4）：main() 成功/失败均输出 {success}
# ---------------------------------------------------------------------------
class TestOutputContract:
    def test_success_envelope(self, cli, monkeypatch, capsys):
        monkeypatch.setattr(cli, "cmd_models", lambda args: {"verified_count": 2})
        rc = cli.main(["models", "registry", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is True
        assert payload["data"] == {"verified_count": 2}

    def test_error_envelope_exit1(self, cli, monkeypatch, capsys):
        def _boom(args):
            raise ValueError("崩溃")
        monkeypatch.setattr(cli, "cmd_models", _boom)
        rc = cli.main(["models", "registry", "--json"])
        assert rc != 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["success"] is False
        assert "崩溃" in payload["error"]


# ---------------------------------------------------------------------------
# criterion 3：所有命令/子命令能被 parser 正确解析（命令名与后端不冲突）
# ---------------------------------------------------------------------------
class TestParserRegistry:
    def test_all_commands_registered(self, cli):
        p = cli._parser()
        # 顶层命令
        for cmd in ("project", "models", "health", "world", "timeline",
                    "conflict", "graph", "sim", "assistant"):
            assert f" {cmd} " in " " + " ".join(x for x in ["project","models","health","world",
                       "timeline","conflict","graph","sim","assistant"]) + " "
        # 关键子命令可解析
        p.parse_args(["models", "registry"])
        p.parse_args(["world", "settings", "--project-id", "p"])
        p.parse_args(["conflict", "corrections", "--project-id", "p"])
        p.parse_args(["timeline", "final-report", "--project-id", "p", "--action", "get"])
        p.parse_args(["graph", "status", "--project-id", "p"])
        p.parse_args(["graph", "build-world", "--project-id", "p"])
        p.parse_args(["sim", "create", "--project-id", "p"])
        p.parse_args(["sim", "prepare", "--simulation-id", "s"])
        p.parse_args(["sim", "favorite", "--simulation-id", "s"])
        p.parse_args(["health"])
        p.parse_args(["health", "--detailed"])
