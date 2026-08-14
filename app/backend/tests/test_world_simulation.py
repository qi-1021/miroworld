"""世界模拟运行器单元测试（不联网，不依赖 LLM）"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_world_simulation import (
    WorldEnv,
    WorldEvent,
    parse_action,
)


DEMO_CONFIG = {
    "world": {
        "name": "测试小镇",
        "time_step_minutes": 30,
        "total_steps": 3,
        "initial_time": "2026-01-01 08:00"
    },
    "locations": [
        {"id": "market", "name": "龙脊城集市", "description": "热闹的广场"},
        {"id": "tavern", "name": "老橡木酒馆", "description": "旅人歇脚的地方"},
        {"id": "gate", "name": "城门", "description": "城防要地"}
    ],
    "connections": [["market", "tavern"], ["market", "gate"]],
    "characters": [
        {
            "id": "kara", "name": "卡拉",
            "persona": "龙脊城的年轻铁匠",
            "location": "market",
            "goal": "打听城门修缮的进展",
            "knowledge": ["龙脊城", "铁匠"]
        },
        {
            "id": "eldrin", "name": "埃尔德里",
            "persona": "东境游吟诗人",
            "location": "tavern",
            "goal": "寻找听众",
            "knowledge": ["东境"]
        }
    ],
    "rules": [
        {"id": "no_fire", "description": "城镇内禁止施放火焰类魔法"}
    ],
    "llm": {"model": "", "base_url": "", "api_key": ""}
}


def make_env(**overrides):
    cfg = json.loads(json.dumps(DEMO_CONFIG))
    if overrides:
        cfg.update(overrides)
    return WorldEnv(cfg)


# ---------------------------------------------------------------- 解析

def test_parse_move():
    a = parse_action("前往老橡木酒馆")
    assert a["type"] == "move"
    assert "老橡木酒馆" in a["target"]


def test_parse_move_truncates_subclause():
    a = parse_action("前往老橡木酒馆寻找愿意听故事的旅人")
    assert a["type"] == "move"
    assert "寻找" not in a["target"]
    assert "老橡木酒馆" in a["target"]


def test_parse_talk():
    a = parse_action("向卡拉打听城门的事")
    assert a["type"] == "talk"
    assert "城门" in a["target"]


def test_parse_use():
    a = parse_action("施展火球术")
    assert a["type"] == "use"
    assert "火球术" in a["target"]


def test_parse_trade():
    a = parse_action("买一把剑")
    assert a["type"] == "trade"


def test_parse_explore():
    a = parse_action("环顾四周，查看集市")
    assert a["type"] == "explore"


def test_parse_wait():
    a = parse_action("我停下来等待。")
    assert a["type"] == "wait"


# ---------------------------------------------------------------- 环境

def test_env_init():
    env = make_env()
    assert len(env.locations) == 3
    assert len(env.characters) == 2
    assert len(env.rules) == 1
    assert env.current_step == 0


def test_advance_clock():
    env = make_env()
    env.current_step = 1
    env.advance_clock()
    assert env.current_step == 1  # step 由主循环统一管理
    assert env.time_str() == "01-01 08:30"


def test_observe_includes_context():
    env = make_env()
    obs = env.observe(env.characters["kara"])
    assert "龙脊城集市" in obs
    # 在场名单（独立的行）不应包含自己
    present_line = [line for line in obs.split("\n") if "此刻" in line][0]
    assert "卡拉" not in present_line
    assert "世界规则" in obs
    assert "你的目标" in obs


def test_observe_sees_present_characters():
    env = make_env()
    env.characters["eldrin"].location = "market"
    obs = env.observe(env.characters["kara"])
    assert "埃尔德里" in obs


def test_move_execution():
    env = make_env()
    kara = env.characters["kara"]
    result = env.execute(kara, {"type": "move", "desc": "前往老橡木酒馆", "target": "老橡木酒馆"})
    assert "老橡木酒馆" in result
    assert kara.location == "tavern"


def test_move_with_subclause_matches_in_full_desc():
    env = make_env()
    kara = env.characters["kara"]
    result = env.execute(kara, {"type": "move", "desc": "前往老橡木酒馆寻找旅人", "target": "老橡木酒馆"})
    assert "老橡木酒馆" in result
    assert kara.location == "tavern"


def test_move_to_unknown_place_stays():
    env = make_env()
    kara = env.characters["kara"]
    result = env.execute(kara, {"type": "move", "desc": "前往雪山", "target": "雪山"})
    assert "留在原地" in result
    assert kara.location == "market"


def test_talk_requires_present_character():
    env = make_env()
    kara = env.characters["kara"]
    result = env.execute(kara, {"type": "talk", "desc": "向埃尔德里问好", "target": "埃尔德里"})
    assert "没有可以交谈的对象" in result


def test_talk_with_present_character():
    env = make_env()
    env.characters["eldrin"].location = "market"
    kara = env.characters["kara"]
    result = env.execute(kara, {"type": "talk", "desc": "向埃尔德里问好", "target": "埃尔德里"})
    assert "与埃尔德里交谈" in result


def test_fire_rule_blocked_in_town():
    env = make_env()
    kara = env.characters["kara"]  # 在集市（镇内）
    ok, reason = env.check_rules(kara, {"type": "use", "desc": "施展火球术", "target": "火球术"})
    assert ok is False
    assert "禁止" in reason


def test_non_fire_action_passes_rules():
    env = make_env()
    kara = env.characters["kara"]
    ok, reason = env.check_rules(kara, {"type": "talk", "desc": "向埃尔德里问好", "target": ""})
    assert ok is True
    assert reason == ""


def test_run_loop_records_events_with_fake_llm():
    """用固定决策的假 LLM 跑完整循环"""
    env = make_env()
    calls = []

    async def fake_llm(text):
        calls.append(text)
        return "前往城门"

    import asyncio
    events = asyncio.run(env.run(fake_llm))

    assert len(events) == 6  # 2 角色 × 3 步
    assert env.current_step == 3
    assert all(isinstance(e, WorldEvent) for e in events)
    assert len(env.history) == 6
    # 移动应成功：角色位置变化
    kara = env.characters["kara"]
    assert kara.location == "gate"


def test_event_to_text_format():
    e = WorldEvent(
        step=1, time="01-01 08:30", character_id="k", character_name="卡拉",
        action_type="move", action_desc="前往城门", result="你来到了【城门】",
        location="城门",
    )
    text = e.to_text()
    assert "卡拉" in text
    assert "城门" in text
