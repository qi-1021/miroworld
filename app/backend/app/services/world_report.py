"""
世界报告生成服务（World Report）

输入 = 一条世界模拟（simulation_id），读取其事件流（events.json）与世界配置
（world_config.json），用 LLM 生成中文报告，包含：
- 世界编年史：按时间梳理"谁在何时何地做了什么、结果"
- 角色动向：每人目标、行动轨迹、互动关系
- 世界状态与规则遵守：规则被遵守/违反情况（含 approved=false 的事件）
- 推演与建议：下一步可能的发展、可选的 what-if 方向

输出：
- report.md    落盘到 data/world-sim/<project_id>/<simulation_id>/report.md
- report.json  结构化 {text, sections:[{title, content}]}（供 GET 接口返回）

LLM 生成结构：
    {"text": "markdown 全文", "sections": [{"title": "...", "content": "..."}]}
若 LLM 只返回 text，则自动按 Markdown 二级标题（##）切分为节。

降级策略：
- 模拟不存在/非本项目 → 抛 ValueError
- 事件为空数组 → 仍生成"空演化"报告（不报错）
- LLM 调用失败 → 抛异常由调用方处理，但落盘仍保证一致性
"""

import os
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger

logger = get_logger('mirofish.world_report')

# 世界模拟数据根目录（与 WorldSimulationService 保持一致）
WORLD_SIM_ROOT = os.path.join(os.path.dirname(__file__), '../../data/world-sim')

# 报告各节标题（与前端/返回结构约定一致）
DEFAULT_SECTION_TITLES = [
    "世界编年史",
    "角色动向",
    "世界状态与规则遵守",
    "推演与建议",
]

# 报告生成提示词
REPORT_PROMPT = """你是一名资深的小说世界推演与编年史分析师。根据给定的一场世界模拟
（事件流 + 世界配置），用中文写一份结构化的世界报告。

输出 JSON（必须严格符合以下结构，不要输出其他内容）：
{{
  "text": "<完整 Markdown 报告>",
  "sections": [
    {{"title": "世界编年史", "content": "<Markdown 内容>"}},
    {{"title": "角色动向", "content": "<Markdown 内容>"}},
    {{"title": "世界状态与规则遵守", "content": "<Markdown 内容>"}},
    {{"title": "推演与建议", "content": "<Markdown 内容>"}}
  ]
}}

要求（text 与 sections 须保持一致，text 为四节按顺序拼接的完整报告）：
1. 世界编年史：按时间先后梳理事件，写明"谁 在 何时 何地 做了什么、结果如何"。
2. 角色动向：逐个角色，说明其目标、行动轨迹、与他人的互动关系。
3. 世界状态与规则遵守：总结世界当前状态；逐条说明规则被遵守/违反情况，
   重点列出 approved=false 的事件（被规则阻止）。
4. 推演与建议：给出下一步可能的发展方向，并列出 2-4 个可选的 what-if 假设方向。
5. 事件为空时如实说明"本次模拟未产生有效事件"，其余部分基于世界配置合理推导。
6. 用「## 」作为每个 section 的二级标题，内容精炼、读起来像一份编年史档案。

世界配置：
{world_config}

完整事件流：
{events}"""


class WorldReportService:
    """世界报告生成服务"""

    # ---------------- 路径 ----------------

    @classmethod
    def _sim_dir(cls, project_id: str, simulation_id: str) -> str:
        """模拟目录：<WORLD_SIM_ROOT>/<project_id>/<simulation_id>"""
        return os.path.join(WORLD_SIM_ROOT, project_id, simulation_id)

    @classmethod
    def _events_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'events.json')

    @classmethod
    def _config_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'world_config.json')

    @classmethod
    def _report_md_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'report.md')

    @classmethod
    def _report_json_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(cls._sim_dir(project_id, simulation_id), 'report.json')

    # ---------------- 数据读取 ----------------

    @classmethod
    def _load_events(cls, project_id: str, simulation_id: str) -> List[Dict[str, Any]]:
        """读取事件流；文件缺失返回空列表。"""
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
        """读取世界配置；缺失返回空字典。"""
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

    # ---------------- 节切分（LLM 兜底） ----------------

    @staticmethod
    def _split_markdown_sections(markdown: str) -> List[Dict[str, str]]:
        """按 Markdown 二级标题把全文切分为节，供 LLM 未提供 sections 时兜底。"""
        if not markdown or not markdown.strip():
            return []
        sections: List[Dict[str, str]] = []
        current_title = ""
        current_parts: List[str] = []
        for line in markdown.splitlines():
            if re.match(r'^##\s+', line):
                if current_title:
                    sections.append({
                        "title": current_title.strip(),
                        "content": "\n".join(current_parts).strip(),
                    })
                current_title = line[2:].strip()
                current_parts = []
            else:
                current_parts.append(line)
        if current_title:
            sections.append({
                "title": current_title.strip(),
                "content": "\n".join(current_parts).strip(),
            })
        return sections

    # ---------------- 报告生成 ----------------

    @classmethod
    def generate_report(
        cls,
        project_id: str,
        simulation_id: str,
        llm: Any = None,
    ) -> Dict[str, Any]:
        """为一条世界模拟生成报告并落盘。

        Args:
            project_id: 项目 ID
            simulation_id: 世界模拟 ID
            llm: 可选的 LLMClient；None 时通过 WorldSimulationService._build_llm_client 构建

        Returns:
            {"text": str, "sections": [{"title", "content"}]}
        """
        from ..services.world_simulation import WorldSimulationService

        # 1. 校验模拟存在且属于本项目
        state = WorldSimulationService.get_state(simulation_id)
        if state is None or state.project_id != project_id:
            raise ValueError("模拟不存在")

        # 2. 读取事件流与世界配置（均允许缺失/为空）
        events = cls._load_events(project_id, simulation_id)
        world_config = cls._load_world_config(project_id, simulation_id)

        # 3. 构建 LLM 并调用
        client = llm or WorldSimulationService._build_llm_client(project_id)
        events_text = json.dumps(events, ensure_ascii=False, indent=2)
        world_text = json.dumps(world_config, ensure_ascii=False, indent=2)
        prompt = REPORT_PROMPT.format(
            world_config=world_text or "（无世界配置）",
            events=events_text or "（无事件）",
        )
        result = client.chat_json(
            messages=[
                {"role": "system", "content": "你是世界报告分析师，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=8192,
        )

        text = str(result.get("text", "")).strip()
        sections = result.get("sections")
        # 校验 sections 结构；缺失或用错时从 text 兜底切分
        if not isinstance(sections, list) or not sections:
            sections = cls._split_markdown_sections(text)
        cleaned_sections: List[Dict[str, str]] = []
        for s in sections:
            if isinstance(s, dict) and s.get("title") and s.get("content") is not None:
                cleaned_sections.append({
                    "title": str(s.get("title", "")).strip(),
                    "content": str(s.get("content", "")).strip(),
                })
        # 保证四节标题齐全（缺失补默认标题占位，内容为空不影响文本）
        filled = cls._fill_section_titles(cleaned_sections)
        if not text:
            text = cls._sections_to_markdown(filled)

        report = {"text": text, "sections": filled}

        # 4. 落盘 report.md 与 report.json
        sim_dir = cls._sim_dir(project_id, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        with open(cls._report_md_path(project_id, simulation_id), 'w', encoding='utf-8') as f:
            f.write(text)
        with open(cls._report_json_path(project_id, simulation_id), 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"世界报告已生成: project={project_id}, sim={simulation_id}, sections={len(filled)}")
        return report

    @classmethod
    def _fill_section_titles(
        cls, sections: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """把缺失的四个默认节按顺序补成【标题-空内容】占位，避免结构不完整。"""
        result = list(sections)
        for title in DEFAULT_SECTION_TITLES:
            if not any(s.get("title", "").strip() == title for s in result):
                result.append({"title": title, "content": ""})
        return result
    @classmethod
    def _sections_to_markdown(cls, sections: List[Dict[str, str]]) -> str:
        """把 sections 拼回 Markdown 全文（text 兜底）。"""
        parts = []
        for s in sections:
            title = s.get("title", "").strip()
            content = s.get("content", "").strip()
            parts.append(f"## {title}\n\n{content}".strip())
        return "\n\n".join(p for p in parts if p)

    # ---------------- 读取报告 ----------------

    @classmethod
    def load_report(
        cls, project_id: str, simulation_id: str
    ) -> Optional[Dict[str, Any]]:
        """读取已生成报告；report.json 优先，否则从 report.md 兜底切分。"""
        json_path = cls._report_json_path(project_id, simulation_id)
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"读取报告 json 失败: {json_path}, err={e}")

        md_path = cls._report_md_path(project_id, simulation_id)
        if os.path.exists(md_path):
            try:
                with open(md_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                return {"text": text, "sections": cls._split_markdown_sections(text)}
            except Exception as e:
                logger.warning(f"读取报告 md 失败: {md_path}, err={e}")
        return None

    @classmethod
    def report_exists(cls, project_id: str, simulation_id: str) -> bool:
        """报告是否已生成。"""
        return (
            os.path.exists(cls._report_json_path(project_id, simulation_id))
            or os.path.exists(cls._report_md_path(project_id, simulation_id))
        )
