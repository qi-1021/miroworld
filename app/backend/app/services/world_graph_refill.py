"""
世界图谱补边（edge refill）

背景：建图时 edge-skip patch（GRAPHITI_EDGE_MODE=skip）会跳过全部边提取，
图谱"有节点没边"。补边 = 把建图时缓存的 episode 文本重放一遍，逐条在
事件循环线程内、持锁状态下临时切换边提取环境：

- Config.GRAPHITI_EDGE_MODE 临时置为 'always'（不再跳过边提取）
- graphiti_core edge_operations.MAX_NODES 临时降到 4（块更小，边提取更稳）

环境切换在 GraphitiClient.add_episode_for_edge_refill 内部完成（专用
事件循环线程 + 与建图 episode 共享同一把 asyncio.Lock），互斥且逐条恢复，
不会泄漏到并发建图任务。已入库的实体会被去重合并（不会重复建点），
而边会被尝试提取出来。补边是低频操作，单条 episode 重跑开销可接受；
单条有界重试（默认 2 次），仍失败就跳过该条，不中断整体。

数据结构：
- data/world-graph/<project_id>/episodes.json  = [ "<chunk文本>", ... ]
  （data/ 已在 .gitignore，目录无需额外处理）
"""

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json
from ..services.zep_factory import get_zep_client

logger = get_logger('mirofish.api.world')

# 补边数据根目录（app/backend/data/world-graph，已 gitignore）
# 注意：__file__ 在 app/backend/app/services/ 下，需上溯 3 层才到 app/backend/
WORLD_GRAPH_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'world-graph',
)

# 单条 episode 最大重试次数
MAX_EPISODE_RETRIES = 2

# 补边时的边提取分块大小（更小更稳）
REFILL_MAX_NODES = 4

# project_id 白名单：proj_ + 12 位小写 hex（与 ProjectManager.create_project 一致）。
# 缓存路径由 URL 段拼接而来，白名单从源头阻断路径穿越（../、绝对路径等）。
_PROJECT_ID_RE = re.compile(r'^proj_[0-9a-f]{12}$')


def validate_project_id(project_id: str) -> str:
    """校验 project_id 格式，非法则抛 ValueError。返回原值便于链式调用。"""
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(f"非法 project_id: {project_id!r}")
    return project_id


def episodes_cache_path(project_id: str) -> str:
    """episodes 缓存文件路径（project_id 必须先通过白名单校验）。"""
    return os.path.join(WORLD_GRAPH_ROOT, validate_project_id(project_id), 'episodes.json')


def save_episodes_cache(project_id: str, texts: List[str]) -> bool:
    """建图时把各 chunk 文本缓存到磁盘。失败仅警告，不影响建图主流程。"""
    try:
        path = episodes_cache_path(project_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, [t for t in texts])
        return True
    except Exception as e:
        logger.warning(f"缓存世界图谱 episodes 失败（忽略）：{e}")
        return False


def load_episodes_cache(project_id: str) -> Optional[List[str]]:
    """读取缓存的 episode 文本列表；不存在/失败返回 None。"""
    try:
        path = episodes_cache_path(project_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        return [str(t) for t in data]
    except Exception as e:
        logger.warning(f"读取 episodes 缓存失败：{e}")
        return None


# ---------------------------------------------------------------------------
# 建图断点进度（build-progress.json）
# ---------------------------------------------------------------------------

def build_progress_path(project_id: str) -> str:
    """建图断点文件：data/world-graph/<project_id>/build-progress.json"""
    return os.path.join(
        WORLD_GRAPH_ROOT,
        validate_project_id(project_id),
        'build-progress.json',
    )


def chunk_hash(text: str) -> str:
    """chunk 文本 sha1，用于判断源文本是否变化。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def load_build_progress(project_id: str) -> Optional[Dict[str, Any]]:
    """读取建图断点。返回 {"chunks": [{index, hash, status, episode_uuid}], "graph_id": ...} 或 None。"""
    try:
        path = build_progress_path(project_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("chunks"), list):
            return None
        return data
    except Exception as e:
        logger.warning(f"读取建图断点失败（忽略）: {e}")
        return None


def save_build_progress(
    project_id: str,
    chunks_state: List[Dict[str, Any]],
    graph_id: Optional[str] = None,
) -> bool:
    """原子写建图断点。失败仅告警。"""
    try:
        path = build_progress_path(project_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, {
            "project_id": project_id,
            "graph_id": graph_id or "",
            "chunks": chunks_state,
            "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        })
        return True
    except Exception as e:
        logger.warning(f"保存建图断点失败（忽略）: {e}")
        return False


def mark_chunks_done(
    project_id: str,
    chunks: List[str],
    indices: List[int],
    episode_uuids: List[str],
    graph_id: Optional[str] = None,
) -> None:
    """把一批成功写入的 chunk 标记为 done 并保存到 build-progress.json。"""
    progress = load_build_progress(project_id) or {"chunks": []}
    by_index = {
        int(item.get("index", -1)): item
        for item in progress.get("chunks", [])
        if isinstance(item, dict)
    }
    for idx, text, uuid_ in zip(indices, chunks, episode_uuids):
        by_index[idx] = {
            "index": idx,
            "hash": chunk_hash(text),
            "status": "done",
            "episode_uuid": uuid_ or "",
        }
    save_build_progress(
        project_id,
        [by_index[k] for k in sorted(by_index) if k >= 0],
        graph_id=graph_id or progress.get("graph_id"),
    )


def run_edge_refill(
    project_id: str,
    graph_id: str,
    task_manager,
    task_id: str,
) -> Dict[str, object]:
    """
    补边执行体（在后台线程中调用）。返回统计 dict。

    - 读取缓存的 episodes；为空则抛 ValueError（由调用方 fail task）。
    - 逐条调用 client.add_episode_for_edge_refill（客户端内部持锁切换
      always + MAX_NODES=4，天然与并发建图互斥，不在此线程改写全局配置），
      单条有界重试（MAX_EPISODE_RETRIES），失败跳过。
    """
    texts = load_episodes_cache(project_id)
    if not texts:
        raise ValueError(f"没有可补边的 episode 缓存（project_id={project_id}）")

    client = get_zep_client()

    total = len(texts)
    refilled = 0
    failed = 0
    for i, text in enumerate(texts):
        last_err = None
        ok = False
        for attempt in range(MAX_EPISODE_RETRIES + 1):
            try:
                uuid = client.add_episode_for_edge_refill(
                    graph_id=graph_id,
                    data=text,
                    edge_mode='always',
                    max_nodes=REFILL_MAX_NODES,
                )
                if uuid:
                    ok = True
                    break
                last_err = "add_episode 返回空 uuid"
            except Exception as exc:
                last_err = str(exc)
                logger.warning(
                    f"补边 episode {i} 第 {attempt + 1} 次失败: {last_err[:120]}"
                )
            if attempt < MAX_EPISODE_RETRIES:
                import time as _time
                _time.sleep(0.5 * (attempt + 1))
        if ok:
            refilled += 1
        else:
            failed += 1
            logger.warning(f"补边 episode {i} 多次失败后跳过（已失败 {failed} 条）")

        # 报进度（80% 前按条推进）
        task_manager.update_task(
            task_id,
            progress=min(99, int((i + 1) / total * 80)) if total else 0,
            message=f"补边 {i + 1}/{total}（成功 {refilled}，跳过 {failed}）",
        )

    return {
        "total": total,
        "refilled": refilled,
        "failed": failed,
        "graph_id": graph_id,
    }


def start_edge_refill(
    project_id: str,
    graph_id: str,
    task_manager,
    task_type: str = "world_edge_refill",
) -> str:
    """
    创建补边后台任务并返回 task_id。
    校验：缓存存在、project 已有 graph_id。
    """
    if not graph_id:
        raise ValueError("项目尚未构建图谱，无法补边")
    if not load_episodes_cache(project_id):
        raise ValueError("没有可补边的 episode 缓存")

    task_id = task_manager.create_task(task_type=task_type)
    task_manager.update_task(
        task_id, progress=0, message="准备补边..."
    )

    def _refill_task():
        import traceback
        from ..models.task import TaskStatus
        try:
            task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=1,
                                     message="开始补边（重放 episode，提取边）...")
            result = run_edge_refill(project_id, graph_id, task_manager, task_id)
            task_manager.complete_task(
                task_id,
                result={
                    "total": result["total"],
                    "refilled": result["refilled"],
                    "failed": result["failed"],
                },
            )
        except ValueError as e:
            task_manager.fail_task(task_id, str(e))
        except Exception as e:
            from .llm_error_normalizer import normalize_llm_error
            friendly = normalize_llm_error(e)
            logger.error(f"补边任务失败: {e}\n{traceback.format_exc()}")
            task_manager.fail_task(task_id, friendly)

    import threading
    threading.Thread(target=_refill_task, daemon=True).start()
    return task_id
