"""
t5 落地②（双缓存 + MODE 注册表）测试：

1. MODE 注册表 / /api/world/modes 端点
2. 本体缓存命中/未命中（mock LLM，隔离缓存目录）
3. 世界配置缓存命中/未命中（mock LLM，隔离缓存目录）
4. POST /api/world/<id>/input 的 mode 透传进 metadata['mode']
"""

import os
import pytest

from app import create_app


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    """隔离世界数据目录与两个缓存目录。"""
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


@pytest.fixture()
def cache_dirs(tmp_path):
    """把两个缓存目录重定向到临时目录，避免污染真实 data/。"""
    ontology_dir = str(tmp_path / "ontology_cache")
    worldsim_dir = str(tmp_path / "world-sim-cache")

    old_ont = os.environ.get('MIROFISH_ONTOLOGY_CACHE_DIR')
    old_ws = os.environ.get('MIROFISH_WORLD_SIM_CACHE_DIR')
    os.environ['MIROFISH_ONTOLOGY_CACHE_DIR'] = ontology_dir
    os.environ['MIROFISH_WORLD_SIM_CACHE_DIR'] = worldsim_dir
    try:
        yield {"ontology": ontology_dir, "worldsim": worldsim_dir}
    finally:
        if old_ont is None:
            os.environ.pop('MIROFISH_ONTOLOGY_CACHE_DIR', None)
        else:
            os.environ['MIROFISH_ONTOLOGY_CACHE_DIR'] = old_ont
        if old_ws is None:
            os.environ.pop('MIROFISH_WORLD_SIM_CACHE_DIR', None)
        else:
            os.environ['MIROFISH_WORLD_SIM_CACHE_DIR'] = old_ws


# ---------------------------------------------------------------------------
# MODE 注册表 / /api/world/modes
# ---------------------------------------------------------------------------
def test_builtin_modes_present():
    from app.services.mode_registry import get_modes, get_mode

    modes = get_modes()
    keys = [m["key"] for m in modes]
    assert "novel-world" in keys
    assert "character-card" in keys
    assert "timeline" in keys
    # 每项含必需字段
    for m in modes:
        for field in ("key", "label", "inputs", "pipeline", "artifacts"):
            assert field in m, f"ModeSpec 缺少字段 {field}: {m}"
    spec = get_mode("character-card")
    assert spec.to_dict()["label"] == "角色卡"
    assert get_mode("nonexistent") is None


def test_api_modes_endpoint(client):
    rv = client.get("/api/world/modes")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] is True
    keys = [m["key"] for m in body["modes"]]
    assert "novel-world" in keys and "character-card" in keys and "timeline" in keys


# ---------------------------------------------------------------------------
# 本体缓存命中/未命中
# ---------------------------------------------------------------------------
def test_ontology_cache_miss_then_hit(cache_dirs):
    """首次调用走 LLM 并写缓存；第二次相同输入直接命中，不再调用 LLM。"""
    from app.services.ontology_generator import generate_ontology_with_cache

    call_count = {"n": 0}
    fake_ontology = {
        "entity_types": [{"name": "人物"}],
        "edge_types": [],
        "analysis_summary": "测试本体",
    }

    class _Gen:
        llm_client = type("LLM", (), {"model": "test-model"})()

        def generate(self, document_texts, simulation_requirement, additional_context=None):
            call_count["n"] += 1
            return dict(fake_ontology)

    gen = _Gen()
    # 第 1 次：未命中 → 调 LLM，写缓存
    r1 = generate_ontology_with_cache(
        gen,
        ["背景文本"], "目标", None,
        cache_key_parts=("背景文本", "目标", "test-model"),
    )
    assert r1["entity_types"] == [{"name": "人物"}]
    assert call_count["n"] == 1
    # 第 2 次：命中 → 不再调 LLM
    r2 = generate_ontology_with_cache(
        gen, ["背景文本"], "目标", None,
        cache_key_parts=("背景文本", "目标", "test-model"),
    )
    assert r2 == fake_ontology
    assert call_count["n"] == 1, "缓存命中后不应再次调用 LLM"
    # 缓存目录已生成文件
    files = os.listdir(cache_dirs["ontology"])
    assert files and files[0].endswith(".json")


def test_ontology_cache_distinct_inputs(cache_dirs):
    """不同目标/不同文本应产生不同缓存键，各自调 LLM。"""
    from app.services.ontology_generator import generate_ontology_with_cache

    call_count = {"n": 0}

    class _Gen:
        llm_client = type("LLM", (), {"model": "m"})()

        def generate(self, document_texts, simulation_requirement, additional_context=None):
            call_count["n"] += 1
            return {"entity_types": [], "edge_types": [], "analysis_summary": "x"}

    gen = _Gen()
    generate_ontology_with_cache(gen, ["T1"], "G1", None, cache_key_parts=("T1", "G1", "m"))
    generate_ontology_with_cache(gen, ["T2"], "G2", None, cache_key_parts=("T2", "G2", "m"))
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 世界配置缓存命中/未命中
# ---------------------------------------------------------------------------
def test_world_config_cache_miss_then_hit(cache_dirs):
    from app.services.world_simulation import WorldSimulationService as Svc

    call_count = {"n": 0}

    class _LLM:
        model = "test-model"
        base_url = "http://x"
        api_key = "k"

        def chat_json(self, messages, temperature, max_tokens):
            call_count["n"] += 1
            return {
                "world": {"name": "测试世界"},
                "characters": [{"id": "c1", "name": "主角", "persona": "p", "location": "loc1"}],
                "locations": [{"id": "loc1", "name": "城", "description": "d"}],
                "connections": [],
                "rules": [],
            }

    llm = _LLM()
    c1 = Svc._generate_world_config("proj", "背景", "正文", llm, goal="统一大陆")
    assert call_count["n"] == 1
    c2 = Svc._generate_world_config("proj", "背景", "正文", llm, goal="统一大陆")
    assert call_count["n"] == 1, "命中世界配置缓存后不应再次调用 LLM"
    assert c2["world"]["name"] == "测试世界"
    # 命中返回时仍附加当前 llm 元信息
    assert c2["llm"]["model"] == "test-model"
    files = os.listdir(cache_dirs["worldsim"])
    assert files and files[0].endswith(".json")


def test_world_config_cache_goal_none(cache_dirs):
    """goal=None 时仍能正确生成缓存键并缓存（不抛异常）。"""
    from app.services.world_simulation import WorldSimulationService as Svc

    call_count = {"n": 0}

    class _LLM:
        model = "test-model"
        base_url = "http://x"
        api_key = "k"

        def chat_json(self, messages, temperature, max_tokens):
            call_count["n"] += 1
            return {
                "world": {"name": "W"},
                "characters": [],
                "locations": [],
                "connections": [],
                "rules": [],
            }

    llm = _LLM()
    Svc._generate_world_config("proj", "背景", "正文", llm, goal=None)
    Svc._generate_world_config("proj", "背景", "正文", llm, goal=None)
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# /input mode 透传
# ---------------------------------------------------------------------------
BG = "龙裔王国建于三百年前，首都是龙脊城。"
STORY = "清晨，龙脊城的街道上，平民艾拉抱怨道。"


def test_input_mode_passthrough_json(client):
    rv = client.post(
        "/api/world/p1/input",
        json={"background": BG, "story": STORY, "mode": "timeline"},
    )
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True
    # settings 读取回 mode
    rv2 = client.get("/api/world/p1/settings")
    assert rv2.get_json()["stats"]["mode"] == "timeline"


def test_input_without_mode_stays_default(client):
    rv = client.post("/api/world/p1/input", json={"background": BG, "story": STORY})
    assert rv.status_code == 200
    rv2 = client.get("/api/world/p1/settings")
    assert rv2.get_json()["stats"]["mode"] == ""
