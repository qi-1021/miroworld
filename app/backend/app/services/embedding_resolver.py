"""
向量模型提供方解析（本地 / 云端 / 自动）

偏好取值（embedding preference）：
- "cloud"：只用云端（注册表 verified embedding 且无 local_path，如 SiliconFlow）；云端不可用 → None
- "local"：只用本地（app/models/embeddings/ 下已就绪模型）
- "auto"（默认）：云端优先 → 本地回退

优先级：环境变量 EMBEDDING_PREFERENCE > 配置文件 > 默认 auto。
配置存储：app/data/model-config/embedding_preference.json
"""
import os
from pathlib import Path
from typing import Any, Optional

_APP_DATA = Path(__file__).resolve().parents[3] / "data" / "model-config"
_PREF_PATH = _APP_DATA / "embedding_preference.json"
_VALID = ("cloud", "local", "auto")


def get_embedding_preference() -> str:
    """读取向量模型偏好；非法值回退 auto。"""
    env = (os.environ.get("EMBEDDING_PREFERENCE") or "").strip().lower()
    if env in _VALID:
        return env
    try:
        if _PREF_PATH.exists():
            import json
            data = json.loads(_PREF_PATH.read_text(encoding="utf-8"))
            pref = str(data.get("preference") or "").strip().lower()
            if pref in _VALID:
                return pref
    except Exception:
        pass
    return "auto"


def set_embedding_preference(preference: str) -> str:
    """写入向量模型偏好；非法值抛 ValueError。"""
    preference = str(preference or "").strip().lower()
    if preference not in _VALID:
        raise ValueError(f"向量模型偏好必须是: {'、'.join(_VALID)}")
    _PREF_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json
    _PREF_PATH.write_text(
        json.dumps({"preference": preference}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return preference


def resolve_registry_cloud_embedder() -> Optional[Any]:
    """从模型注册表解析已验证的云端向量模型（无 local_path，如 SiliconFlow）。

    返回 CloudOpenAIEmbedder 实例；没有可用云端模型返回 None。
    """
    try:
        from .cloud_embedding import CloudOpenAIEmbedder
        from .model_registry import ModelRegistryService

        registry = ModelRegistryService()
        for entry in registry.get_redacted_registry().get("models", []):
            if not entry.get("verified"):
                continue
            if "embedding" not in entry.get("capabilities", []):
                continue
            if entry.get("local_path"):
                continue
            connection_id = entry.get("connection_id")
            if not connection_id:
                continue
            api_key = registry.resolve_connection_secret(connection_id)
            connection = registry.get_connection(connection_id)
            endpoint = (connection or {}).get("endpoint") or ""
            model_id = entry.get("model_id")
            if not api_key or not endpoint or not model_id:
                continue
            dimension = entry.get("metadata", {}).get("dimension")
            return CloudOpenAIEmbedder(
                endpoint=endpoint, api_key=api_key, model=model_id, dimension=dimension,
            )
    except Exception:
        return None
    return None
