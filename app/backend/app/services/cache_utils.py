"""
轻量磁盘缓存工具（为 LLM 生成结果去重，减少重复调用）。

设计目标：
- 缓存键 = sha256(参与生成的主要输入) 归一化后拼接模型/目标等维度。
- 读写全程 try/except，任何 I/O 异常都静默降级（仅记录 warning），
  绝不让缓存错误阻断主流程。
- 数据目录默认落在已 gitignore 的 app/backend/data/ 下。

供本体生成缓存 / 世界配置缓存复用。
"""

import hashlib
import json
import os
from typing import Any, Optional

from ..utils.logger import get_logger

logger = get_logger('mirofish.cache')

# 默认缓存根目录：app/backend/data/（已在 .gitignore）
_CACHE_ROOT = os.path.join(os.path.dirname(__file__), '../../data')


def cache_root() -> str:
    return _CACHE_ROOT


def compute_cache_key(parts: list[str]) -> str:
    """
    由若干文本片段计算缓存键（sha256 十六进制）。
    parts 会被归一化（strip、保留 None 为空串）后拼接再哈希，
    保证同样输入得到同样 key。
    """
    normalized = "|".join((str(p) if p is not None else "").strip() for p in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_join(root: str, hash_key: str) -> str:
    """限制 hash_key 只含十六进制，避免路径穿越。"""
    if not hash_key or not all(c in "0123456789abcdef" for c in hash_key):
        raise ValueError(f"非法缓存键: {hash_key!r}")
    return os.path.join(root, f"{hash_key}.json")


def read_cache(cache_dir: str, hash_key: str) -> Optional[Any]:
    """
    读取缓存。命中返回解析后的对象；未命中/读失败返回 None（调用方据此决定是否绕过）。
    """
    try:
        path = _safe_join(cache_dir, hash_key)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取缓存失败（按未命中处理）：{e}")
        return None


def write_cache(cache_dir: str, hash_key: str, value: Any) -> bool:
    """
    写缓存。成功返回 True；失败返回 False（静默降级）。
    """
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = _safe_join(cache_dir, hash_key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning(f"写入缓存失败（忽略继续）: {e}")
        return False
