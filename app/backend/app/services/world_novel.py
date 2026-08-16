"""
世界模拟 → 小说续写服务（World Novel）

输入 = 一条世界模拟（simulation_id），读取其事件流（events.json）、世界配置
（world_config.json）、当前项目时间线，以及已裁定冲突（accepted/justified/
dismissed），用 LLM 生成“简洁续写的小说正文”，而不是分析报告。

输出：
- novel.md    落盘到 data/world-sim/<project_id>/<simulation_id>/novel.md
- novel.json  结构化 {text, chapters:[{title, content}]}（供 GET 接口返回）

降级策略：
- 模拟不存在/非本项目 → ValueError
- 事件为空 → 基于世界配置与时间线自然续写
- LLM 调用失败 → 抛异常由调用方处理
"""

import os
import json
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json, atomic_write_text

logger = get_logger('mirofish.world_novel')

WORLD_SIM_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'world-sim',
)

NOVEL_PROMPT = """你是一名小说续写作者。根据一场已经推演完成的世界模拟结果（事件流 + 世界配置）
与当前项目时间线，把故事继续写下去。

要求：
1. 以“最终推演确定的内容”为准，续写简洁、叙事化的小说正文，而不是分析报告。
2. 承接当前时间线与模拟事件中已经确定的状态、人物关系、地点和结果。
3. 后续情节可以从推演确定内容自然展开，也可以小幅收束/留钩子，但不要偏离已确定设定。
4. 语言精炼，符合已有文本的中文叙事风格；篇幅控制在 1500-4000 字。
5. 已裁定冲突（accepted/justified/dismissed）按裁定处理，不要再当矛盾重复提出。

输出 JSON（必须严格符合以下结构，不要输出其他内容）：
{{
  "text": "<完整小说正文 Markdown>",
  "chapters": [
    {{"title": "章节标题", "content": "本章正文"}}
  ]
}}

世界配置：
{world_config}

模拟事件流：
{events}

当前时间线（最近事件摘要）：
{timeline_context}

已裁定冲突：
{resolved_conflicts}

任务目标（可选）：
{goal}"""


class WorldNovelService:
    """世界模拟小说续写服务"""

    # ---------------- 路径 ----------------

    @classmethod
    def _sim_dir(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(WORLD_SIM_ROOT, project_id, simulation_id)

    @classmethod
    def _events_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'events.json')

    @classmethod
    def _config_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'world_config.json')

    @classmethod
    def _novel_md_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'novel.md')

    @classmethod
    def _novel_json_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'novel.json')

    # ---------------- 数据读取 ----------------

    @classmethod
    def _load_events(cls, project_id: str, simulation_id: str) -> List[Dict[str, Any]]:
        path = cls._events_path(project_id, simulation_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"读取事件流失败: {path}, err={e}")
            return []

    @classmethod
    def _load_world_config(cls, project_id: str, simulation_id: str) -> Dict[str, Any]:
        path = cls._config_path(project_id, simulation_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"读取世界配置失败: {path}, err={e}")
            return {}

    @classmethod
    def _load_timeline_context(cls, project_id: str, limit: int = 30) -> str:
        try:
            from ..services.timeline_service import load_timeline
            events = load_timeline(project_id, None).get("events", [])
            events = sorted(events, key=lambda e: (e.get("sort_lower") or 0))
            lines = []
            for e in events[-limit:]:
                text = str(e.get("summary") or "").strip()
                if text:
                    lines.append(f"- {text}")
            return "\n".join(lines) or "（无）"
        except Exception as e:
            logger.warning(f"读取时间线上下文失败（忽略）: {e}")
            return "（无）"

    @classmethod
    def _load_resolved_conflicts(cls, project_id: str) -> str:
        try:
            from ..services.conflict_detector import load_effective_resolutions
            resolutions = load_effective_resolutions(project_id)
            if not resolutions:
                return "（无）"
            lines = []
            for r in resolutions:
                note = r.get("resolution_note") or r.get("verdict") or ""
                lines.append(f"- {r.get('topic')}（{r.get('status')}）{('：' + note) if note else ''}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"读取已裁定冲突失败（忽略）: {e}")
            return "（无）"

    # ---------------- 生成与存储 ----------------

    @classmethod
    def generate_novel(
        cls,
        project_id: str,
        simulation_id: str,
        llm: Any = None,
    ) -> Dict[str, Any]:
        from ..services.world_simulation import WorldSimulationService

        state = WorldSimulationService.get_state(simulation_id)
        if state is None or state.project_id != project_id:
            raise ValueError("模拟不存在")

        events = cls._load_events(project_id, simulation_id)
        world_config = cls._load_world_config(project_id, simulation_id)
        timeline_context = cls._load_timeline_context(project_id)
        resolved_conflicts = cls._load_resolved_conflicts(project_id)
        goal = str((world_config.get("goal") or state.result.get("goal") or "")).strip()

        client = llm or WorldSimulationService._build_llm_client(project_id)
        prompt = NOVEL_PROMPT.format(
            world_config=json.dumps(world_config, ensure_ascii=False, indent=2) or "（无）",
            events=json.dumps(events, ensure_ascii=False, indent=2) or "（无）",
            timeline_context=timeline_context,
            resolved_conflicts=resolved_conflicts,
            goal=goal or "（无）",
        )
        result = client.chat_json(
            messages=[
                {"role": "system", "content": "你是小说续写作者，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=8192,
        )

        text = str(result.get("text", "")).strip() if isinstance(result, dict) else ""
        chapters = result.get("chapters") if isinstance(result, dict) else []
        if not isinstance(chapters, list):
            chapters = []
        cleaned_chapters = []
        for ch in chapters:
            if isinstance(ch, dict) and ch.get("title") and ch.get("content") is not None:
                cleaned_chapters.append({
                    "title": str(ch.get("title", "")).strip(),
                    "content": str(ch.get("content", "")).strip(),
                })
        if not text:
            text = "\n\n".join(
                f"## {c['title']}\n\n{c['content']}" for c in cleaned_chapters
            )
        novel = {"text": text, "chapters": cleaned_chapters}

        sim_dir = cls._sim_dir(project_id, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        atomic_write_text(cls._novel_md_path(project_id, simulation_id), text)
        atomic_write_json(cls._novel_json_path(project_id, simulation_id), novel)

        logger.info(f"世界小说续写已生成: project={project_id}, sim={simulation_id}, chapters={len(cleaned_chapters)}")
        return novel

    @classmethod
    def load_novel(cls, project_id: str, simulation_id: str) -> Optional[Dict[str, Any]]:
        path = cls._novel_json_path(project_id, simulation_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning(f"读取小说续写失败: {path}, err={e}")
            return None