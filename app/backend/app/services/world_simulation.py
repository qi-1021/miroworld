"""
世界模拟服务（独立模式）

把"世界设定库"（背景文档 + 小说正文）转换为世界模拟配置：
1. LLM 从背景/正文中提取角色（人物/组织）、地点、规则
2. 生成 world_config.json（run_world_simulation.py 的输入）
3. 调用 .venv-simulation 子进程运行世界模拟
4. 收集事件流与结果

与社交模拟（Twitter/Reddit）完全独立：不依赖平台动作，不发帖。
"""

import os
import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from .world_bible import WorldBibleService

logger = get_logger('mirofish.world_sim')

# 世界模拟数据目录
WORLD_SIM_ROOT = os.path.join(os.path.dirname(__file__), '../../data/world-sim')

# 世界配置生成提示词
WORLD_CONFIG_PROMPT = """你是一名小说世界模拟专家。请根据给定的"世界背景设定"和"小说正文"，提取出用于世界模拟的配置。

输出 JSON（必须严格符合以下结构）：
{{
  "world": {{
    "name": "世界名称（来自背景）",
    "time_step_minutes": 30,
    "total_steps": 6,
    "initial_time": "2026-01-01 08:00"
  }},
  "locations": [
    {{"id": "loc1", "name": "地点名（来自背景/正文）", "description": "简短描述"}}
  ],
  "connections": [["loc1", "loc2"]],
  "characters": [
    {{
      "id": "char1",
      "name": "角色名",
      "persona": "基于背景/正文的角色设定（性格、身份、目标）",
      "location": "初始所在地点 id",
      "goal": "这个角色在当前时间点的目标",
      "knowledge": ["角色知道的关键信息"]
    }}
  ],
  "rules": [
    {{"id": "rule1", "description": "世界规则（来自背景设定，如魔法代价、禁忌）"}}
  ]
}}

要求：
1. 角色数量 3-8 个，从背景和正文中提取最重要的人物/组织
2. 地点 3-6 个，必须与 characters 的 location 对应
3. 规则 0-3 条，只提取背景中明确的世界规则
4. characters 的 location 必须是 locations 中存在的 id
5. connections 是地点之间的连通关系
6. 只输出 JSON，不要输出其他内容

世界背景设定：
{background}

小说正文：
{story}"""


@dataclass
class WorldSimulationState:
    """世界模拟状态"""
    simulation_id: str
    project_id: str
    status: str = "created"   # created | preparing | running | completed | failed
    config_path: str = ""
    events_path: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorldSimulationService:
    """世界模拟服务"""

    _lock = threading.Lock()
    _states: Dict[str, WorldSimulationState] = {}

    # ---------------- 状态管理 ----------------

    @classmethod
    def _state_path(cls, project_id: str, simulation_id: str) -> str:
        return os.path.join(WORLD_SIM_ROOT, project_id, simulation_id, 'state.json')

    @classmethod
    def _save_state(cls, state: WorldSimulationState):
        os.makedirs(os.path.dirname(cls._state_path(state.project_id, state.simulation_id)), exist_ok=True)
        with open(cls._state_path(state.project_id, state.simulation_id), 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def get_state(cls, simulation_id: str) -> Optional[WorldSimulationState]:
        with cls._lock:
            state = cls._states.get(simulation_id)
        if state:
            return state
        # 从磁盘查找（遍历项目目录）
        if os.path.isdir(WORLD_SIM_ROOT):
            for proj_name in os.listdir(WORLD_SIM_ROOT):
                path = cls._state_path(proj_name, simulation_id)
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        return WorldSimulationState(**json.load(f))
        return None

    @classmethod
    def list_simulations(cls, project_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """列出项目的世界模拟"""
        results = []
        root = os.path.join(WORLD_SIM_ROOT, project_id)
        if not os.path.isdir(root):
            return results
        for name in sorted(os.listdir(root), reverse=True):
            sim_dir = os.path.join(root, name)
            if not os.path.isdir(sim_dir):
                continue
            state_path = os.path.join(sim_dir, 'state.json')
            if os.path.exists(state_path):
                with open(state_path, 'r', encoding='utf-8') as f:
                    state = WorldSimulationState(**json.load(f))
                if state.project_id == project_id:
                    results.append(state.to_dict())
                    if len(results) >= limit:
                        break
        return results

    # ---------------- 配置生成 ----------------

    @classmethod
    def _build_llm_client(cls, project_id: str) -> LLMClient:
        """项目绑定模型优先，其次注册表第一个已验证 chat 模型"""
        try:
            from ..services.model_registry import ModelRegistryService
            from ..services.model_resolver import ModelResolver
            from ..models.model_config import ModelRole

            registry = ModelRegistryService()
            bindings = registry.get_project_bindings(project_id)
            if bindings and bindings.to_dict().get(ModelRole.PRIMARY.value):
                snapshot = registry.create_snapshot(
                    owner_type="project",
                    owner_id=project_id,
                    bindings=bindings,
                    expected_revision=None,
                )
                resolved = ModelResolver(registry).resolve_chat(ModelRole.PRIMARY, snapshot["id"])
                return LLMClient(
                    api_key=resolved.api_key,
                    base_url=resolved.endpoint,
                    model=resolved.model_id,
                )
        except Exception as e:
            logger.warning(f"项目绑定模型解析失败: {e}")

        try:
            from ..services.zep_graphiti_impl import GraphitiClient
            resolved = GraphitiClient._resolve_registry_chat_model()
            if resolved:
                api_key, base_url, model = resolved
                return LLMClient(api_key=api_key, base_url=base_url, model=model)
        except Exception as e:
            logger.warning(f"注册表模型回退失败: {e}")

        return LLMClient()

    @classmethod
    def _generate_world_config(
        cls,
        project_id: str,
        background: str,
        story: str,
        llm: LLMClient,
    ) -> Dict[str, Any]:
        """LLM 生成世界模拟配置"""
        # 控制输入规模：背景/正文各截取前 6000 字
        bg = background[:6000] if background else ""
        st = story[:6000] if story else ""

        prompt = WORLD_CONFIG_PROMPT.format(
            background=bg or "（无背景设定）",
            story=st or "（无正文）",
        )
        result = llm.chat_json(
            messages=[
                {"role": "system", "content": "你是小说世界模拟专家，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=8192,
        )
        if not isinstance(result, dict):
            raise ValueError("世界配置生成失败：LLM 未返回 JSON 对象")

        # 校验基本结构
        if "world" not in result or "characters" not in result or "locations" not in result:
            raise ValueError("世界配置生成失败：缺少必需字段（world/characters/locations）")

        # 补充默认值
        result.setdefault("connections", [])
        result.setdefault("rules", [])
        result["llm"] = {
            "model": llm.model,
            "base_url": llm.base_url,
            "api_key": llm.api_key,
        }
        return result

    # ---------------- 主流程 ----------------

    @classmethod
    def start_simulation(
        cls,
        project_id: str,
        total_steps: int = 6,
        time_step_minutes: int = 30,
    ) -> WorldSimulationState:
        """
        启动世界模拟：
        1. 读取设定库
        2. LLM 生成世界配置
        3. 写入配置目录
        4. 后台线程调用 .venv-simulation 子进程
        """
        bible = WorldBibleService.get_bible(project_id)
        if bible is None or (not bible.background_text.strip() and not bible.story_text.strip()):
            raise ValueError("尚未提交世界输入，请先在「世界设定」中保存背景/正文")

        sim_id = f"worldsim_{datetime.now().strftime('%Y%m%d%H%M%S')}_{project_id[-6:]}"
        sim_dir = os.path.join(WORLD_SIM_ROOT, project_id, sim_id)
        os.makedirs(sim_dir, exist_ok=True)

        state = WorldSimulationState(
            simulation_id=sim_id,
            project_id=project_id,
            status="preparing",
            created_at=datetime.now().isoformat(timespec='seconds'),
            updated_at=datetime.now().isoformat(timespec='seconds'),
        )
        with cls._lock:
            cls._states[sim_id] = state
        cls._save_state(state)

        def run():
            try:
                # 1. LLM 生成配置
                llm = cls._build_llm_client(project_id)
                config = cls._generate_world_config(
                    project_id, bible.background_text, bible.story_text, llm
                )
                config["world"]["total_steps"] = int(total_steps)
                config["world"]["time_step_minutes"] = int(time_step_minutes)

                config_path = os.path.join(sim_dir, 'world_config.json')
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

                state.config_path = config_path
                state.status = "running"
                state.updated_at = datetime.now().isoformat(timespec='seconds')
                cls._save_state(state)

                # 2. 调用子进程（.venv-simulation）
                script = os.path.join(
                    os.path.dirname(__file__), '../../scripts/run_world_simulation.py'
                )
                sim_python = cls._get_simulation_python()

                events_path = os.path.join(sim_dir, 'events.json')
                cmd = [
                    sim_python, script,
                    "--config", config_path,
                    "--out", events_path,
                ]
                logger.info(f"启动世界模拟子进程: {cmd}")

                proc = subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(script),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                output, _ = proc.communicate(timeout=3600)

                state.events_path = events_path
                if os.path.exists(events_path):
                    with open(events_path, 'r', encoding='utf-8') as f:
                        events = json.load(f)
                    state.result = {
                        "event_count": len(events),
                        "events": events,
                        "log_tail": output[-2000:],
                    }
                    state.status = "completed"
                else:
                    state.status = "failed"
                    state.error = f"模拟未产出事件文件。输出:\n{output[-2000:]}"
            except subprocess.TimeoutExpired:
                state.status = "failed"
                state.error = "世界模拟超时（1 小时）"
            except Exception as e:
                logger.error(f"世界模拟失败: {e}")
                state.status = "failed"
                state.error = str(e)
            finally:
                state.updated_at = datetime.now().isoformat(timespec='seconds')
                cls._save_state(state)

        threading.Thread(target=run, daemon=True).start()
        return state

    @staticmethod
    def _get_simulation_python() -> str:
        """获取模拟环境 Python（.venv-simulation 优先）"""
        env_python = os.environ.get('SIMULATION_PYTHON')
        if env_python:
            return env_python
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(backend_dir, '.venv-simulation/bin/python'),
            os.path.join(backend_dir, '.venv-simulation/Scripts/python.exe'),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return 'python'
