"""
模式注册表（Mode Registry）

把"世界/MiroFish 的用途模式"登记为结构化规格，供前端按需选择、
后端在 /input 时把 mode 透传进 metadata。目前三种内置模式：

- novel-world：小说世界推演（现状默认行为）
- character-card：角色卡生成（聚焦人物设定）
- timeline：时间线/编年史（聚焦事件脉络）

模式本身不改变现有请求处理逻辑；POST /api/world/<id>/input 仅把
mode 记录到 metadata['mode']，供上层消费。未来若某模式需要不同
pipeline 或产物，可在 registry 扩展并在对应服务端分支使用。
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List

BUILTIN_MODES = [
    {
        "key": "novel-world",
        "label": "小说世界",
        "inputs": ["background_files", "story_files", "background_text", "story_text"],
        "pipeline": ["世界设定索引", "本体/知识图谱", "世界模拟推演"],
        "artifacts": ["世界观设定库", "知识图谱", "虚拟世界状态与事件流"],
    },
    {
        "key": "character-card",
        "label": "角色卡",
        "inputs": ["background_text", "story_text"],
        "pipeline": ["角色提取", "角色卡聚合"],
        "artifacts": ["角色卡（外貌/性格/目标/关系）"],
    },
    {
        "key": "timeline",
        "label": "时间线",
        "inputs": ["story_text", "background_text"],
        "pipeline": ["事件提取", "时间线生成"],
        "artifacts": ["事件时间线", "分幕/章节脉络"],
    },
]


@dataclass
class ModeSpec:
    """模式规格。"""
    key: str
    label: str
    inputs: List[str] = field(default_factory=list)
    pipeline: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class ModeRegistry:
    """模式注册表：按 key 存取 ModeSpec。"""

    def __init__(self):
        self._modes: Dict[str, ModeSpec] = {}
        for m in BUILTIN_MODES:
            self.register(ModeSpec(**m))

    def register(self, spec: ModeSpec) -> None:
        if not spec or not spec.key:
            raise ValueError("ModeSpec 必须有 key")
        self._modes[spec.key] = spec

    def get(self, key: str) -> ModeSpec:
        return self._modes.get(key)

    def list(self) -> List[ModeSpec]:
        # 保持注册顺序稳定
        return list(self._modes.values())

    def list_dicts(self) -> List[Dict[str, object]]:
        return [m.to_dict() for m in self.list()]


# 模块级单例，供 API 路由直接使用
_registry = ModeRegistry()


def get_mode_registry() -> ModeRegistry:
    return _registry


def get_modes() -> List[Dict[str, object]]:
    """返回所有模式的 dict 列表。"""
    return _registry.list_dicts()


def get_mode(key: str):
    """按 key 取单个 ModeSpec；不存在返回 None。"""
    return _registry.get(key)
