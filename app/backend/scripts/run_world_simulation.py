"""
世界模拟运行器（WorldEnv 最小实现）

跑通"世界时钟 → 感知 → 决策 → 动作解析 → 规则校验 → 执行 → 事件回写"完整循环。

用法：
    python run_world_simulation.py --config /path/to/world_config.json

配置文件结构：
{
  "world": {
    "name": "龙脊城小镇",
    "time_step_minutes": 60,
    "total_steps": 10,
    "initial_time": "2026-01-01 08:00"
  },
  "locations": [
    {"id": "market", "name": "集市", "description": "热闹的广场，商贩云集"},
    {"id": "tavern", "name": "酒馆", "description": "旅人歇脚的地方"}
  ],
  "characters": [
    {
      "id": "kara", "name": "卡拉",
      "persona": "龙脊城的年轻铁匠，性格直率，关心城防。",
      "location": "market",
      "goal": "打听城门修缮的消息",
      "knowledge": ["龙脊城", "铁匠"]
    },
    {
      "id": "eldrin", "name": "埃尔德里",
      "persona": "来自东境的游吟诗人，见多识广，喜欢讲述远方见闻。",
      "location": "tavern",
      "goal": "找一个听众分享旅途故事",
      "knowledge": ["东境", "游吟诗人"]
    }
  ],
  "rules": [
    {"id": "no_fire_in_town", "description": "城镇内禁止施放火焰类魔法"},
    {"id": "magic_cost", "description": "高阶魔法消耗施法者寿命"}
  ],
  "llm": {"model": "deepseek-v4-flash", "base_url": "", "api_key": ""}
}
"""

import argparse
import asyncio
import json
import os
import sys
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# ---------------------------------------------------------------- IPC 常量

# 命令类型（与后端 WorldSimulationService 保持一致）
CMD_PAUSE = "pause"          # 暂停模拟
CMD_RESUME = "resume"        # 恢复模拟
CMD_STOP = "stop"            # 停止模拟
CMD_INTERVIEW = "interview"  # 采访指定角色
CMD_INJECT_VARIABLE = "inject_variable"  # 上帝干预：向世界注入突发变数/天灾/情报
CMD_ALTER_CHARACTER = "alter_character"  # 上帝干预：篡改特定角色心境/动机/状态

# IPC 目录名（纯文件系统，供 .venv-simulation 无 Flask 环境使用）
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

# ---------------------------------------------------------------- 数据模型

@dataclass
class WorldLocation:
    """世界地点"""
    id: str
    name: str
    description: str = ""

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], name=d.get("name", d["id"]), description=d.get("description", ""))


@dataclass
class WorldCharacter:
    """世界角色"""
    id: str
    name: str
    persona: str = ""
    location: str = ""
    goal: str = ""
    knowledge: List[str] = field(default_factory=list)
    # 角色已知的世界规则 id；默认空列表 = 知道全部规则；若非空则 observe 只展示其中的规则
    known_rules: List[str] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)  # 动态状态（体力、心情等）
    active: bool = True

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            persona=d.get("persona", ""),
            location=d.get("location", ""),
            goal=d.get("goal", ""),
            knowledge=d.get("knowledge", []),
            known_rules=d.get("known_rules", []),
            state=d.get("state", {}),
        )


@dataclass
class WorldRule:
    """世界规则"""
    id: str
    description: str

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], description=d.get("description", ""))


@dataclass
class WorldEvent:
    """世界事件（模拟历史）"""
    step: int
    time: str
    character_id: str
    character_name: str
    action_type: str       # move / talk / use / wait / ...
    action_desc: str       # 自然语言描述
    result: str            # 执行结果
    id: str = ""
    location: str = ""
    target_id: str = ""
    approved: bool = True  # 规则校验是否通过
    detail: Dict[str, Any] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)  # 关联的最近事件 id（因果/剧情链）

    def to_dict(self):
        return asdict(self)

    def to_text(self):
        return f"[{self.time}] {self.character_name} 在{self.location}：{self.action_desc} → {self.result}"


# ---------------------------------------------------------------- 动作解析

# 动作意图关键词（轻量解析，不依赖 LLM）
ACTION_INTENTS = [
    ("move", ["前往", "走去", "走向", "走出", "去往", "来到", "离开", "去", "走到", "返回", "进入", "赶到", "赶到"]),
    ("talk", ["对", "告诉", "问", "打听", "说", "交谈", "聊天", "询问", "分享", "搭话", "喊"]),
    ("use", ["使用", "施展", "施放", "拿起", "喝", "吃", "用", "端起"]),
    ("trade", ["买", "卖", "交易", "购买", "收购"]),
    ("explore", ["看看", "观察", "查看", "探索", "巡视", "检查", "张望", "环顾", "四处"]),
    ("wait", ["等待", "等着", "待", "休息", "想想", "停下"]),
]

# 动作目标截断词：遇到这些词说明主要目标已结束（后面是次要从句）
TARGET_STOPWORDS = ["然后", "接着", "顺便", "同时", "为了", "寻找", "看看", "打听", "询问", "找"]


def parse_action(text: str) -> Dict[str, Any]:
    """从自然语言动作中解析出结构化动作（轻量规则解析）"""
    text_clean = text.strip()
    best = {"type": "wait", "desc": text_clean, "target": "", "location": ""}
    best_priority = -1
    for intent, keywords in ACTION_INTENTS:
        for kw in keywords:
            idx = text_clean.find(kw)
            if idx != -1:
                # 优先级：匹配位置越靠前越可能是主要动作
                priority = len(text_clean) - idx
                if priority > best_priority:
                    best_priority = priority
                    target = text_clean[idx + len(kw):].strip("。！？!?，, ")
                    # 截断次要从句
                    for stop in TARGET_STOPWORDS:
                        stop_idx = target.find(stop)
                        if stop_idx > 0:
                            target = target[:stop_idx].strip("，, ")
                            break
                    best = {
                        "type": intent,
                        "desc": text_clean,
                        "target": target[:40],
                        "location": "",
                    }
    return best


# ---------------------------------------------------------------- 世界环境

class WorldEnv:
    """世界环境：维护世界状态，执行动作，推进时钟"""

    def __init__(self, config: Dict[str, Any]):
        wc = config.get("world", {})
        self.world_name = wc.get("name", "世界")
        self.time_step_minutes = int(wc.get("time_step_minutes", 60))
        self.total_steps = int(wc.get("total_steps", 10))
        self.current_step = 0
        self.start_step = 1  # 续推时从历史最后一步的下一步开始
        # 灵活时间模式：
        # - "minutes": 固定每步分钟数（默认，适合舆情/短时推演）
        # - "narrative": 叙事时间跳跃，使用 time_jumps 列表作为每步时间标签
        self.time_mode = str(wc.get("time_mode") or "minutes")
        self.time_jumps = list(wc.get("time_jumps") or []) if isinstance(wc.get("time_jumps"), list) else []
        self.story_summary_mode = str(wc.get("story_summary_mode") or "rule")  # rule | llm
        self.max_concurrency = int(wc.get("max_concurrency") or max(1, len(config.get("characters", []) or [])))
        self.current_step_label = ""
        try:
            self.current_time = datetime.fromisoformat(wc.get("initial_time", "2026-01-01 08:00"))
        except ValueError:
            self.current_time = datetime(2026, 1, 1, 8, 0)

        self.locations = {loc["id"]: WorldLocation.from_dict(loc) for loc in config.get("locations", [])}
        self.characters = {ch["id"]: WorldCharacter.from_dict(ch) for ch in config.get("characters", [])}
        self.rules = [WorldRule.from_dict(r) for r in config.get("rules", [])]

        # 空间图：location -> 相邻 location（可移动）
        self.adjacency: Dict[str, List[str]] = {}
        for loc in self.locations.values():
            self.adjacency[loc.id] = []
        for edge in config.get("connections", []):
            a, b = edge[0], edge[1]
            self.adjacency.setdefault(a, []).append(b)
            self.adjacency.setdefault(b, []).append(a)

        self.events: List[WorldEvent] = []
        self.history: List[str] = []
        self.story_summary: List[str] = []  # 每步一句剧情脉络（长程记忆）
        self.active_variables: List[Dict[str, Any]] = []  # 上帝干预：当前世界生效中的突发变数/异变/外力

        # IPC 控制（暂停/停止/采访/上帝干预），无则默认为 None
        self.ipc: Optional["WorldIPCHandler"] = None

        # 最近一次感知中被过滤（隐藏）的信息列表，供 run 循环写入事件 detail.filtered
        self._last_filtered: List[Dict[str, Any]] = []

    def attach_ipc(self, simulation_dir: str):
        """绑定 IPC 处理器（命令目录位于 simulation_dir 下）"""
        self.ipc = WorldIPCHandler(simulation_dir)

    # ---------- IPC ----------

    async def _process_ipc(self, llm_call) -> Optional[bool]:
        """
        处理一条 IPC 命令。返回控制信号：
            None  -> 无命令，继续执行
            True  -> 应终止主循环（stop）
            False -> 不应终止，继续（pause/resume/interview 已处理）
        若未绑定 IPC，直接返回 None。
        """
        if not self.ipc:
            return None
        cmd = self.ipc.poll_command()
        if cmd is None:
            return None

        command_id = cmd.get("command_id", "")
        ctype = cmd.get("command_type", "")
        args = cmd.get("args", {}) or {}

        if ctype == CMD_PAUSE:
            self.ipc.paused = True
            self.ipc.update_status("paused")
            # 返回 False：继续进行暂停循环之外的处理（不终止）
            self.ipc.send_response(
                command_id, "completed", result={"paused": True}
            )
            print("  ⏸ 收到暂停命令，模拟已暂停")
            return False

        if ctype == CMD_RESUME:
            self.ipc.paused = False
            self.ipc.update_status("running")
            self.ipc.send_response(
                command_id, "completed", result={"paused": False}
            )
            print("  ▶ 收到恢复命令，模拟继续")
            return False

        if ctype == CMD_STOP:
            self.ipc.update_status("stopped")
            self.ipc.send_response(
                command_id, "completed", result={"stopped": True}
            )
            print("  ⏹ 收到停止命令，模拟即将终止")
            return True

        if ctype == CMD_INTERVIEW:
            await self._handle_interview(command_id, args, llm_call)
            return False

        if ctype == CMD_INJECT_VARIABLE:
            await self._handle_inject_variable(command_id, args)
            return False

        if ctype == CMD_ALTER_CHARACTER:
            await self._handle_alter_character(command_id, args)
            return False

        # 未知命令：响应错误但不中断
        self.ipc.send_response(command_id, "failed", error=f"未知命令类型: {ctype}")
        return False

    async def _handle_inject_variable(self, command_id: str, args: Dict[str, Any]):
        """上帝干预：向世界沙盘注入突发变数（天灾/异变/外力入局/情报泄露）"""
        var_text = str(args.get("variable") or args.get("content") or args.get("prompt") or "").strip()
        var_kind = str(args.get("kind") or "anomaly").strip()
        if not var_text:
            self.ipc.send_response(command_id, "failed", error="变数内容不能为空")
            return

        var_entry = {
            "id": f"var_{len(self.active_variables) + 1}",
            "kind": var_kind,
            "text": var_text,
            "step": self.current_step,
            "time": self.time_str(),
        }
        self.active_variables.append(var_entry)

        # 记录为显式的上帝干预全局事件
        god_event = WorldEvent(
            step=self.current_step,
            time=self.time_str(),
            character_id="god_author",
            character_name="👑 创作者干预",
            action_type="god_variable",
            action_desc=f"【上帝变数注入】{var_text}",
            result="世界法则与局势发生剧烈震荡，所有角色均受到强烈冲击",
            id=f"ev_{self.current_step}_god_{len(self.events)}",
            location="全域世界",
            approved=True,
            detail={"variable": var_entry},
        )
        self.events.append(god_event)
        self.history.append(god_event.to_text())
        print(f"  👑 [上帝干预] 注入突发变数: {var_text}")

        self.ipc.send_response(command_id, "completed", result={
            "variable": var_entry,
            "active_variables_count": len(self.active_variables),
        })

    async def _handle_alter_character(self, command_id: str, args: Dict[str, Any]):
        """上帝干预：篡改特定角色的心境/即时动机/目标/状态"""
        character_name = str(args.get("character_name", "")).strip()
        new_goal = str(args.get("goal") or "").strip()
        new_persona_delta = str(args.get("persona_delta") or args.get("mindset") or "").strip()

        char = None
        if character_name:
            char = self.characters.get(character_name)
            if char is None:
                char = next((c for c in self.characters.values() if c.name == character_name), None)

        if char is None:
            self.ipc.send_response(command_id, "failed", error=f"未找到角色: {character_name}")
            return

        if new_goal:
            char.goal = new_goal
        if new_persona_delta:
            char.persona = f"{char.persona} 【心境突变：{new_persona_delta}】"

        # 记录为角色心境突变事件
        shift_desc = f"【心境动机重塑】{char.name} 的目标被重塑为：{new_goal or '未变'}，心境转为：{new_persona_delta or '狂化/决绝'}"
        god_event = WorldEvent(
            step=self.current_step,
            time=self.time_str(),
            character_id="god_author",
            character_name="👑 创作者干预",
            action_type="mindset_shift",
            action_desc=shift_desc,
            result=f"{char.name} 的行为模式与抉择倾向已彻底改变",
            id=f"ev_{self.current_step}_mind_{char.id}_{len(self.events)}",
            location=self.locations.get(char.location, WorldLocation("?", "?")).name,
            approved=True,
            detail={"character_id": char.id, "new_goal": new_goal, "persona_delta": new_persona_delta},
        )
        self.events.append(god_event)
        self.history.append(god_event.to_text())
        print(f"  🧠 [心境重塑] {char.name}: {shift_desc}")

        self.ipc.send_response(command_id, "completed", result={
            "character_id": char.id,
            "character_name": char.name,
            "current_goal": char.goal,
        })

    async def _handle_interview(self, command_id: str, args: Dict[str, Any], llm_call):
        """采访指定角色：用 LLM 以该角色的身份和当前感知回答采访问题"""
        character_name = str(args.get("character_name", "")).strip()
        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            self.ipc.send_response(command_id, "failed", error="采访问题不能为空")
            return

        # 按 id 或 name 匹配角色
        char = None
        if character_name:
            char = self.characters.get(character_name)
            if char is None:
                char = next(
                    (c for c in self.characters.values() if c.name == character_name),
                    None,
                )
        if char is None:
            self.ipc.send_response(
                command_id, "failed", error=f"未找到角色: {character_name or '（未指定）'}"
            )
            return

        observation = self.observe(char)
        interview_prompt = (
            f"你是{char.name}。{char.persona}\n"
            f"你的身份知识：{'、'.join(char.knowledge) if char.knowledge else '无'}\n"
            f"你当前的处境：\n{observation}\n\n采访者问：{prompt}\n"
            "请以该角色的第一人称身份，用 1-3 句中文自然、真实地回答，不要解释格式。"
        )
        try:
            answer = await llm_call(interview_prompt)
        except Exception as e:
            self.ipc.send_response(command_id, "failed", error=f"采访 LLM 调用失败: {e}")
            print(f"  🎙 角色 {char.name} 采访失败: {e}")
            return

        self.ipc.send_response(
            command_id,
            "completed",
            result={
                "character_id": char.id,
                "character_name": char.name,
                "prompt": prompt,
                "answer": answer.strip(),
            },
        )
        print(f"  🎙 角色 {char.name} 接受了采访")

    async def _wait_while_paused(self, llm_call):
        """
        若处于暂停状态，阻塞等待恢复/停止；暂停期间仍可响应采访命令。
        返回 True 表示收到停止命令需终止循环。
        """
        while self.ipc and self.ipc.paused:
            cmd = self.ipc.poll_command()
            if cmd is None:
                await asyncio.sleep(0.5)
                continue
            # 响应恢复/停止/采访
            stop = await self._process_ipc(llm_call)
            if stop:
                return True
        return False

    # ---------- 时钟 ----------

    def advance_clock(self):
        """推进世界时间（current_step 由主循环统一递增）"""
        if self.time_mode == "narrative":
            # 叙事时间跳跃：按用户提供的标签推进，不再使用固定分钟
            idx = self.current_step - 1
            self.current_step_label = (
                self.time_jumps[idx] if 0 <= idx < len(self.time_jumps) else f"第 {self.current_step} 阶段"
            )
            return
        self.current_step_label = ""
        self.current_time += timedelta(minutes=self.time_step_minutes)

    def time_str(self) -> str:
        if self.time_mode == "narrative" and self.current_step_label:
            return self.current_step_label
        return self.current_time.strftime("%m-%d %H:%M")

    # ---------- 感知 ----------

    def _recent_context(self, character: WorldCharacter, limit: int = 6, max_len: int = 60) -> str:
        """返回该角色最近参与/目睹的事件摘要（供决策提示词注入，形成角色记忆）。

        - 只取该角色相关的事件（本角色发起的，或结果/描述中出现其名的）；
        - 按事件顺序取最近 limit 条，每条截断 max_len 字符；
        - 无相关事件返回空串。
        """
        relevant = []
        for ev in self.events:
            if ev.character_id != character.id and not (
                character.name and character.name in (ev.action_desc or ev.result or "")
            ):
                continue
            body = f"{ev.action_desc or ''} {ev.result or ''}".strip()
            relevant.append(f"{ev.character_name}：{body}")
        lines = []
        for text in relevant[-limit:]:
            line = "- " + str(text).strip().replace("\n", " ")
            if len(line) > max_len:
                line = line[:max_len] + "…"
            lines.append(line)
        return "\n".join(lines)

    def _global_context(self, limit: int = 8, max_len: int = 80) -> str:
        """返回最近全局事件摘要（不限角色），让角色感知世界其他地方发生了什么。"""
        lines = []
        for ev in self.events[-limit:]:
            body = f"{ev.character_name} 在 {ev.location}：{ev.action_desc or ''} {ev.result or ''}".strip()
            if len(body) > max_len:
                body = body[:max_len] + "…"
            lines.append("- " + body.replace("\n", " "))
        return "\n".join(lines)

    def _world_memory(self, max_len: int = 300) -> str:
        """世界记忆层：作者设定的世界名、地点、规则等长期事实。"""
        lines = [f"世界：{self.world_name}"]
        if self.locations:
            lines.append("地点：" + "、".join(l.name for l in list(self.locations.values())[:10]))
        if self.rules:
            lines.append("规则：" + "；".join(r.description for r in self.rules[:6]))
        text = "\n".join(lines)
        return text[:max_len]

    def _story_context(self, limit: int = 4, max_len: int = 80) -> str:
        """返回最近几步的剧情脉络摘要（长程记忆），帮助角色把握主线。"""
        lines = []
        for text in self.story_summary[-limit:]:
            t = str(text or "").strip().replace("\n", " ")
            if len(t) > max_len:
                t = t[:max_len] + "…"
            lines.append("- " + t)
        return "\n".join(lines)

    def observe(self, character: WorldCharacter) -> str:
        """角色感知：位置 + 在场角色 + 环境 + 规则 + 时间（含视角过滤与知识边界）

        视角过滤规则：
        - 地点：不在角色 knowledge 中的地点只显示名称，不显示描述
        - 其他角色：只显示名字与 persona 第一句，绝不泄露其 goal
        - 规则：若角色的 known_rules 非空，只展示 known_rules 中的规则

        被隐藏的信息记录到 self._last_filtered，供主循环写入事件 detail.filtered。
        """
        lines = [f"现在是{self.time_str()}，第{self.current_step}步。"]
        filtered: List[Dict[str, Any]] = []

        # ---- 地点视角 ----
        loc = self.locations.get(character.location)
        if loc:
            if self._knows_place(character, loc):
                lines.append(f"你位于【{loc.name}】：{loc.description}")
            else:
                # 不在 knowledge 中：只显示名称，隐藏描述
                lines.append(f"你位于【{loc.name}】")
                filtered.append({"kind": "location_detail", "target": loc.id, "name": loc.name})
        else:
            lines.append("你位于一片未知之地。")

        # ---- 在场角色（只显示名字与 persona 第一句，隐藏其 goal）----
        present = [
            c for c in self.characters.values()
            if c.id != character.id and c.location == character.location
        ]
        if present:
            parts = []
            for c in present:
                peep = self._persona_first_sentence(c)
                filtered.append({"kind": "character_goal", "target": c.id, "name": c.name})
                parts.append(f"{c.name}（{peep}）" if peep else c.name)
            lines.append(f"此刻在场的还有：{'、'.join(parts)}")
        else:
            lines.append("此刻这里没有其他人。")

        # ---- 规则（known_rules 知识边界）----
        # 默认空列表 = 知道全部规则；非空则只展示 known_rules 中的规则
        if character.known_rules:
            shown = [r for r in self.rules if r.id in character.known_rules]
            for r in self.rules:
                if r.id not in character.known_rules:
                    filtered.append({"kind": "rule", "rule_id": r.id})
        else:
            shown = self.rules
        if shown:
            rules = "；".join(r.description for r in shown)
            lines.append(f"世界规则：{rules}")

        # ---- 自身目标（角色自己的目标可见）----
        if character.goal:
            lines.append(f"你的目标：{character.goal}")

        # 可去地点提示（帮助 LLM 输出可控动作）
        reachable = [
            loc.name for loc in self.locations.values()
            if loc.id != character.location
        ]
        if reachable:
            lines.append(f"你可以前往的地点：{'、'.join(reachable)}")

        lines.append("请用一句话描述你接下来要做的动作（例如：前往老橡木酒馆、向卡拉打听城门的事）。")

        # 记录本次感知中被过滤的信息（供事件 detail.filtered 审查）
        self._last_filtered = filtered
        return "\n".join(lines)

    def _knows_place(self, character: WorldCharacter, loc: WorldLocation) -> bool:
        """角色是否"知道"某地点（knowledge 与地点名/id 匹配）"""
        if not character.knowledge:
            return True  # 无 knowledge 视为都认识，保持旧行为
        for k in character.knowledge:
            if k and (k in loc.name or loc.name in k or k == loc.id):
                return True
        return False

    @staticmethod
    def _persona_first_sentence(character: WorldCharacter) -> str:
        """取 persona 的第一句（按中文/英文句号切分）"""
        text = (character.persona or "").strip()
        if not text:
            return ""
        # 按 。！？!? . 切出第一句
        import re as _re
        m = _re.split(r'[。！？!?]', text)
        return m[0].strip() if m else text

    # ---------- 规则校验 ----------

    def check_rules(self, character: WorldCharacter, action: Dict[str, Any]) -> tuple[bool, str]:
        """规则引擎：校验动作合法性（轻量实现，关键词规则）"""
        desc = action.get("desc", "")
        loc = self.locations.get(character.location)
        in_town = loc is not None and ("镇" in loc.name or "城" in loc.name)
        for rule in self.rules:
            rl = rule.description
            # 示例规则：城镇内禁止火焰魔法
            if "禁止" in rl and any(kw in desc for kw in ("火", "火焰", "禁咒", "火球", "焚烧")):
                if in_town:
                    return False, f"违反规则【{rule.description}】"
        # 魔法代价规则：记录到结果里（不阻止，但提示）
        return True, ""

    # ---------- 动作执行 ----------

    def execute(self, character: WorldCharacter, action: Dict[str, Any]) -> str:
        """执行动作，更新世界状态，返回结果描述"""
        atype = action.get("type", "wait")
        target = action.get("target", "")

        if atype == "move":
            # 尝试移动到目标地点：先精确匹配 target，再在整句里模糊匹配
            candidates = []
            for loc_id, loc in self.locations.items():
                if loc.name in target or loc_id in target:
                    candidates.append((loc_id, loc, 2))  # 精确命中优先级 2
                elif loc.name in action.get("desc", ""):
                    candidates.append((loc_id, loc, 1))  # 整句命中优先级 1
            if candidates:
                candidates.sort(key=lambda x: -x[2])
                loc_id, loc, _ = candidates[0]
                if loc_id == character.location:
                    return f"你已经在【{loc.name}】了"
                character.location = loc_id
                return f"你来到了【{loc.name}】"
            return f"未能找到地点「{target}」，你留在原地"

        if atype == "talk":
            # 与在场角色交谈（对话结果记录，不真正调 LLM 回复——最小实现）
            present = [
                c for c in self.characters.values()
                if c.id != character.id and c.location == character.location
            ]
            if present:
                names = "、".join(c.name for c in present)
                return f"你与{names}交谈：{target or '（闲聊）'}"
            return "这里没有可以交谈的对象，你自言自语"

        if atype == "use":
            return f"你使用了「{target or '物品'}」"

        if atype == "trade":
            return f"你试图交易：{target or '（未指明物品）'}"

        if atype == "explore":
            loc = self.locations.get(character.location)
            return f"你仔细观察了周围：{loc.description if loc else '空无一物'}"

        return "你停下来想了想，暂时没有行动"

    def load_history(self, events: List[Dict[str, Any]], start_step: int = 1):
        """续推：把历史事件载入环境，作为角色记忆与剧情上下文；从 start_step 继续跑。"""
        self.events = []
        for e in events:
            try:
                self.events.append(WorldEvent(**e))
            except Exception:
                continue
        self.history = [e.to_text() for e in self.events]
        # 重建剧情脉络摘要（长程记忆）
        by_step = {}
        for e in self.events:
            by_step.setdefault(e.step, []).append(e)
        self.story_summary = []
        for step in sorted(by_step):
            evs = by_step[step]
            self.story_summary.append(
                f"第{step}步：" + "；".join(f"{e.character_name}{e.action_desc[:30]}" for e in evs[:6])[:240]
            )
        self.start_step = max(1, int(start_step))
        # 固定分钟模式：把时钟拨到历史最后一条事件的时间，保证时间连续
        if self.time_mode == "minutes" and self.events:
            last_time = self.events[-1].time
            try:
                self.current_time = datetime.strptime(last_time, "%m-%d %H:%M").replace(year=self.current_time.year)
            except Exception:
                pass

    # ---------- 主循环 ----------

    async def run(self, llm_call) -> List[WorldEvent]:
        """运行完整模拟循环。llm_call(text) -> str 是异步 LLM 调用。"""
        # 若绑定了 IPC，标记为运行状态
        final_step = self.start_step + self.total_steps - 1
        if self.ipc:
            self.ipc.update_status("running")
            self.ipc.write_progress(self.start_step - 1, final_step, "准备开始")

        _stopped = False
        for step in range(self.start_step, self.start_step + self.total_steps):
            # 每步开始前处理 IPC 命令
            if await self._process_ipc(llm_call):
                _stopped = True
                break
            # 若处于暂停状态，阻塞等待恢复/停止
            if self.ipc and self.ipc.paused:
                if await self._wait_while_paused(llm_call):
                    _stopped = True
                    break

            self.current_step = step
            if self.ipc:
                self.ipc.write_progress(step, final_step, f"第 {step}/{final_step} 步")
            self.advance_clock()
            print(f"\n{'='*56}\n第 {step} 步 · {self.time_str()}\n{'='*56}")

            active_chars = [c for c in self.characters.values() if c.active]
            # 1. 感知与提示词准备（本地计算，顺序执行；过滤信息按角色留存）
            prepared = []
            for char in active_chars:
                observation = self.observe(char)
                filtered = list(self._last_filtered)
                _goal = (char.goal or "").strip() or "按人设自然行动"
                _recent = self._recent_context(char)
                _global = self._global_context()
                _world_mem = self._world_memory()
                _vars_block = ""
                if self.active_variables:
                    _vars_lines = ["【🚨 世界突发重大变数 / 上帝干预已降临】："]
                    for v in self.active_variables[-3:]:
                        _vars_lines.append(f"· {v.get('text')}")
                    _vars_lines.append("【重要警告】：以上突发异变/天灾/外力直接影响整个世界格局，你必须在接下来的行动中对该变数做出最直接的应急反应、抉择或应对！")
                    _vars_block = "\n".join(_vars_lines) + "\n\n"

                prompt = (
                    f"你是{char.name}。{char.persona}\n"
                    f"当前目标：{_goal}\n"
                    f"你的身份知识：{'、'.join(char.knowledge) if char.knowledge else '无'}\n"
                    f"{_vars_block}"
                    f"你亲身经历/目睹的最近事（角色记忆）：\n{_recent or '（暂无）'}\n\n"
                    f"故事脉络（最近几步）：\n{_story or '（暂无）'}\n\n"
                    f"世界最新动态（你可能听说或需要留意）：\n{_global or '（暂无）'}\n\n"
                    f"世界记忆（作者设定与规则）：\n{_world_mem or '（暂无）'}\n\n"
                    f"{observation}\n"
                    f"请严格以{char.name}的身份与性格行动：语气、价值观、口癖都符合人物设定（persona），"
                    f"动作要尽量衔接上面提到的最近事件、突发变数和世界动态，推动剧情连贯发展，"
                    f"不要说出超出其身份与见闻的内容。"
                )
                prepared.append((char, observation, prompt, filtered))

            # 2. 同一步内多角色并行 LLM 决策（大幅提升效率）
            sem = asyncio.Semaphore(max(1, self.max_concurrency))

            async def _decide(prompt):
                async with sem:
                    try:
                        return await llm_call(prompt)
                    except Exception as e:
                        print(f"  ⚠ LLM 调用失败: {e}")
                        return "我停下来等待。"

            decisions = await asyncio.gather(*(_decide(p) for _, _, p, _ in prepared))

            # 3. 顺序执行动作（决策基于同一时刻世界状态，执行串行保证状态一致）
            for (char, observation, _prompt, filtered), decision in zip(prepared, decisions):
                # 解析
                action = parse_action(decision)
                # 3b. 修正：move 的目标是角色名 → 实际是交谈
                if action["type"] == "move":
                    for other in self.characters.values():
                        if other.id != char.id and (
                            other.name in action["target"] or other.name in action["desc"]
                        ):
                            action["type"] = "talk"
                            action["target"] = other.name
                            break
                if action["type"] == "wait":
                    action["target"] = ""
                # 4. 校验
                approved, reason = self.check_rules(char, action)
                # 5. 执行
                result = self.execute(char, action)
                # 6. 记录事件
                event = WorldEvent(
                    step=step,
                    time=self.time_str(),
                    character_id=char.id,
                    character_name=char.name,
                    action_type=action["type"],
                    action_desc=decision.strip(),
                    result=result,
                    id=f"ev_{step}_{char.id}_{len(self.events)}",
                    location=self.locations.get(char.location, WorldLocation("?", "?")).name,
                    approved=approved,
                    detail={
                        "rule_check": reason,
                        "filtered": filtered,
                    },
                    links=[e.id for e in self.events[-3:] if e.id],
                )
                self.events.append(event)
                self.history.append(event.to_text())
                flag = "✓" if approved else "✗"
                print(f"  {flag} {char.name}（{event.location}）")
                print(f"    决策: {decision.strip()[:80]}")
                print(f"    动作: [{action['type']}] {action['target'][:30]}")
                if not approved:
                    print(f"    规则: {reason}")
                print(f"    结果: {result[:60]}")
            # 每步结束后追加一句剧情脉络（长程记忆；可切换 LLM 生成）
            step_evs = [e for e in self.events if e.step == step]
            if step_evs:
                summary = ""
                if self.story_summary_mode == "llm":
                    try:
                        _step_text = "；".join(
                            f"{e.character_name}{e.action_desc}" for e in step_evs[:8]
                        )
                        summary = await llm_call(
                            f"用一句话概括这一阶段世界发生的事，要求连贯自然：{_step_text}"
                        )
                        summary = (summary or "").strip()
                    except Exception:
                        summary = ""
                if not summary:
                    summary = f"第{step}步：" + "；".join(
                        f"{e.character_name}{e.action_desc[:30]}" for e in step_evs[:6]
                    )
                self.story_summary.append(summary[:240])
            if _stopped:
                break

        # 模拟结束时若仍绑定 IPC，更新状态文件
        if self.ipc:
            self.ipc.update_status("stopped")

        return self.events


# ---------------------------------------------------------------- IPC 处理器

class WorldIPCHandler:
    """
    世界模拟 IPC 处理器（纯文件系统，供 .venv-simulation 无 Flask 环境使用）

    与后端 WorldSimulationService 通过命令/响应目录交互：
        - 命令目录：<sim_dir>/ipc_commands/<command_id>.json
        - 响应目录：<sim_dir>/ipc_responses/<command_id>.json
        - 环境状态：<sim_dir>/env_status.json
    支持命令：pause / resume / stop / interview
    """

    def __init__(self, simulation_dir: str):
        self.simulation_dir = simulation_dir
        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)

        # 确保目录存在
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

        self.paused = False

    def update_status(self, status: str):
        """更新环境状态文件"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "paused": self.paused,
                "timestamp": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def write_progress(self, current_step: int, total_steps: int, message: str = ""):
        """写进度文件，供后端轮询展示“第 X 步 / 共 Y 步”"""
        progress_file = os.path.join(self.simulation_dir, "progress.json")
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump({
                "current_step": current_step,
                "total_steps": total_steps,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def poll_command(self) -> Optional[Dict[str, Any]]:
        """轮询获取最早的待处理命令（按修改时间排序）"""
        if not os.path.isdir(self.commands_dir):
            return None
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                try:
                    command_files.append((filepath, os.path.getmtime(filepath)))
                except OSError:
                    continue
        command_files.sort(key=lambda x: x[1])
        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def send_response(
        self,
        command_id: str,
        status: str,
        result: Dict[str, Any] = None,
        error: str = None,
    ):
        """发送响应并删除命令文件"""
        response = {
            "command_id": command_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        try:
            os.remove(os.path.join(self.commands_dir, f"{command_id}.json"))
        except OSError:
            pass


# ---------------------------------------------------------------- LLM 调用

def create_llm_caller(config: Dict[str, Any]):
    """创建异步 LLM 调用器（OpenAI 兼容，直接 requests 异步）"""
    llm_cfg = config.get("llm", {})
    api_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
    base_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    model = llm_cfg.get("model") or os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    async def call(text: str) -> str:
        if not api_key:
            return "在原地观察周围局势并思索对策。"

        import httpx
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是世界模拟中的角色。根据你的身份、观察、最近经历和世界动态，用一句中文描述你接下来要做的动作。动作要自然衔接最近发生的事，推动剧情连贯发展；不要解释，直接输出动作。"},
                {"role": "user", "content": text},
            ],
            "temperature": 0.8,
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        # 空响应与异常重试
        last_content = ""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices and isinstance(choices[0], dict):
                            last_content = choices[0].get("message", {}).get("content") or ""
            except Exception as e:
                print(f"  ⚠ [LLM] 调用异常 (尝试 {attempt + 1}/3): {e}")
            if last_content.strip():
                return last_content.strip()
            await asyncio.sleep(0.5 + attempt * 0.5)

        return "在原地调整状态，密切留意周围动向。"

    return call


# ---------------------------------------------------------------- 入口

def main():
    parser = argparse.ArgumentParser(description="世界模拟运行器")
    parser.add_argument("--config", required=True, help="世界配置文件路径")
    parser.add_argument("--out", default="", help="事件输出 JSON 路径（默认打印）")
    parser.add_argument(
        "--ipc-dir", default="",
        help="IPC 目录（后端创建的模拟目录，用于 pause/resume/stop/interview；缺省时若配置所在目录已含 ipc_commands 则自动启用）",
    )
    parser.add_argument("--resume-events", default="", help="续推：历史事件 JSON 文件路径")
    parser.add_argument("--start-step", type=int, default=1, help="续推起始步号（默认 1）")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    env = WorldEnv(config)

    # 续推：载入历史事件，让新推演从历史末尾继续
    if args.resume_events and os.path.exists(args.resume_events):
        with open(args.resume_events, "r", encoding="utf-8") as f:
            history_events = json.load(f)
        env.load_history(history_events, start_step=args.start_step)
        print(f"   续推：已载入 {len(history_events)} 条历史事件，从第 {args.start_step} 步继续")

    llm_call = create_llm_caller(config)

    # 启用 IPC 控制：显式传入 --ipc-dir，或配置所在目录已被后端创建 ipc_commands
    if args.ipc_dir:
        env.attach_ipc(args.ipc_dir)
    elif os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(args.config)), "ipc_commands")):
        env.attach_ipc(os.path.dirname(os.path.abspath(args.config)))

    print(f"🌍 世界：{env.world_name}")
    print(f"   地点：{', '.join(l.name for l in env.locations.values())}")
    print(f"   角色：{', '.join(c.name for c in env.characters.values())}")
    print(f"   规则：{'; '.join(r.description for r in env.rules)}")
    print(f"   时钟：每步 {env.time_step_minutes} 分钟，共 {env.total_steps} 步")
    if env.ipc:
        print("   控制：IPC 已启用（pause/resume/stop/interview）")

    events = asyncio.run(env.run(llm_call))

    print(f"\n{'='*56}\n模拟结束 · 共 {len(events)} 个事件\n{'='*56}")
    for e in events:
        print(e.to_text())

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in events], f, ensure_ascii=False, indent=2)
        print(f"\n事件已保存: {args.out}")


if __name__ == "__main__":
    main()
