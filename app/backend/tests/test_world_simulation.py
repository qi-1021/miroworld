"""世界模拟运行器单元测试（不联网，不依赖 LLM）"""

import json
import os
import sys
import asyncio
import uuid
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.run_world_simulation import (
    WorldEnv,
    WorldEvent,
    WorldIPCHandler,
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


# ---------------------------------------------------------------- IPC 控制

def _write_cmd(tmp_path, command_type, **args):
    """写入一条命令文件并返回 command_id / 完整命令"""
    env = make_env()
    sim = str(tmp_path)
    handler = WorldIPCHandler(sim)
    command_id = str(uuid.uuid4())
    cmd = {
        "command_id": command_id,
        "command_type": command_type,
        "args": args,
        "timestamp": "",
    }
    with open(os.path.join(handler.commands_dir, f"{command_id}.json"), 'w', encoding='utf-8') as f:
        json.dump(cmd, f, ensure_ascii=False, indent=2)
    return env, handler, command_id


async def _fake_llm(text):
    return "前往城门"


def test_ipc_handler_poll_and_respond(tmp_path):
    """轮询到命令后 send_response 会写入响应并删除命令文件"""
    _, handler, command_id = _write_cmd(str(tmp_path), "stop")
    cmd = handler.poll_command()
    assert cmd is not None
    assert cmd["command_type"] == "stop"
    handler.send_response(command_id, "completed", result={"stopped": True})
    resp_file = os.path.join(handler.responses_dir, f"{command_id}.json")
    assert os.path.exists(resp_file)
    with open(resp_file, 'r', encoding='utf-8') as f:
        resp = json.load(f)
    assert resp["status"] == "completed"
    assert resp["result"]["stopped"] is True
    # 命令文件已被删除，再次轮询无命令
    assert not os.path.exists(os.path.join(handler.commands_dir, f"{command_id}.json"))
    assert handler.poll_command() is None


def test_ipc_handler_update_status(tmp_path):
    """update_status 写入 env_status.json 且带 paused 标记"""
    handler = WorldIPCHandler(str(tmp_path))
    handler.paused = True
    handler.update_status("paused")
    with open(os.path.join(str(tmp_path), "env_status.json"), 'r', encoding='utf-8') as f:
        status = json.load(f)
    assert status["status"] == "paused"
    assert status["paused"] is True


def test_process_ipc_pause_and_resume(tmp_path):
    """pause 命令设为暂停；resume 恢复"""
    env = make_env()
    env.attach_ipc(str(tmp_path))
    _ = _write_cmd(str(tmp_path), "pause")
    stop = asyncio.run(env._process_ipc(_fake_llm))
    assert stop is False
    assert env.ipc.paused is True
    # resume
    _ = _write_cmd(str(tmp_path), "resume")
    stop = asyncio.run(env._process_ipc(_fake_llm))
    assert stop is False
    assert env.ipc.paused is False


def test_process_ipc_stop(tmp_path):
    """stop 命令返回终止信号 True"""
    env, _, _ = _write_cmd(str(tmp_path), "stop")
    env.attach_ipc(str(tmp_path))
    stop = asyncio.run(env._process_ipc(_fake_llm))
    assert stop is True
    with open(os.path.join(str(tmp_path), "env_status.json"), 'r', encoding='utf-8') as f:
        status = json.load(f)
    assert status["status"] == "stopped"


def test_process_ipc_interview_by_name(tmp_path):
    """interview 命令：按角色名匹配，用 LLM 回答并写响应"""
    env, _, command_id = _write_cmd(
        str(tmp_path), "interview", character_name="卡拉", prompt="你在哪里？"
    )
    env.attach_ipc(str(tmp_path))
    stop = asyncio.run(env._process_ipc(_fake_llm))
    assert stop is False
    resp_file = os.path.join(env.ipc.responses_dir, f"{command_id}.json")
    assert os.path.exists(resp_file)
    with open(resp_file, 'r', encoding='utf-8') as f:
        resp = json.load(f)
    assert resp["status"] == "completed"
    assert resp["result"]["character_name"] == "卡拉"
    assert resp["result"]["character_id"] == "kara"
    assert "城门" in resp["result"]["answer"]  # 假 LLM 返回"前往城门"


def test_process_ipc_interview_by_id_and_missing(tmp_path):
    """interview：按 id 匹配可行；角色不存在返回 failed"""
    env, _, command_id = _write_cmd(str(tmp_path), "interview", character_name="kara", prompt="？")
    env.attach_ipc(str(tmp_path))
    asyncio.run(env._process_ipc(_fake_llm))
    with open(os.path.join(env.ipc.responses_dir, f"{command_id}.json"), 'r', encoding='utf-8') as f:
        resp = json.load(f)
    assert resp["status"] == "completed"
    assert resp["result"]["character_id"] == "kara"

    # 不存在的角色
    env2, _, cid2 = _write_cmd(str(tmp_path), "interview", character_name="不存在者", prompt="？")
    env2.attach_ipc(str(tmp_path))
    asyncio.run(env2._process_ipc(_fake_llm))
    with open(os.path.join(env2.ipc.responses_dir, f"{cid2}.json"), 'r', encoding='utf-8') as f:
        resp2 = json.load(f)
    assert resp2["status"] == "failed"
    assert "未找到角色" in resp2["error"]


def test_process_ipc_unknown_command(tmp_path):
    """未知命令返回 failed 但不终止"""
    env, _, command_id = _write_cmd(str(tmp_path), "jump")
    env.attach_ipc(str(tmp_path))
    stop = asyncio.run(env._process_ipc(_fake_llm))
    assert stop is False
    with open(os.path.join(env.ipc.responses_dir, f"{command_id}.json"), 'r', encoding='utf-8') as f:
        resp = json.load(f)
    assert resp["status"] == "failed"


def test_run_loop_stops_on_stop_command(tmp_path):
    """运行前写入 stop 命令 → 主循环立即终止，无事件"""
    env, _, _ = _write_cmd(str(tmp_path), "stop")
    env.attach_ipc(str(tmp_path))
    events = asyncio.run(env.run(_fake_llm))
    assert events == []
    assert env.current_step == 0
    with open(os.path.join(str(tmp_path), "env_status.json"), 'r', encoding='utf-8') as f:
        status = json.load(f)
    assert status["status"] == "stopped"


def test_wait_while_paused_resumes(tmp_path):
    """暂停状态下写入 resume 命令 → _wait_while_paused 返回 False（不终止）"""
    env, _, _ = _write_cmd(str(tmp_path), "resume")
    env.attach_ipc(str(tmp_path))
    env.ipc.paused = True  # 模拟已处于暂停
    result = asyncio.run(env._wait_while_paused(_fake_llm))
    assert result is False
    assert env.ipc.paused is False


def test_wait_while_paused_stops(tmp_path):
    """暂停状态下写入 stop 命令 → _wait_while_paused 返回 True（终止）"""
    env, _, _ = _write_cmd(str(tmp_path), "stop")
    env.attach_ipc(str(tmp_path))
    env.ipc.paused = True
    result = asyncio.run(env._wait_while_paused(_fake_llm))
    assert result is True


def test_attach_ipc_creates_directories(tmp_path):
    """attach_ipc 会创建命令/响应目录"""
    env = make_env()
    env.attach_ipc(str(tmp_path))
    assert os.path.isdir(os.path.join(str(tmp_path), "ipc_commands"))
    assert os.path.isdir(os.path.join(str(tmp_path), "ipc_responses"))


# ---------------------------------------------------------------- 角色视角过滤与知识边界

def test_observe_hides_unknown_place_description():
    """知识边界：不在 knowledge 中的地点只显示名称，不显示描述"""
    env = make_env()
    # 埃尔德里在 tavern（老橡木酒馆），knowledge=["东境"]，不认识酒馆
    obs = env.observe(env.characters["eldrin"])
    assert "老橡木酒馆" in obs          # 名称可见
    assert "旅人歇脚的地方" not in obs  # 描述被隐藏
    # 过滤记录里包含 location_detail
    kinds = {f["kind"] for f in env._last_filtered}
    assert "location_detail" in kinds


def test_observe_shows_known_place_description():
    """知识边界：knowledge 中的地点显示描述"""
    env = make_env()
    # 卡拉在 market（龙脊城集市），knowledge=["龙脊城"，"铁匠"]，认识集市
    obs = env.observe(env.characters["kara"])
    assert "龙脊城集市" in obs
    assert "热闹的广场" in obs  # 描述可见
    kinds = {f["kind"] for f in env._last_filtered}
    assert "location_detail" not in kinds


def test_observe_hides_present_character_goal():
    """在场角色只显示名字与 persona 第一句，绝不泄露其 goal"""
    env = make_env()
    # 把埃尔德里移到集市，让卡拉能看到他
    env.characters["eldrin"].location = "market"
    obs = env.observe(env.characters["kara"])
    assert "埃尔德里" in obs
    assert "东境游吟诗人" in obs          # persona 第一句可见
    assert "寻找听众" not in obs          # 埃尔德里的 goal 被隐藏
    # 过滤记录里包含 character_goal
    goal_filtered = [f for f in env._last_filtered if f["kind"] == "character_goal"]
    assert any(f["name"] == "埃尔德里" for f in goal_filtered)


def test_observe_known_rules_filters():
    """known_rules 非空时，observe 只展示其中的规则，其余规则隐藏"""
    env = make_env()
    # DEMO_CONFIG 只有一条规则 no_fire
    kara = env.characters["kara"]
    kara.known_rules = []  # 默认空 = 知道全部
    obs = env.observe(kara)
    assert "城镇内禁止" in obs

    # 设置为知道空/无关规则 id -> 看不到该规则
    kara.known_rules = ["nonexistent_rule"]
    obs2 = env.observe(kara)
    assert "城镇内禁止" not in obs2
    kinds = {f["kind"] for f in env._last_filtered}
    assert "rule" in kinds
    assert any(f["rule_id"] == "no_fire" for f in env._last_filtered)


def test_known_rules_multi_rule():
    """多规则下 known_rules 只暴露白名单规则"""
    env = make_env(**{
        "rules": [
            {"id": "no_fire", "description": "城镇内禁止施放火焰类魔法"},
            {"id": "magic_cost", "description": "高阶魔法消耗施法者寿命"},
        ]
    })
    kara = env.characters["kara"]
    kara.known_rules = ["no_fire"]
    obs = env.observe(kara)
    assert "城镇内禁止施放火焰类魔法" in obs
    assert "高阶魔法消耗施法者寿命" not in obs
    ids = {f["rule_id"] for f in env._last_filtered if f["kind"] == "rule"}
    assert "magic_cost" in ids


def test_run_event_detail_contains_filtered():
    """主循环事件 detail.filtered 记录被隐藏的信息"""
    env = make_env()
    async def fake_llm(text):
        return "原地等待"
    import asyncio as _a
    events = _a.run(env.run(fake_llm))
    # 至少有一个事件
    any_filtered = any(e.detail.get("filtered") is not None for e in events)
    assert any_filtered
    # 过滤列表本身是 list，且每个事件都带 filtered 键
    for e in events:
        assert "filtered" in e.detail
        assert isinstance(e.detail["filtered"], list)
