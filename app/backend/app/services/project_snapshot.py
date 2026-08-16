"""项目快照导出/导入服务。

快照是 JSON 对象（也可由前端打包为 .miroworld.json 文件），包含：
- 项目元数据（名称、本体、状态、图谱 id、模拟需求、分块配置）
- 提取原文 extracted_text
- 世界设定库 bible（背景/正文/分块/元数据）
- 时间线 timeline + 人物档案 characters
- 冲突报告 conflicts
- 项目模型绑定 model_bindings

导入时：
- 创建全新 project_id（避免与现有项目冲突）
- 恢复上述全部文件数据
- graph_id 原样保留（同一台机器上 Neo4j 数据仍存在时可直接继续使用；
  跨机器/数据丢失时用户可点击“重建图谱”强制重来）
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from ..models.project import ProjectManager, ProjectStatus
from ..utils.logger import get_logger
from ..utils.atomic_json import atomic_write_json

logger = get_logger("mirofish.snapshot")

SNAPSHOT_FORMAT = "mirofish-project-snapshot"
SNAPSHOT_VERSION = 1


def _read_text(path: str) -> str:
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"读取文本失败: {path}, {e}")
        return ""


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"读取 JSON 失败: {path}, {e}")
        return None


def export_project_snapshot(project_id: str) -> Dict[str, Any]:
    """导出项目完整快照（JSON dict）。"""
    from . import timeline_service
    from .conflict_detector import load_conflict_report
    from .world_bible import WorldBibleService, WORLD_DATA_ROOT

    project = ProjectManager.get_project(project_id)
    if project is None:
        raise ValueError(f"项目不存在: {project_id}")

    # 提取原文
    project_dir = ProjectManager._get_project_dir(project_id)
    extracted_text = _read_text(os.path.join(project_dir, "extracted_text.txt"))

    # 世界设定库
    bible_path = os.path.join(WORLD_DATA_ROOT, project_id, "bible.json")
    world_bible = _read_json(bible_path)

    # 时间线与人物
    timeline = timeline_service.load_timeline(project_id, None)
    characters = timeline_service.load_characters(project_id)

    # 冲突报告
    report = load_conflict_report(project_id)
    conflicts = report.to_dict() if report is not None else None

    # 模型绑定
    model_bindings = None
    try:
        from ..services.model_registry import ModelRegistryService
        bindings = ModelRegistryService().get_project_bindings(project_id)
        if bindings is not None:
            model_bindings = bindings.to_dict()
    except Exception as e:
        logger.warning(f"读取项目模型绑定失败（忽略）: {e}")

    snapshot = {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source_project_id": project_id,
        "project": project.to_dict(),
        "extracted_text": extracted_text,
        "world_bible": world_bible,
        "timeline": timeline,
        "characters": characters,
        "conflicts": conflicts,
        "model_bindings": model_bindings,
    }
    return snapshot


def import_project_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """从快照创建新项目并恢复全部已完成步骤。返回新项目 dict。"""
    from . import timeline_service
    from .conflict_detector import ConflictReport, save_conflict_report
    from .world_bible import WorldBibleService
    from ..models.model_config import RoleBindings

    if not isinstance(snapshot, dict):
        raise ValueError("快照必须是 JSON 对象")
    if snapshot.get("format") not in (SNAPSHOT_FORMAT, "miroworld-project-snapshot"):
        raise ValueError("不是有效的 Miroworld 项目快照")
    old_project = snapshot.get("project") or {}
    if not isinstance(old_project, dict):
        raise ValueError("快照缺少 project 元数据")

    name = str(old_project.get("name") or "导入项目").strip() or "导入项目"
    project = ProjectManager.create_project(name=name)

    # 恢复项目元数据（不复制 source_project_id）
    project.simulation_requirement = old_project.get("simulation_requirement")
    project.ontology = old_project.get("ontology")
    project.analysis_summary = old_project.get("analysis_summary")
    project.chunk_size = int(old_project.get("chunk_size") or 1500)
    project.chunk_overlap = int(old_project.get("chunk_overlap") or 150)
    project.files = list(old_project.get("files") or [])
    graph_id = old_project.get("graph_id")
    if graph_id:
        project.graph_id = graph_id
        project.status = ProjectStatus.GRAPH_COMPLETED
    elif project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED
    ProjectManager.save_project(project)

    # 恢复提取原文
    extracted_text = str(snapshot.get("extracted_text") or "")
    if extracted_text:
        ProjectManager.save_extracted_text(project.project_id, extracted_text)

    # 恢复世界设定库
    bible = snapshot.get("world_bible") or {}
    if isinstance(bible, dict) and (
        str(bible.get("background_text") or "").strip()
        or str(bible.get("story_text") or "").strip()
    ):
        metadata = dict(bible.get("metadata") or {})
        # 文件清单来自旧项目，保留展示；实际文件未复制时仅作记录
        WorldBibleService.save_input(
            project_id=project.project_id,
            background=str(bible.get("background_text") or ""),
            story=str(bible.get("story_text") or ""),
            chunk_size=project.chunk_size,
            overlap=project.chunk_overlap,
            metadata=metadata,
            embed=False,
        )

    # 恢复时间线
    timeline = snapshot.get("timeline") or {}
    events = timeline.get("events") if isinstance(timeline, dict) else []
    if isinstance(events, list) and events:
        timeline_service._save_timeline(project.project_id, events)

    # 恢复人物档案
    characters = snapshot.get("characters") or []
    if isinstance(characters, list) and characters:
        timeline_service.save_characters(project.project_id, characters)

    # 恢复冲突报告
    conflicts = snapshot.get("conflicts")
    if isinstance(conflicts, dict):
        try:
            report = ConflictReport.from_dict(conflicts)
            save_conflict_report(project.project_id, report)
        except Exception as e:
            logger.warning(f"恢复冲突报告失败（忽略）: {e}")

    # 恢复模型绑定
    bindings = snapshot.get("model_bindings")
    if isinstance(bindings, dict) and bindings:
        try:
            from ..services.model_registry import ModelRegistryService
            registry = ModelRegistryService()
            registry.save_project_bindings(
                project_id=project.project_id,
                bindings=RoleBindings.from_dict(bindings),
                expected_revision=registry.get_redacted_registry()["revision"],
            )
        except Exception as e:
            logger.warning(f"恢复模型绑定失败（忽略）: {e}")

    logger.info(f"项目快照导入完成: {project.project_id}")
    return project.to_dict()
