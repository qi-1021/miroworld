"""
项目上下文管理
用于在服务端持久化项目状态，避免前端在接口间传递大量数据
"""

import os
import json
import uuid
import shutil
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field, asdict
from ..config import Config
from ..utils.atomic_json import atomic_write_json

logger = logging.getLogger('mirofish.project')


class ProjectStatus(str, Enum):
    """项目状态"""
    CREATED = "created"              # 刚创建，文件已上传
    ONTOLOGY_GENERATED = "ontology_generated"  # 本体已生成
    GRAPH_BUILDING = "graph_building"    # 图谱构建中
    GRAPH_COMPLETED = "graph_completed"  # 图谱构建完成
    FAILED = "failed"                # 失败


@dataclass
class Project:
    """项目数据模型"""
    project_id: str
    name: str
    status: ProjectStatus
    created_at: str
    updated_at: str

    # 文件信息
    files: List[Dict[str, str]] = field(default_factory=list)  # [{filename, path, size}]
    total_text_length: int = 0

    # 本体信息（接口1生成后填充）
    ontology: Optional[Dict[str, Any]] = None
    analysis_summary: Optional[str] = None

    # 图谱信息（接口2完成后填充）
    graph_id: Optional[str] = None
    graph_build_task_id: Optional[str] = None

    # 配置
    simulation_requirement: Optional[str] = None
    # 与 Config.DEFAULT_CHUNK_SIZE 保持一致（1500 字符，减少 episode 数与 LLM 调用）
    chunk_size: int = 1500
    chunk_overlap: int = 150

    # 错误信息
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, ProjectStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": self.files,
            "total_text_length": self.total_text_length,
            "ontology": self.ontology,
            "analysis_summary": self.analysis_summary,
            "graph_id": self.graph_id,
            "graph_build_task_id": self.graph_build_task_id,
            "simulation_requirement": self.simulation_requirement,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "error": self.error
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """从字典创建"""
        status = data.get('status', 'created')
        if isinstance(status, str):
            status = ProjectStatus(status)

        return cls(
            project_id=data['project_id'],
            name=data.get('name', 'Unnamed Project'),
            status=status,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            files=data.get('files', []),
            total_text_length=data.get('total_text_length', 0),
            ontology=data.get('ontology'),
            analysis_summary=data.get('analysis_summary'),
            graph_id=data.get('graph_id'),
            graph_build_task_id=data.get('graph_build_task_id'),
            simulation_requirement=data.get('simulation_requirement'),
            chunk_size=data.get('chunk_size', 1500),
            chunk_overlap=data.get('chunk_overlap', 150),
            error=data.get('error')
        )


class ProjectManager:
    """项目管理器 - 负责项目的持久化存储和检索"""

    # 项目存储根目录
    PROJECTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'projects')

    @classmethod
    def _ensure_projects_dir(cls):
        """确保项目目录存在"""
        os.makedirs(cls.PROJECTS_DIR, exist_ok=True)

    @classmethod
    def _get_project_dir(cls, project_id: str) -> str:
        """获取项目目录路径"""
        return os.path.join(cls.PROJECTS_DIR, project_id)

    @classmethod
    def _get_project_meta_path(cls, project_id: str) -> str:
        """获取项目元数据文件路径"""
        return os.path.join(cls._get_project_dir(project_id), 'project.json')

    @classmethod
    def _get_project_files_dir(cls, project_id: str) -> str:
        """获取项目文件存储目录"""
        return os.path.join(cls._get_project_dir(project_id), 'files')

    @classmethod
    def _get_project_text_path(cls, project_id: str) -> str:
        """获取项目提取文本存储路径"""
        return os.path.join(cls._get_project_dir(project_id), 'extracted_text.txt')

    @classmethod
    def create_project(cls, name: str = "Unnamed Project") -> Project:
        """
        创建新项目

        Args:
            name: 项目名称

        Returns:
            新创建的Project对象
        """
        cls._ensure_projects_dir()

        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        project = Project(
            project_id=project_id,
            name=name,
            status=ProjectStatus.CREATED,
            created_at=now,
            updated_at=now
        )

        # 创建项目目录结构
        project_dir = cls._get_project_dir(project_id)
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(files_dir, exist_ok=True)

        # 自动绑定当前可用的已验证主模型，避免新项目继续使用旧 .env 配置
        try:
            from ..services.model_registry import ModelRegistryService
            from ..models.model_config import ModelRole, RoleBindings

            registry = ModelRegistryService()
            registry_state = registry.get_redacted_registry()
            verified_chat = [
                item for item in registry_state["models"]
                if item.get("verified") and "chat" in item.get("capabilities", [])
            ]
            if verified_chat:
                registry.save_project_bindings(
                    project_id=project_id,
                    bindings=RoleBindings(
                        roles={ModelRole.PRIMARY: verified_chat[0]["id"]}
                    ),
                    expected_revision=registry_state["revision"],
                )
        except Exception:
            # 模型注册表不可用时不阻塞项目创建，后续可在设置中绑定
            pass

        # 保存项目元数据
        cls.save_project(project)

        return project

    @classmethod
    def save_project(cls, project: Project) -> None:
        """保存项目元数据（原子写，避免写一半崩溃损坏 project.json）。"""
        project.updated_at = datetime.now().isoformat()
        meta_path = cls._get_project_meta_path(project.project_id)
        cls._ensure_projects_dir()
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        atomic_write_json(meta_path, project.to_dict())

    @classmethod
    def get_project(cls, project_id: str) -> Optional[Project]:
        """
        获取项目

        Args:
            project_id: 项目ID

        Returns:
            Project对象，如果不存在返回None
        """
        meta_path = cls._get_project_meta_path(project_id)

        if not os.path.exists(meta_path):
            return None

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Project.from_dict(data)
        except Exception as e:
            logger.warning(f"读取项目元数据失败（按不存在处理）: {project_id}, {e}")
            return None

    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Project]:
        """
        列出所有项目

        Args:
            limit: 返回数量限制

        Returns:
            项目列表，按创建时间倒序
        """
        cls._ensure_projects_dir()

        projects = []
        for project_id in sorted(os.listdir(cls.PROJECTS_DIR)):
            if not os.path.isdir(os.path.join(cls.PROJECTS_DIR, project_id)):
                continue
            project = cls.get_project(project_id)
            if project:
                projects.append(project)

        # 按创建时间倒序排序
        projects.sort(key=lambda p: p.created_at, reverse=True)

        return projects[:limit]

    @classmethod
    def recover_interrupted_projects(cls) -> int:
        """启动时恢复：把重启前处于 GRAPH_BUILDING 的项目标记为 FAILED。

        图谱构建任务保存在进程内 TaskManager（重启即丢），进程重启后若项目
        仍停在 graph_building，会永远无法重新构建。这里一次性恢复为失败态，
        前端即可重新发起（/build 支持 force，失败态也允许直接重建）。
        """
        recovered = 0
        if not os.path.isdir(cls.PROJECTS_DIR):
            return recovered
        for project_id in sorted(os.listdir(cls.PROJECTS_DIR)):
            project_dir = os.path.join(cls.PROJECTS_DIR, project_id)
            if not os.path.isdir(project_dir):
                continue
            project = cls.get_project(project_id)
            if not project:
                continue
            if project.status == ProjectStatus.GRAPH_BUILDING:
                project.status = ProjectStatus.FAILED
                project.error = "服务重启，图谱构建中断；请重新发起构建"
                project.graph_build_task_id = None
                cls.save_project(project)
                recovered += 1
                logger.info(
                    "启动恢复：项目 %s 的图谱构建中断，已标记为 failed",
                    project_id,
                )
        return recovered

    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        """
        删除项目及其所有文件

        Args:
            project_id: 项目ID

        Returns:
            是否删除成功
        """
        project_dir = cls._get_project_dir(project_id)

        if not os.path.exists(project_dir):
            return False

        shutil.rmtree(project_dir)
        return True

    @classmethod
    def save_file_to_project(cls, project_id: str, file_storage, original_filename: str) -> Dict[str, str]:
        """
        保存上传的文件到项目目录

        Args:
            project_id: 项目ID
            file_storage: Flask的FileStorage对象
            original_filename: 原始文件名

        Returns:
            文件信息字典 {filename, path, size}
        """
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(files_dir, exist_ok=True)

        # 生成安全的文件名
        ext = os.path.splitext(original_filename)[1].lower()
        safe_filename = f"{uuid.uuid4().hex[:8]}{ext}"
        file_path = os.path.join(files_dir, safe_filename)

        # 保存文件
        file_storage.save(file_path)

        # 获取文件大小
        file_size = os.path.getsize(file_path)

        return {
            "original_filename": original_filename,
            "saved_filename": safe_filename,
            "path": file_path,
            "size": file_size
        }

    @classmethod
    def save_extracted_text(cls, project_id: str, text: str) -> None:
        """保存提取的文本"""
        text_path = cls._get_project_text_path(project_id)
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text)

    @classmethod
    def get_extracted_text(cls, project_id: str) -> Optional[str]:
        """获取提取的文本"""
        text_path = cls._get_project_text_path(project_id)

        if not os.path.exists(text_path):
            return None

        with open(text_path, 'r', encoding='utf-8') as f:
            return f.read()

    @classmethod
    def get_project_files(cls, project_id: str) -> List[str]:
        """获取项目的所有文件路径"""
        files_dir = cls._get_project_files_dir(project_id)

        if not os.path.exists(files_dir):
            return []

        return [
            os.path.join(files_dir, f)
            for f in os.listdir(files_dir)
            if os.path.isfile(os.path.join(files_dir, f))
        ]

