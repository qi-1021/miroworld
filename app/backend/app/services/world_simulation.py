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
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.atomic_json import atomic_write_json
from .world_bible import WorldBibleService

logger = get_logger('mirofish.world_sim')

# 世界模拟数据目录
WORLD_SIM_ROOT = os.path.join(os.path.dirname(__file__), '../../data/world-sim')

# IPC 命令类型（与 run_world_simulation.py 保持一致）
IPC_CMD_PAUSE = "pause"
IPC_CMD_RESUME = "resume"
IPC_CMD_STOP = "stop"
IPC_CMD_INTERVIEW = "interview"

# IPC 目录名（纯文件系统）
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"

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
7. 世界推演应围绕"任务目标"展开：角色的 goal 与世界的规则设计
   都要服务于达成或阻碍该目标；无明确目标时按设定自然推演

任务目标：
{goal}

世界背景设定：
{background}

小说正文：
{story}"""


@dataclass
class WorldSimulationState:
    """世界模拟状态"""
    simulation_id: str
    project_id: str
    status: str = "created"   # created | preparing | running | paused | completed | failed | stopped
    paused: bool = False      # 是否处于暂停状态
    config_path: str = ""
    events_path: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, Any] = field(default_factory=dict)
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
        atomic_write_json(cls._state_path(state.project_id, state.simulation_id), state.to_dict())
        with cls._lock:
            cls._states[state.simulation_id] = state

    @classmethod
    def _load_state_file(cls, path: str) -> Optional[WorldSimulationState]:
        """读取 state.json；损坏/缺字段时降级返回 None（不让单个坏文件拖垮列表/查询）。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return WorldSimulationState(**json.load(f))
        except Exception as e:
            logger.warning(f"读取世界模拟状态失败（跳过）: {path}, {e}")
            return None

    @classmethod
    def _attach_progress(cls, state: "WorldSimulationState"):
        """把子进程写入的 progress.json 合并进 state.progress（不落 state.json，避免频繁写盘）。"""
        try:
            progress_path = os.path.join(
                WORLD_SIM_ROOT, state.project_id, state.simulation_id, "progress.json"
            )
            if os.path.exists(progress_path):
                with open(progress_path, "r", encoding="utf-8") as f:
                    state.progress = json.load(f)
        except Exception:
            pass

    @classmethod
    def get_state(cls, simulation_id: str) -> Optional[WorldSimulationState]:
        with cls._lock:
            state = cls._states.get(simulation_id)
        if state:
            cls._attach_progress(state)
            return state
        # 从磁盘查找（遍历项目目录）
        if os.path.isdir(WORLD_SIM_ROOT):
            for proj_name in os.listdir(WORLD_SIM_ROOT):
                path = cls._state_path(proj_name, simulation_id)
                if os.path.exists(path):
                    state = cls._load_state_file(path)
                    if state is not None:
                        cls._attach_progress(state)
                        with cls._lock:
                            cls._states[simulation_id] = state
                    return state
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
                state = cls._load_state_file(state_path)
                if state and state.project_id == project_id:
                    cls._attach_progress(state)
                    results.append(state.to_dict())
                    if len(results) >= limit:
                        break
        return results

    # ---------------- IPC 控制 ----------------

    @classmethod
    def _sim_dir(cls, project_id: str, simulation_id: str) -> str:
        """模拟数据目录（state.json 所在目录）"""
        return os.path.dirname(cls._state_path(project_id, simulation_id))

    # ---------------- 删除与孤儿清理 ----------------

    @classmethod
    def delete_simulation(cls, project_id: str, simulation_id: str) -> bool:
        """删除单条世界模拟（其目录 data/world-sim/<project>/<sim>）并清内存缓存。

        不等同于删除整个项目：仅移除这一条模拟的数据。
        返回是否实际删除了某条模拟目录。
        """
        sim_dir = cls._sim_dir(project_id, simulation_id)
        removed = False
        if os.path.isdir(sim_dir) or os.path.islink(sim_dir):
            shutil.rmtree(sim_dir, ignore_errors=True)
            removed = True
        elif os.path.isfile(sim_dir):
            os.remove(sim_dir)
            removed = True
        with cls._lock:
            cls._states.pop(simulation_id, None)
        # 删除后顺带清理空的项目目录，避免 data/world-sim 残留空壳
        project_dir = os.path.join(WORLD_SIM_ROOT, project_id)
        if os.path.isdir(project_dir) and not os.listdir(project_dir):
            try:
                os.rmdir(project_dir)
            except OSError:
                pass
        return removed

    @classmethod
    def _find_simulation_json(
        cls, simulation_id: str
    ) -> Optional[Dict[str, str]]:
        """按 simulation_id 在 data/world-sim 全盘定位归属（忽略无效/损坏状态文件）。

        返回 {"project_id": ..., "simulation_id": ..., "sim_dir": ..., "state": {...}} 或 None。
        优先用 state.json 的 project_id，其次以目录名作为归属。
        """
        if not os.path.isdir(WORLD_SIM_ROOT):
            return None
        for proj_name in sorted(os.listdir(WORLD_SIM_ROOT)):
            proj_dir = os.path.join(WORLD_SIM_ROOT, proj_name)
            if not os.path.isdir(proj_dir) or proj_name == IPC_COMMANDS_DIR:
                continue
            sim_dir = os.path.join(proj_dir, simulation_id)
            if not os.path.isdir(sim_dir):
                continue
            state = cls._load_state_file(os.path.join(sim_dir, "state.json"))
            owner = state.project_id if (state and state.project_id) else proj_name
            return {
                "project_id": owner,
                "simulation_id": simulation_id,
                "sim_dir": sim_dir,
                "state": state.to_dict() if state else None,
            }
        return None

    @classmethod
    def _is_orphan_project_dir(cls, project_dir_name: str) -> bool:
        """判断 data/world-sim 下一个顶层目录是否"孤儿"（其归属项目不存在）。

        孤儿判定：顶层目录名不是某个真实 ProjectManager 项目，或该目录下
        没有任何 state.json 指向真实存在项目（冗余目录/残留测试数据）。
        """
        if not project_dir_name or project_dir_name.startswith('.'):
            return False
        try:
            from ..models.project import ProjectManager
            if ProjectManager.get_project(project_dir_name) is not None:
                return False
        except Exception:
            return False
        return True

    @classmethod
    def list_orphan_simulations(
        cls, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """列出 data/world-sim 下的"孤儿/空模拟"（可安全删除，不占真实项目）。

        每条：{project_id, simulation_id, sim_dir, status, created_at, has_events}。
        这些通常来自：项目已被删除但模拟目录残留、单元测试写入的真实目录、或无归属的空壳。
        供首页「删除空模拟」入口与孤儿清理使用。
        """
        orphans = []
        if not os.path.isdir(WORLD_SIM_ROOT):
            return orphans
        for proj_name in sorted(os.listdir(WORLD_SIM_ROOT)):
            proj_dir = os.path.join(WORLD_SIM_ROOT, proj_name)
            if not os.path.isdir(proj_dir):
                continue
            if not cls._is_orphan_project_dir(proj_name):
                continue
            for sim_name in sorted(os.listdir(proj_dir), reverse=True):
                sim_dir = os.path.join(proj_dir, sim_name)
                if not os.path.isdir(sim_dir):
                    continue
                state = cls._load_state_file(os.path.join(sim_dir, "state.json"))
                orphans.append({
                    "project_id": proj_name,
                    "simulation_id": sim_name,
                    "sim_dir": sim_dir,
                    "status": state.status if state else "orphan",
                    "created_at": state.created_at if state else "",
                    "has_events": os.path.exists(os.path.join(sim_dir, "events.json")),
                })
                if len(orphans) >= limit:
                    return orphans
        return orphans

    @classmethod
    def cleanup_orphans(cls, dry_run: bool = False) -> Dict[str, Any]:
        """清理 data/world-sim 下全部孤儿模拟（归属项目不存在的残留）。

        返回统计：scan / removed / skipped（dry_run=True 时只统计不删除）。
        """
        removed = 0
        skipped = 0
        for item in cls.list_orphan_simulations(limit=10_000):
            if dry_run:
                skipped += 1
                continue
            sim_dir = item.get("sim_dir")
            if sim_dir and os.path.isdir(sim_dir):
                shutil.rmtree(sim_dir, ignore_errors=True)
                removed += 1
            else:
                skipped += 1
        # 清理空的孤儿项目壳目录
        if not dry_run and os.path.isdir(WORLD_SIM_ROOT):
            for proj_name in os.listdir(WORLD_SIM_ROOT):
                proj_dir = os.path.join(WORLD_SIM_ROOT, proj_name)
                if os.path.isdir(proj_dir) and not os.listdir(proj_dir):
                    try:
                        os.rmdir(proj_dir)
                    except OSError:
                        pass
        return {"scan": removed + skipped, "removed": removed, "skipped": skipped}

    @classmethod
    def _send_world_command(
        cls,
        project_id: str,
        simulation_id: str,
        command_type: str,
        args: Dict[str, Any] = None,
    ) -> str:
        """
        写入一条 IPC 命令文件，返回 command_id。
        命令文件位于 <sim_dir>/ipc_commands/<command_id>.json。
        """
        sim_dir = cls._sim_dir(project_id, simulation_id)
        commands_dir = os.path.join(sim_dir, IPC_COMMANDS_DIR)
        responses_dir = os.path.join(sim_dir, IPC_RESPONSES_DIR)
        os.makedirs(commands_dir, exist_ok=True)
        os.makedirs(responses_dir, exist_ok=True)

        # 顺带清理超过 1 小时的残留命令/响应文件（失败/超时可能残留）
        cls._cleanup_stale_ipc_files(sim_dir, max_age_seconds=3600)

        command_id = str(uuid.uuid4())
        command = {
            "command_id": command_id,
            "command_type": command_type,
            "args": args or {},
            "timestamp": datetime.now().isoformat(timespec='seconds'),
        }
        atomic_write_json(os.path.join(commands_dir, f"{command_id}.json"), command)
        logger.info(f"发送世界模拟 IPC 命令: {command_type}, {simulation_id}, command_id={command_id}")
        return command_id

    @classmethod
    def _cleanup_stale_ipc_files(cls, sim_dir: str, max_age_seconds: float = 3600) -> int:
        """清理 IPC 命令/响应目录中超过 max_age_seconds 的残留 JSON 文件。"""
        removed = 0
        for sub in (IPC_COMMANDS_DIR, IPC_RESPONSES_DIR):
            d = os.path.join(sim_dir, sub)
            if not os.path.isdir(d):
                continue
            now = time.time()
            for fn in os.listdir(d):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(d, fn)
                try:
                    if now - os.path.getmtime(path) > max_age_seconds:
                        os.remove(path)
                        removed += 1
                except Exception as e:
                    logger.debug(f"清理 IPC 文件失败（跳过）: {path}, {e}")
        if removed:
            logger.info(f"已清理 {removed} 个过期世界模拟 IPC 文件: {sim_dir}")
        return removed

    @classmethod
    def _read_world_response(
        cls,
        project_id: str,
        simulation_id: str,
        command_id: str,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """
        轮询读取一条 IPC 响应，超时抛出 TimeoutError。
        响应文件位于 <sim_dir>/ipc_responses/<command_id>.json。
        """
        responses_dir = os.path.join(cls._sim_dir(project_id, simulation_id), IPC_RESPONSES_DIR)
        response_file = os.path.join(responses_dir, f"{command_id}.json")
        commands_dir = os.path.join(cls._sim_dir(project_id, simulation_id), IPC_COMMANDS_DIR)
        start = time.time()
        while time.time() - start < timeout:
            if os.path.exists(response_file):
                try:
                    with open(response_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 读取成功后清理命令/响应文件，避免目录长期堆积
                    try:
                        os.remove(response_file)
                    except OSError:
                        pass
                    command_file = os.path.join(commands_dir, f"{command_id}.json")
                    try:
                        os.remove(command_file)
                    except OSError:
                        pass
                    return data
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"解析世界模拟 IPC 响应失败: {e}")
            time.sleep(poll_interval)
        raise TimeoutError(f"等待世界模拟 IPC 命令响应超时 ({timeout} 秒): {command_id}")

    @classmethod
    def control_simulation(
        cls,
        project_id: str,
        simulation_id: str,
        action: str,
        character_name: str = None,
        prompt: str = None,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """
        世界模拟控制：执行 pause / resume / stop / interview。

        Args:
            project_id: 项目 ID
            simulation_id: 模拟 ID
            action: pause | resume | stop | interview
            character_name: interview 时指定角色名（或 id）
            prompt: interview 时的采访问题
            timeout: interview 响应等待超时（秒）
            poll_interval: 响应轮询间隔（秒）

        Returns:
            Dict，含 command_id / action，interview 额外含响应的 result
        """
        if action not in (IPC_CMD_PAUSE, IPC_CMD_RESUME, IPC_CMD_STOP, IPC_CMD_INTERVIEW):
            raise ValueError(f"不支持的控制动作: {action}")

        state = cls.get_state(simulation_id)
        if state is None or state.project_id != project_id:
            raise ValueError("模拟不存在")

        # interview 需要角色名与采访问题
        if action == IPC_CMD_INTERVIEW:
            if not prompt:
                raise ValueError("采访模式必须提供 prompt（采访问题）")
            if not character_name:
                raise ValueError("采访模式必须提供 character_name（角色名/id）")

        args = {}
        if action == IPC_CMD_INTERVIEW:
            args = {"character_name": character_name, "prompt": prompt}

        command_id = cls._send_world_command(project_id, simulation_id, action, args)

        if action == IPC_CMD_PAUSE:
            state.status = "paused"
            state.paused = True
            state.updated_at = datetime.now().isoformat(timespec='seconds')
            cls._save_state(state)
            return {"command_id": command_id, "action": action}

        if action == IPC_CMD_RESUME:
            state.status = "running"
            state.paused = False
            state.updated_at = datetime.now().isoformat(timespec='seconds')
            cls._save_state(state)
            return {"command_id": command_id, "action": action}

        if action == IPC_CMD_STOP:
            state.status = "stopped"
            state.paused = False
            state.updated_at = datetime.now().isoformat(timespec='seconds')
            cls._save_state(state)
            return {"command_id": command_id, "action": action}

        # interview：等待子进程响应
        response = cls._read_world_response(
            project_id, simulation_id, command_id,
            timeout=timeout, poll_interval=poll_interval,
        )
        return {
            "command_id": command_id,
            "action": action,
            "status": response.get("status"),
            "result": response.get("result"),
            "error": response.get("error"),
        }

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
        goal: Optional[str] = None,
        timeline_context: str = "",
    ) -> Dict[str, Any]:
        """LLM 生成世界模拟配置（goal 为可选任务目标，timeline_context 为时间线参考）。

        带磁盘缓存：键 = sha256(背景+正文 + goal + timeline_context + model_id)，
        避免相同设定重复调用 LLM。缓存读写异常静默降级。
        """
        # 控制输入规模：背景/正文各截取前 6000 字
        bg = background[:6000] if background else ""
        st = story[:6000] if story else ""

        cache_key = None
        try:
            from .cache_utils import compute_cache_key, read_cache, write_cache
            cache_key = compute_cache_key([background, story, goal or "", timeline_context, llm.model])
        except Exception:
            cache_key = None

        override = os.environ.get('MIROFISH_WORLD_SIM_CACHE_DIR')
        if override:
            world_config_cache_dir = override
        else:
            # app/backend/data/world-sim-cache（已 gitignore）
            world_config_cache_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                'data', 'world-sim-cache',
            )

        result = None
        if cache_key:
            result = read_cache(world_config_cache_dir, cache_key)
            if result is not None:
                logger.info(
                    f"世界配置缓存命中（key={cache_key[:12]}…），跳过 LLM 调用"
                )
                # 缓存不含 llm 元信息，重新附加当前 llm 客户端信息
                result.setdefault("llm", cls._llm_meta(llm))
                return result

        prompt = WORLD_CONFIG_PROMPT.format(
            background=bg or "（无背景设定）",
            story=st or "（无正文）",
            goal=goal or "（无明确目标，请根据设定自然推演）",
        )
        if timeline_context:
            prompt += f"\n\n当前时间线上下文（供推演参考，角色目标与规则应与之衔接）：\n{timeline_context}\n"
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

        # 补充默认值（不含 llm 元信息，交由 _llm_meta 在返回时统一附加，
        # 这样缓存文件不绑定特定 api_key/base_url）
        result.setdefault("connections", [])
        result.setdefault("rules", [])

        if cache_key:
            write_cache(world_config_cache_dir, cache_key, result)

        result["llm"] = cls._llm_meta(llm)
        return result

    @classmethod
    def _llm_meta(cls, llm: LLMClient) -> Dict[str, str]:
        return {
            "model": getattr(llm, "model", ""),
            "base_url": getattr(llm, "base_url", ""),
            "api_key": getattr(llm, "api_key", ""),
        }

    # ---------------- 主流程 ----------------

    @classmethod
    def start_simulation(
        cls,
        project_id: str,
        total_steps: int = 6,
        time_step_minutes: int = 30,
        goal: Optional[str] = None,
        time_mode: str = "minutes",
        time_jumps: Optional[List[str]] = None,
        include_timeline: bool = False,
        from_event_id: Optional[str] = None,
        story_summary_mode: str = "rule",
    ) -> WorldSimulationState:
        """
        启动世界模拟：
        1. 读取设定库
        2. LLM 生成世界配置（可指定任务目标 goal）
        3. 写入配置目录
        4. 后台线程调用 .venv-simulation 子进程
        """
        bible = WorldBibleService.get_bible(project_id)
        if bible is None or (not bible.background_text.strip() and not bible.story_text.strip()):
            raise ValueError("尚未提交世界输入，请先在「世界设定」中保存背景/正文")

        if time_mode not in ("minutes", "narrative"):
            raise ValueError("time_mode 必须是 minutes 或 narrative")
        if time_mode == "narrative" and not time_jumps:
            raise ValueError("narrative 模式需要提供 time_jumps 时间标签列表")
        if from_event_id:
            from .timeline_service import load_timeline
            events = load_timeline(project_id, None).get("events", [])
            if not any(e.get("id") == from_event_id for e in events):
                raise ValueError(f"起点事件不存在: {from_event_id}")

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
                timeline_context = ""
                if from_event_id or include_timeline:
                    try:
                        from .timeline_service import load_timeline
                        events = load_timeline(project_id, None).get("events", [])
                        lines = []
                        if from_event_id:
                            idx = next((i for i, e in enumerate(events) if e.get("id") == from_event_id), None)
                            if idx is not None:
                                start = events[idx]
                                lines.append(
                                    f"- [起点] {start.get('time_text') or ''} {start.get('summary') or ''}".strip()
                                )
                                for e in events[idx + 1: idx + 40]:
                                    lines.append(f"- {e.get('time_text') or ''} {e.get('summary') or ''}".strip())
                            timeline_context = "\n".join(lines) if lines else "（时间线为空）"
                        else:
                            for e in events[:40]:
                                lines.append(f"- {e.get('time_text') or ''} {e.get('summary') or ''}".strip())
                            timeline_context = "\n".join(lines) if lines else "（时间线为空）"
                    except Exception as e:
                        logger.warning(f"读取时间线上下文失败（忽略）: {e}")
                config = cls._generate_world_config(
                    project_id, bible.background_text, bible.story_text, llm,
                    goal=goal, timeline_context=timeline_context,
                )
                config["world"]["total_steps"] = int(total_steps)
                config["world"]["story_summary_mode"] = story_summary_mode if story_summary_mode in ("rule", "llm") else "rule"
                config["world"]["time_step_minutes"] = int(time_step_minutes)
                config["world"]["time_mode"] = time_mode
                config["world"]["time_jumps"] = list(time_jumps or [])

                config_path = os.path.join(sim_dir, 'world_config.json')
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

                state.config_path = config_path
                state.status = "running"
                state.updated_at = datetime.now().isoformat(timespec='seconds')
                cls._save_state(state)

                # 2. 调用子进程（.venv-simulation）
                events_path = os.path.join(sim_dir, 'events.json')
                output = cls._run_simulation_subprocess(
                    config_path=config_path,
                    events_path=events_path,
                    ipc_dir=sim_dir,
                )

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

                    # 3. 事件回写图谱（若项目已有知识图谱）
                    graph_write = cls._write_events_to_graph(project_id, events)
                    state.result["graph_write"] = graph_write
                    if graph_write.get("status") == "ok":
                        logger.info(
                            f"世界事件已回写图谱: {graph_write.get('graph_id')}, "
                            f"episode={graph_write.get('episode_uuid')}"
                        )
                    elif graph_write.get("status") == "skipped":
                        logger.info("跳过图谱回写（项目尚未构建图谱）")
                    else:
                        logger.warning(f"图谱回写失败: {graph_write.get('error')}")
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

    # ---------------- 续推 ----------------

    @classmethod
    def continue_simulation(
        cls,
        base_simulation_id: str,
        additional_steps: int = 3,
        goal: Optional[str] = None,
    ) -> WorldSimulationState:
        """从一条已有世界线的末尾继续推演（保留历史事件作为记忆，步号接续）。"""
        base = cls.get_state(base_simulation_id)
        if base is None:
            raise ValueError("基础模拟不存在")
        project_id = base.project_id

        events_path = base.events_path or os.path.join(
            WORLD_SIM_ROOT, project_id, base.simulation_id, "events.json"
        )
        if not os.path.exists(events_path):
            raise ValueError("基础模拟没有事件文件，无法续推")
        with open(events_path, "r", encoding="utf-8") as f:
            base_events = json.load(f)
        if not base_events:
            raise ValueError("基础模拟事件为空，无法续推")
        last_step = max(int(e.get("step") or 0) for e in base_events)

        base_config_path = base.config_path or os.path.join(
            WORLD_SIM_ROOT, project_id, base.simulation_id, "world_config.json"
        )
        if not os.path.exists(base_config_path):
            raise ValueError("基础模拟缺少世界配置，无法续推")
        with open(base_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        sim_id = f"{base.simulation_id}_cont"
        counter = 2
        while cls.get_state(sim_id) is not None:
            sim_id = f"{base.simulation_id}_cont_{counter}"
            counter += 1

        sim_dir = os.path.join(WORLD_SIM_ROOT, project_id, sim_id)
        os.makedirs(sim_dir, exist_ok=True)

        new_config = json.loads(json.dumps(config))
        new_config["world"]["total_steps"] = int(additional_steps)
        if goal:
            new_config["world"]["goal"] = str(goal).strip()

        config_path = os.path.join(sim_dir, "world_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)

        resume_events_path = os.path.join(sim_dir, "resume_events.json")
        with open(resume_events_path, "w", encoding="utf-8") as f:
            json.dump(base_events, f, ensure_ascii=False, indent=2)

        out_events_path = os.path.join(sim_dir, "events.json")
        state = WorldSimulationState(
            simulation_id=sim_id,
            project_id=project_id,
            status="preparing",
            config_path=config_path,
            events_path=out_events_path,
            created_at=datetime.now().isoformat(timespec="seconds"),
            updated_at=datetime.now().isoformat(timespec="seconds"),
        )
        state.result = {"meta": {"continue_base": base.simulation_id}}
        with cls._lock:
            cls._states[sim_id] = state
        cls._save_state(state)

        def run():
            try:
                state.status = "running"
                state.updated_at = datetime.now().isoformat(timespec="seconds")
                cls._save_state(state)
                output = cls._run_simulation_subprocess(
                    config_path=config_path,
                    events_path=out_events_path,
                    ipc_dir=sim_dir,
                    extra_args=[
                        "--resume-events", resume_events_path,
                        "--start-step", str(last_step + 1),
                    ],
                )
                if os.path.exists(out_events_path):
                    with open(out_events_path, "r", encoding="utf-8") as f:
                        events = json.load(f)
                    state.result = {
                        "event_count": len(events),
                        "events": events,
                        "log_tail": output[-2000:],
                        "meta": {"continue_base": base.simulation_id},
                    }
                    state.status = "completed"
                else:
                    state.status = "failed"
                    state.error = f"续推未产出事件文件。输出:\n{output[-2000:]}"
            except subprocess.TimeoutExpired:
                state.status = "failed"
                state.error = "世界模拟续推超时（1 小时）"
            except Exception as e:
                logger.error(f"世界模拟续推失败: {e}")
                state.status = "failed"
                state.error = str(e)
            finally:
                state.updated_at = datetime.now().isoformat(timespec="seconds")
                cls._save_state(state)

        threading.Thread(target=run, daemon=True).start()
        return state

    # ---------------- 事件回写图谱 ----------------

    @classmethod
    def _write_events_to_graph(
        cls,
        project_id: str,
        events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        把世界模拟事件流回写到项目的知识图谱（Graphiti + Neo4j）。

        事件流格式化为时序文本，作为一条 episode 追加到图谱：
        [时间] 角色 在 地点：动作 → 结果

        返回：
            {"status": "ok", "graph_id": ..., "episode_uuid": ...}
            {"status": "skipped", "reason": ...}  项目无图谱
            {"status": "error", "error": ...}
        """
        if not events:
            return {"status": "skipped", "reason": "无事件可回写"}

        # 获取项目的 graph_id
        try:
            from ..models.project import ProjectManager
            project = ProjectManager.get_project(project_id)
            graph_id = project.graph_id if project else None
        except Exception as e:
            return {"status": "error", "error": f"读取项目失败: {e}"}

        if not graph_id:
            return {"status": "skipped", "reason": "项目尚未构建图谱"}

        # 格式化为时序文本
        lines = []
        for e in events:
            time_str = e.get("time", "")
            who = e.get("character_name", "")
            where = e.get("location", "")
            action = e.get("action_desc", "")
            result = e.get("result", "")
            approved = e.get("approved", True)
            mark = "" if approved else "（被规则阻止）"
            lines.append(f"[{time_str}] {who} 在 {where}：{action} → {result}{mark}")
        episode_text = "\n".join(lines)

        try:
            from ..services.zep_factory import get_zep_client

            client = get_zep_client()
            # 只在 Graphiti 后端回写（Zep Cloud 也可用 add_episode）
            episode_uuid = client.add_episode(
                graph_id=graph_id,
                data=episode_text,
                episode_type="text",
            )
            if not episode_uuid:
                return {"status": "error", "error": "add_episode 返回空 uuid"}
            return {
                "status": "ok",
                "graph_id": graph_id,
                "episode_uuid": episode_uuid,
                "event_count": len(events),
            }
        except Exception as e:
            logger.error(f"世界事件回写图谱失败: {e}")
            return {"status": "error", "error": str(e)}

    # ---------------- what-if 分支推演 ----------------

    @classmethod
    def simulate_whatif(
        cls,
        base_simulation_id: str,
        question: str,
        steps: int = 3,
    ) -> WorldSimulationState:
        """
        what-if 分支推演：基于一条已完成/进行中的模拟，构造"假设分支世界配置"，跑新增模拟。

        - 读取基础模拟的状态、世界配置与事件流
        - 构造分支配置：world.name 追加假设后缀；rules 追加一条假设前提规则；
          世界名/首角色 goal 注入假设问题；total_steps 设为 steps
        - 新模拟 simulation_id = 基础 id + "_whatif"（冲突时追加序号），
          result.meta 记录 whatif_base 与 whatif_question
        - 通过子进程跑 steps 步（与 start_simulation 同机制，含 --ipc-dir）
        """
        question = (question or "").strip()
        if not question:
            raise ValueError("what-if 假设问题不能为空")
        if not (0 < int(steps) <= 60):
            raise ValueError("steps 需在 1-60 之间")

        base = cls.get_state(base_simulation_id)
        if base is None:
            raise ValueError("基础模拟不存在")
        project_id = base.project_id

        # 读取基础世界配置（config_path 优先，缺失则回退模拟目录内 world_config.json）
        base_config_path = base.config_path or os.path.join(
            WORLD_SIM_ROOT, project_id, base.simulation_id, 'world_config.json'
        )
        if not os.path.exists(base_config_path):
            raise ValueError("基础模拟缺少世界配置，无法推演")
        with open(base_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 构造分支世界配置（深拷贝，避免污染基础配置）
        branch = json.loads(json.dumps(config))
        world = branch.setdefault("world", {})
        world["name"] = f"{world.get('name', '世界')}（推演：{question[:20]}）"
        world["total_steps"] = int(steps)
        # 追加假设前提规则
        rules = branch.setdefault("rules", [])
        if not isinstance(rules, list):
            rules = []
            branch["rules"] = rules
        rules.append({
            "id": f"whatif_assumption_{len(rules) + 1}",
            "description": question,
        })
        # 把假设注入第一个角色的 goal，让推演目标围绕假设展开
        chars = branch.setdefault("characters", [])
        if isinstance(chars, list) and chars:
            chars[0]["goal"] = f"{chars[0].get('goal', '')}；假设：{question}".strip("；")

        # 新模拟 ID：基础 id + "_whatif"（冲突时追加序号）
        sim_id = f"{base.simulation_id}_whatif"
        counter = 2
        while cls.get_state(sim_id) is not None:
            sim_id = f"{base.simulation_id}_whatif_{counter}"
            counter += 1

        sim_dir = os.path.join(WORLD_SIM_ROOT, project_id, sim_id)
        os.makedirs(sim_dir, exist_ok=True)

        branch_config_path = os.path.join(sim_dir, 'world_config.json')
        with open(branch_config_path, 'w', encoding='utf-8') as f:
            json.dump(branch, f, ensure_ascii=False, indent=2)

        state = WorldSimulationState(
            simulation_id=sim_id,
            project_id=project_id,
            status="preparing",
            config_path=branch_config_path,
            created_at=datetime.now().isoformat(timespec='seconds'),
            updated_at=datetime.now().isoformat(timespec='seconds'),
        )
        state.result = {
            "meta": {
                "whatif_base": base.simulation_id,
                "whatif_question": question,
            }
        }
        with cls._lock:
            cls._states[sim_id] = state
        cls._save_state(state)

        def run():
            try:
                state.status = "running"
                state.updated_at = datetime.now().isoformat(timespec='seconds')
                cls._save_state(state)

                events_path = os.path.join(sim_dir, 'events.json')
                output = cls._run_simulation_subprocess(
                    config_path=branch_config_path,
                    events_path=events_path,
                    ipc_dir=sim_dir,
                )
                state.events_path = events_path
                meta = state.result.get("meta", {})
                if os.path.exists(events_path):
                    with open(events_path, 'r', encoding='utf-8') as f:
                        events = json.load(f)
                    state.result = {
                        "meta": meta,
                        "event_count": len(events),
                        "events": events,
                        "log_tail": output[-2000:],
                    }
                    state.status = "completed"
                else:
                    state.status = "failed"
                    state.error = f"推演未产出事件文件。输出:\n{output[-2000:]}"
            except subprocess.TimeoutExpired:
                state.status = "failed"
                state.error = "what-if 推演超时（1 小时）"
            except Exception as e:
                logger.error(f"what-if 推演失败: {e}")
                state.status = "failed"
                state.error = str(e)
            finally:
                state.updated_at = datetime.now().isoformat(timespec='seconds')
                cls._save_state(state)

        threading.Thread(target=run, daemon=True).start()
        return state

    @classmethod
    def batch_whatif(
        cls,
        base_simulation_id: str,
        questions: List[str],
        steps: int = 3,
    ) -> List[Dict[str, Any]]:
        """批量 What-if 分叉：从同一条基础世界线同时发起多个假设推演。"""
        started = []
        for q in questions:
            q = (q or "").strip()
            if not q:
                continue
            state = cls.simulate_whatif(base_simulation_id, q, steps=steps)
            started.append({
                "simulation_id": state.simulation_id,
                "question": q,
                "status": state.status,
            })
        return started

    @staticmethod
    def _run_simulation_subprocess(
        config_path: str,
        events_path: str,
        ipc_dir: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
    ) -> str:
        """调用 .venv-simulation 子进程跑世界模拟，返回进程日志输出。

        便于测试 mock：覆盖此方法即可模拟子进程执行。
        """
        script = os.path.join(
            os.path.dirname(__file__), '../../scripts/run_world_simulation.py'
        )
        sim_python = WorldSimulationService._get_simulation_python()
        cmd = [sim_python, script, "--config", config_path, "--out", events_path]
        if ipc_dir:
            cmd += ["--ipc-dir", ipc_dir]
        if extra_args:
            cmd += extra_args
        logger.info(f"启动世界模拟子进程: {cmd}")
        proc = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(script),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            output, _ = proc.communicate(timeout=3600)
            return output
        except subprocess.TimeoutExpired:
            # communicate 超时不会自动杀进程，必须显式终止，否则孤儿进程一直烧内存
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception as e:
                logger.warning(f"终止超时世界模拟子进程失败: {e}")
            logger.error("世界模拟子进程超时（1 小时），已终止进程 %s", proc.pid)
            raise

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
