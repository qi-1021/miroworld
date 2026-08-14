"""向量模型指纹计算。

指纹用于把"图谱使用的向量模型"与"当前快照配置"绑定：
指纹不一致时，禁止向已有图谱混写向量（会导致检索语义错乱）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional


def compute_embedding_fingerprint(
    *,
    provider: str,
    model_id: str,
    dimension: Optional[int] = None,
    max_length: Optional[int] = None,
    model_type: Optional[str] = None,
    local_path: Optional[str] = None,
    normalize: bool = True,
    query_prefix: str = "",
    document_prefix: str = "",
) -> str:
    """计算向量模型指纹。

    对本地模型，local_path 采用相对目录名而非绝对路径，保证跨机器一致。
    """
    payload: Dict[str, Any] = {
        "provider": provider,
        "model_id": model_id,
        "dimension": dimension,
        "max_length": max_length,
        "model_type": model_type,
        "local_path": local_path,
        "normalize": normalize,
        "query_prefix": query_prefix,
        "document_prefix": document_prefix,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
