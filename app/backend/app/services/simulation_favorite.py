"""
模拟流向收藏服务（收藏 / 最佳流向 / 备注）。

为首页「推演记录」的每一条模拟（媒体 sim_xxx、世界 worldsim_xxx、
纯世界项目占位 world_<project_id>、孤儿模拟）提供统一的收藏元数据：
- favorite   ：⭐ 收藏标记（布尔）
- is_best_flow：👑 最佳流向标记（布尔，同项目内唯一互斥）
- remark     ：备注文本（自由字符串）

数据持久化在一个独立的 JSON 存储 data/sim-favorites/favorites.json，
key 为 simulation_id 字符串。选独立存储而非写入各模拟 state.json，是因为
历史列表来源多样（媒体 state / 世界 state / 世界项目占位 / 孤儿），且要
「兼容旧数据」——旧 state.json 没有收藏字段也能正常读写。收藏作为旁路元数据，
以本存储为准；不侵入原有模拟状态模型，风险最低、最易测试。
"""

import json
import os
import threading
from typing import Dict, Any, List, Optional

from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json

logger = get_logger('mirofish.simulation_favorite')

# 收藏数据根（测试可覆写为临时目录）
FAVORITES_ROOT_ENV = "MIROFISH_SIM_FAVORITES_ROOT"
_FAVORITES_ROOT = os.path.join(
    os.path.dirname(__file__), '../../data/sim-favorites'
)


def favorites_root() -> str:
    return os.environ.get(FAVORITES_ROOT_ENV, _FAVORITES_ROOT)


class SimulationFavoriteService:
    """模拟流向收藏的读写服务（单例，线程安全）。"""

    _instance: Optional['SimulationFavoriteService'] = None
    _lock = threading.RLock()

    def __new__(cls) -> 'SimulationFavoriteService':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._data: Dict[str, Dict[str, Any]] = {}
                    cls._data_lock = threading.RLock()  # 可重入，避免 get→_load 死锁
                    cls._loaded = False
        return cls._instance

    # ---------------- 存储路径 ----------------

    def _store_path(self) -> str:
        return os.path.join(favorites_root(), 'favorites.json')

    @classmethod
    def reset(cls) -> None:
        """清空单例内存缓存（测试隔离用：重设数据根后强制从新路径重新加载）。"""
        with cls._lock:
            cls._instance = None

    def _load(self) -> Dict[str, Dict[str, Any]]:
        """懒加载存储；文件缺失/损坏时降级为空 dict（不阻塞收藏功能）。"""
        if self._loaded:
            return self._data
        with self._data_lock:
            if self._loaded:
                return self._data
            path = self._store_path()
            data: Dict[str, Dict[str, Any]] = {}
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        raw = json.load(f)
                    if isinstance(raw, dict):
                        # 仅保留结构合法的条目，容忍脏数据
                        for key, val in raw.items():
                            if isinstance(key, str) and isinstance(val, dict):
                                data[key] = val
                except Exception as e:
                    logger.warning(f"读取收藏存储失败（忽略并重建）: {path}, {e}")
            self._data = data
            self._loaded = True
        return self._data

    def _persist(self) -> None:
        os.makedirs(favorites_root(), exist_ok=True)
        try:
            atomic_write_json(self._store_path(), self._data)
        except Exception as e:
            logger.warning(f"持久化收藏存储失败（忽略）: {e}")

    # ---------------- 查询 ----------------

    @staticmethod
    def _norm(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        entry = entry or {}
        return {
            "favorite": bool(entry.get("favorite", False)),
            "is_best_flow": bool(entry.get("is_best_flow", False)),
            "remark": str(entry.get("remark") or ""),
            "project_id": str(entry.get("project_id") or ""),
        }

    def get(self, simulation_id: str) -> Dict[str, Any]:
        """读取单条收藏元数据（规范化，无记录时返回默认值）。"""
        sim_id = str(simulation_id or "")
        with self._data_lock:
            data = self._load()
            return self._norm(data.get(sim_id))

    def get_many(self, simulation_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量读取多条收藏元数据（供历史列表一次性合并）。"""
        ids = [str(s) for s in simulation_ids]
        with self._data_lock:
            data = self._load()
            return {sid: self._norm(data.get(sid)) for sid in ids}

    def _entry(self, simulation_id: str) -> Dict[str, Any]:
        sim_id = str(simulation_id or "")
        data = self._load()
        if sim_id not in data:
            data[sim_id] = {}
        return data[sim_id]

    def set_favorite(self, simulation_id: str, value: bool) -> Dict[str, Any]:
        """设置收藏标记。"""
        with self._data_lock:
            entry = self._entry(simulation_id)
            entry["favorite"] = bool(value)
        self._persist()
        return self.get(simulation_id)

    def set_best_flow(
        self,
        simulation_id: str,
        value: bool,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """
        设置最佳流向标记。同项目唯一互斥：把 A 设为最佳时，
        同项目内其它模拟的最佳流向会被清除。
        """
        sim_id = str(simulation_id or "")
        # 先用解析出的项目归属，其次用请求传入，最后沿用存储内已记录的项目
        pid = project_id or self._resolve_project_id(sim_id) or \
            self._norm(self._load().get(sim_id)).get("project_id") or ""
        with self._data_lock:
            if not value:
                entry = self._entry(sim_id)
                entry["is_best_flow"] = False
                if pid:
                    entry["project_id"] = pid
            else:
                # 若已知项目归属，互斥清除同项目其它条目的最佳标记
                if pid:
                    for other_sid, other in self._load().items():
                        if other_sid == sim_id:
                            continue
                        other_pid = self._norm(other).get("project_id") or ""
                        if other_pid and other_pid == pid:
                            other["is_best_flow"] = False
                entry = self._entry(sim_id)
                entry["is_best_flow"] = True
                if pid:
                    entry["project_id"] = pid
        self._persist()
        return self.get(sim_id)

    def set_remark(self, simulation_id: str, remark: str) -> Dict[str, Any]:
        """设置备注文本（空串即清除）。"""
        with self._data_lock:
            entry = self._entry(simulation_id)
            entry["remark"] = str(remark or "")
        self._persist()
        return self.get(simulation_id)

    def update(
        self,
        simulation_id: str,
        favorite: Optional[bool] = None,
        best_flow: Optional[bool] = None,
        remark: Optional[str] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """合并更新收藏元数据（任一字段为 None 表示不改动）。"""
        sim_id = str(simulation_id or "")
        pid = project_id or self._resolve_project_id(sim_id)
        if pid:
            # 记录项目归属，供互斥与过滤使用
            with self._data_lock:
                self._entry(sim_id)["project_id"] = pid
        if best_flow is not None:
            return self.set_best_flow(sim_id, best_flow, project_id=pid)
        with self._data_lock:
            entry = self._entry(sim_id)
            if favorite is not None:
                entry["favorite"] = bool(favorite)
            if remark is not None:
                entry["remark"] = str(remark or "")
        self._persist()
        return self.get(sim_id)

    def list_favorited(self) -> List[str]:
        """返回所有收藏（favorite=True）的 simulation_id 列表。"""
        with self._data_lock:
            data = self._load()
            return [
                sid for sid, entry in data.items()
                if self._norm(entry).get("favorite")
            ]

    # ---------------- 项目归属解析 ----------------

    @staticmethod
    def _resolve_project_id(simulation_id: str) -> str:
        """解析一条模拟记录所属项目 id（尽力而为，解析不到返回空串）。

        优先级：
        1. world_<project_id> 占位 → project_id 本身就是 <project_id>
        2. 世界模拟 worldsim_*    → 全盘定位 state.json 的 project_id
        3. 媒体模拟 sim_*        → SimulationManager 状态里的 project_id
        """
        sim_id = str(simulation_id or "")
        if sim_id.startswith("world_"):
            return sim_id[len("world_"):]
        try:
            if sim_id.startswith("worldsim_"):
                from .world_simulation import WorldSimulationService
                found = WorldSimulationService._find_simulation_json(sim_id)
                if found:
                    return found.get("project_id") or ""
        except Exception:
            pass
        try:
            if sim_id.startswith("sim_"):
                from .simulation_manager import SimulationManager
                state = SimulationManager().get_simulation(sim_id)
                if state is not None:
                    return getattr(state, "project_id", "") or ""
        except Exception:
            pass
        return ""

    @classmethod
    def resolve_project_id(cls, simulation_id: str) -> str:
        return cls._resolve_project_id(simulation_id)

    # ---------------- 删除时联动清理 ----------------

    def remove(self, simulation_id: str) -> None:
        """删除某条模拟的收藏记录（用于模拟删除时清理脏数据）。"""
        sim_id = str(simulation_id or "")
        with self._data_lock:
            data = self._load()
            if sim_id in data:
                del data[sim_id]
        self._persist()

    def clear_project_best(self, project_id: str) -> None:
        """清除某项目的全部最佳流向标记。"""
        if not project_id:
            return
        with self._data_lock:
            data = self._load()
            for entry in data.values():
                if str(entry.get("project_id") or "") == project_id:
                    entry["is_best_flow"] = False
        self._persist()
