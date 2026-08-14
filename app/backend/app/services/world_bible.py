"""
世界设定库（World Bible）服务

管理小说世界的两种输入：
- background: 背景设定文档（世界观、地理、规则、历史……静态事实）
- story:      小说正文段落（当前状态、事件、人物现状……动态信息）

核心能力：
1. 输入保存（两种来源可单独或同时提交）
2. 智能分块 + 元数据（来源、字符范围），为后续向量化预留扩展点
3. 按需检索：关键词 + 来源过滤，返回相关块（后续可升级为语义检索）

存储：app/data/world/<project_id>/bible.json
"""

import os
import json
import uuid
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.file_parser import split_text_into_chunks

logger = get_logger('mirofish.world_bible')

# 世界设定数据根目录
WORLD_DATA_ROOT = os.path.join(os.path.dirname(__file__), '../../data/world')


# ---------------------------------------------------------------- 数据模型

@dataclass
class WorldChunk:
    """设定库中的一个文本块"""
    chunk_id: str
    source: str              # 'background' | 'story'
    text: str
    char_start: int = 0      # 在原始文本中的起始偏移
    char_end: int = 0        # 在原始文本中的结束偏移
    section: str = ""        # 章节/主题路径（如 地理/东境），后续由结构解析填充
    keywords: List[str] = field(default_factory=list)  # 该块的关键词（用于轻量检索）
    embedding: Optional[List[float]] = None  # 预留：向量化后填充

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop('embedding', None)  # 向量不落盘（第一阶段）
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorldChunk':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorldBible:
    """一个项目完整的世界设定库"""
    project_id: str
    background_text: str = ""
    story_text: str = ""
    chunks: List[WorldChunk] = field(default_factory=list)
    updated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)  # 预留：来源文件名、版本等

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "background_text": self.background_text,
            "story_text": self.story_text,
            "chunks": [c.to_dict() for c in self.chunks],
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorldBible':
        return cls(
            project_id=data.get('project_id', ''),
            background_text=data.get('background_text', ''),
            story_text=data.get('story_text', ''),
            chunks=[WorldChunk.from_dict(c) for c in data.get('chunks', [])],
            updated_at=data.get('updated_at', ''),
            metadata=data.get('metadata', {}),
        )

    def stats(self) -> Dict[str, Any]:
        """统计摘要"""
        bg_chunks = [c for c in self.chunks if c.source == 'background']
        st_chunks = [c for c in self.chunks if c.source == 'story']
        return {
            "project_id": self.project_id,
            "background_chars": len(self.background_text),
            "story_chars": len(self.story_text),
            "background_chunks": len(bg_chunks),
            "story_chunks": len(st_chunks),
            "total_chunks": len(self.chunks),
            "updated_at": self.updated_at,
            "has_background": bool(self.background_text.strip()),
            "has_story": bool(self.story_text.strip()),
        }


# ---------------------------------------------------------------- 服务

class WorldBibleService:
    """世界设定库服务"""

    @classmethod
    def _ensure_dir(cls, project_id: str) -> str:
        d = os.path.join(WORLD_DATA_ROOT, project_id)
        os.makedirs(d, exist_ok=True)
        return d

    @classmethod
    def _bible_path(cls, project_id: str) -> str:
        return os.path.join(WORLD_DATA_ROOT, project_id, 'bible.json')

    # ---------------- 输入与索引 ----------------

    @classmethod
    def save_input(
        cls,
        project_id: str,
        background: str = "",
        story: str = "",
        chunk_size: int = 500,
        overlap: int = 50,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorldBible:
        """
        保存世界输入（背景/正文，至少一个非空）并重建分块索引。

        幂等：再次调用会整体重建该项目的设定库。
        """
        background = background or ""
        story = story or ""
        if not background.strip() and not story.strip():
            raise ValueError("背景文档和小说正文不能同时为空，至少需要输入一个")

        bible = WorldBible(
            project_id=project_id,
            background_text=background,
            story_text=story,
            updated_at=datetime.now().isoformat(timespec='seconds'),
            metadata=metadata or {},
        )

        chunks: List[WorldChunk] = []
        if background.strip():
            chunks.extend(cls._chunk_text(
                text=background,
                source='background',
                chunk_size=chunk_size,
                overlap=overlap,
            ))
        if story.strip():
            chunks.extend(cls._chunk_text(
                text=story,
                source='story',
                chunk_size=chunk_size,
                overlap=overlap,
            ))
        bible.chunks = chunks

        cls._ensure_dir(project_id)
        with open(cls._bible_path(project_id), 'w', encoding='utf-8') as f:
            json.dump(bible.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"世界设定库已保存: project={project_id}, chunks={len(chunks)}")
        return bible

    @classmethod
    def _chunk_text(
        cls,
        text: str,
        source: str,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> List[WorldChunk]:
        """分块并附带偏移与关键词"""
        raw_chunks = split_text_into_chunks(text, chunk_size, overlap)
        chunks: List[WorldChunk] = []
        offset = 0
        for raw in raw_chunks:
            start = text.find(raw, offset)
            if start == -1:
                start = offset
            end = start + len(raw)
            chunks.append(WorldChunk(
                chunk_id=f"{source}_{uuid.uuid4().hex[:12]}",
                source=source,
                text=raw,
                char_start=start,
                char_end=end,
                keywords=cls._extract_keywords(raw),
            ))
            offset = end
        return chunks

    @staticmethod
    def _extract_keywords(text: str, limit: int = 12) -> List[str]:
        """提取块内的高频关键词（中文简化分词：按标点切短语 + 去停用词）"""
        # 按中英文标点切分成短语，保留 2-12 字的短语作为候选关键词
        phrases = re.split(r'[，。！？；：、,.!?;:\s\n"\'""''（）()【】\[\]「」『』]', text)
        tokens = []
        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue
            if 2 <= len(phrase) <= 12:
                tokens.append(phrase)
            else:
                tokens.extend(re.findall(r'[A-Za-z][A-Za-z0-9\-]{2,}', phrase))
        stopwords = {
            '我们', '他们', '你们', '这个', '那个', '一个', '一些', '什么', '怎么',
            '自己', '已经', '可以', '没有', '不是', '还是', '就是', '但是', '因为',
            '所以', '如果', '然后', '现在', '时候', '这样', '那样', '以及', '并且',
            '东西', '地方', '知道', '觉得', '看着', '说道', '有些', '有点', '开始',
            '终于', '突然', '似乎', '仿佛', '好像', '也许', '大概', '难道', '居然',
            'with', 'that', 'this', 'have', 'from', 'were', 'there', 'about',
            '清晨', '低声说', '正在', '路过的', '施法者每', '王国建于', '手施展了',
        }
        seen = {}
        for t in tokens:
            tl = t.lower()
            if tl in stopwords or len(tl) < 2:
                continue
            seen[t] = seen.get(t, 0) + 1
        ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
        return [w for w, _ in ranked[:limit]]

    # ---------------- 读取 ----------------

    @classmethod
    def get_bible(cls, project_id: str) -> Optional[WorldBible]:
        """读取设定库，不存在返回 None"""
        path = cls._bible_path(project_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return WorldBible.from_dict(json.load(f))
        except Exception as e:
            logger.error(f"读取世界设定库失败: project={project_id}, err={e}")
            return None

    @classmethod
    def get_stats(cls, project_id: str) -> Optional[Dict[str, Any]]:
        bible = cls.get_bible(project_id)
        return bible.stats() if bible else None

    @classmethod
    def delete(cls, project_id: str) -> bool:
        """删除项目的设定库"""
        d = os.path.join(WORLD_DATA_ROOT, project_id)
        if os.path.isdir(d):
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            return True
        return False

    # ---------------- 检索 ----------------

    @classmethod
    def search(
        cls,
        project_id: str,
        query: str,
        source: Optional[str] = None,
        limit: int = 8,
        exclude_chunk_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        按需检索设定块（有限筛选）。

        第一阶段：关键词命中 + 来源过滤的轻量检索。
        后续扩展：chunk.embedding 就绪后升级为语义 + 关键词混合检索。
        """
        bible = cls.get_bible(project_id)
        if not bible:
            return []

        # 查询关键词
        q_tokens = [w for w in re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9\-]{1,}', query)]
        if not q_tokens:
            return []

        exclude = set(exclude_chunk_ids or [])
        scored = []
        for chunk in bible.chunks:
            if source and chunk.source != source:
                continue
            if chunk.chunk_id in exclude:
                continue
            text_lower = chunk.text.lower()
            q_lower = query.lower()
            score = 0.0
            # 整句命中权重最高
            if q_lower in text_lower:
                score += 10.0
            for tok in q_tokens:
                if tok.lower() in text_lower:
                    score += 3.0
                if tok in chunk.keywords:
                    score += 2.0
            # 关键词命中密度
            if score > 0:
                score += min(len(chunk.text) / 1000.0, 2.0) * 0.5
                scored.append((score, chunk))

        scored.sort(key=lambda kv: -kv[0])
        return [
            {
                "chunk_id": c.chunk_id,
                "source": c.source,
                "text": c.text,
                "section": c.section,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "score": round(s, 2),
            }
            for s, c in scored[:limit]
        ]
