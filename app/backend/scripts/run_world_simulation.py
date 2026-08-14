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
    location: str = ""
    target_id: str = ""
    approved: bool = True  # 规则校验是否通过
    detail: Dict[str, Any] = field(default_factory=dict)

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

    # ---------- 时钟 ----------

    def advance_clock(self):
        """推进世界时间（current_step 由主循环统一递增）"""
        self.current_time += timedelta(minutes=self.time_step_minutes)

    def time_str(self) -> str:
        return self.current_time.strftime("%m-%d %H:%M")

    # ---------- 感知 ----------

    def observe(self, character: WorldCharacter) -> str:
        """角色感知：位置 + 在场角色 + 环境 + 规则 + 时间"""
        lines = [f"现在是{self.time_str()}，第{self.current_step}步。"]
        loc = self.locations.get(character.location)
        if loc:
            lines.append(f"你位于【{loc.name}】：{loc.description}")
        else:
            lines.append("你位于一片未知之地。")

        present = [
            c for c in self.characters.values()
            if c.id != character.id and c.location == character.location
        ]
        if present:
            names = "、".join(c.name for c in present)
            lines.append(f"此刻在场的还有：{names}")
        else:
            lines.append("此刻这里没有其他人。")

        if self.rules:
            rules = "；".join(r.description for r in self.rules)
            lines.append(f"世界规则：{rules}")

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
        return "\n".join(lines)

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

    # ---------- 主循环 ----------

    async def run(self, llm_call) -> List[WorldEvent]:
        """运行完整模拟循环。llm_call(text) -> str 是异步 LLM 调用。"""
        for step in range(1, self.total_steps + 1):
            self.current_step = step
            self.advance_clock()
            print(f"\n{'='*56}\n第 {step} 步 · {self.time_str()}\n{'='*56}")

            for char in self.characters.values():
                if not char.active:
                    continue
                # 1. 感知
                observation = self.observe(char)
                # 2. 决策（LLM）
                try:
                    decision = await llm_call(
                        f"你是{char.name}。{char.persona}\n你的身份知识：{'、'.join(char.knowledge) if char.knowledge else '无'}\n\n{observation}"
                    )
                except Exception as e:
                    print(f"  ⚠ {char.name} LLM 调用失败: {e}")
                    decision = "我停下来等待。"
                # 3. 解析
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
                    location=self.locations.get(char.location, WorldLocation("?", "?")).name,
                    approved=approved,
                    detail={"rule_check": reason},
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

        return self.events


# ---------------------------------------------------------------- LLM 调用

def create_llm_caller(config: Dict[str, Any]):
    """创建异步 LLM 调用器（OpenAI 兼容，直接 requests 异步）"""
    llm_cfg = config.get("llm", {})
    api_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
    base_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    model = llm_cfg.get("model") or os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini")

    if not api_key:
        raise ValueError("缺少 LLM API Key：请在配置或 LLM_API_KEY 环境变量中提供")

    import httpx

    async def call(text: str) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是世界模拟中的角色。根据你的身份和观察，用一句中文描述你接下来要做的动作。不要解释，直接输出动作。"},
                {"role": "user", "content": text},
            ],
            "temperature": 0.8,
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        # 空响应重试（OpenCode 网关偶发返回空内容）
        last_content = ""
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                last_content = data["choices"][0]["message"]["content"] or ""
            if last_content.strip():
                return last_content
            await asyncio.sleep(1.0 + attempt)
        return "我停下来等待。"

    return call


# ---------------------------------------------------------------- 入口

def main():
    parser = argparse.ArgumentParser(description="世界模拟运行器")
    parser.add_argument("--config", required=True, help="世界配置文件路径")
    parser.add_argument("--out", default="", help="事件输出 JSON 路径（默认打印）")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    env = WorldEnv(config)
    llm_call = create_llm_caller(config)

    print(f"🌍 世界：{env.world_name}")
    print(f"   地点：{', '.join(l.name for l in env.locations.values())}")
    print(f"   角色：{', '.join(c.name for c in env.characters.values())}")
    print(f"   规则：{'; '.join(r.description for r in env.rules)}")
    print(f"   时钟：每步 {env.time_step_minutes} 分钟，共 {env.total_steps} 步")

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
