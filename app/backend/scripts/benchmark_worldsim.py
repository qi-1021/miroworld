#!/usr/bin/env python3
"""世界模拟性能基准（不联网，使用假 LLM）。

用法：
    python scripts/benchmark_worldsim.py --steps 3 --characters 4
"""

import argparse
import asyncio
import time

from run_world_simulation import WorldEnv


def build_config(steps, chars):
    return {
        "world": {
            "name": "基准世界",
            "time_step_minutes": 30,
            "total_steps": steps,
            "initial_time": "2026-01-01 08:00",
            "max_concurrency": max(1, chars),
        },
        "locations": [
            {"id": "market", "name": "集市", "description": "广场"},
            {"id": "gate", "name": "城门", "description": "城门"},
        ],
        "connections": [["market", "gate"]],
        "characters": [
            {
                "id": f"c{i}",
                "name": f"角色{i}",
                "persona": "普通居民",
                "location": "market" if i % 2 == 0 else "gate",
                "goal": "正常生活",
                "knowledge": [],
            }
            for i in range(chars)
        ],
        "rules": [],
    }


async def fake_llm(text):
    return "前往城门"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--characters", type=int, default=4)
    args = parser.parse_args()

    env = WorldEnv(build_config(args.steps, args.characters))
    start = time.time()
    events = asyncio.run(env.run(fake_llm))
    elapsed = time.time() - start
    print(f"steps={args.steps} characters={args.characters} events={len(events)} elapsed={elapsed:.2f}s "
          f"events_per_sec={len(events) / elapsed:.2f}")


if __name__ == "__main__":
    main()
