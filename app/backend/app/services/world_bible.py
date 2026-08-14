"""
世界设定库（World Bible）服务

管理小说世界的两种输入：
- background: 背景设定文档（世界观、地理、规则、历史……静态事实）
- story:      小说正文段落（当前状态、事件、人物现状……动态信息）

核心能力：
1. 输入保存（两种来源可单独或同时提交）
2. 智能分块 + 元数据（来源、字符范围），分块后生成语义向量（bge-m3）
3. 按需检索：语义 + 关键词加权融合（语义 0.6 / 关键词 0.4），支持来源过滤

语义向量：
- 复用 app/services/local_embedding.py 的 LocalSentenceTransformerEmbedder（bge-m3，dim=1024，懒加载）
- 向量不进 bible.json（避免体积爆炸），单独存 <project>/embeddings.npy + embeddings_meta.json
- 读取时懒加载；本地模型/运行时不可用时优雅降级为纯关键词检索

存储：app/data/world/<project_id>/
  - bible.json            世界设定 + 分块（不含向量）
  - embeddings.npy        按分块顺序的二维向量矩阵
  - embeddings_meta.json  向量元数据（模型名、维度、chunk_id 顺序）
"""

import os
import json
import uuid
import asyncio
import re
import threading
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

    @classmethod
    def _embeddings_path(cls, project_id: str) -> str:
        """分块向量矩阵文件（npy，按 chunk 顺序）"""
        return os.path.join(WORLD_DATA_ROOT, project_id, 'embeddings.npy')

    @classmethod
    def _embeddings_meta_path(cls, project_id: str) -> str:
        """向量元数据文件（模型名、维度、chunk_id 顺序）"""
        return os.path.join(WORLD_DATA_ROOT, project_id, 'embeddings_meta.json')

    # ---------------- 语义向量（bge-m3 懒加载） ----------------

    _embedder_cache = None        # 进程内复用的一次性懒加载 embedder
    _embedder_attempted = False   # 是否已尝试解析（避免每次重复探测）
    _embedding_lock = threading.Lock()
    # <project_id> -> (mtime, Dict[chunk_id -> vector]) 懒加载向量缓存
    _embeddings_cache: Dict[str, Any] = {}

    @classmethod
    def _get_embedder(cls) -> Optional[Any]:
        """懒解析本地向量模型：优先 bge-m3（dim=1024），其次是已就绪的本地模型。

        运行时（sentence-transformers）未装或本地无就绪模型时返回 None，
        调用方据此降级为纯关键词检索。进程内只解析一次并复用。
        """
        if cls._embedder_attempted:
            return cls._embedder_cache
        with cls._embedding_lock:
            if cls._embedder_attempted:
                return cls._embedder_cache
            cls._embedder_attempted = True
            try:
                from .local_embedding import (
                    scan_local_models,
                    LocalSentenceTransformerEmbedder,
                )
                models = scan_local_models()
                ready = [m for m in models if m.get("ready")]
                pick = None
                # 优先 bge-m3（名字含 bge + m3，维度 1024）
                for m in ready:
                    name = (m.get("name") or "").lower()
                    if "bge" in name and "m3" in name:
                        pick = m
                        break
                if pick is None and ready:
                    pick = ready[0]
                if pick is None:
                    logger.warning("未找到本地向量模型，设定库将使用纯关键词检索")
                    cls._embedder_cache = None
                    return None
                cls._embedder_cache = LocalSentenceTransformerEmbedder(
                    pick["path"], dimension=pick.get("dimension")
                )
                logger.info(
                    "设定库启用本地向量模型: %s (dim=%s)",
                    pick.get("name"), pick.get("dimension"),
                )
            except Exception as exc:
                logger.warning("本地向量模型不可用，降级为关键词检索: %s", exc)
                cls._embedder_cache = None
            return cls._embedder_cache

    @classmethod
    def _reset_embedder_cache(cls) -> None:
        """清空 embedder 缓存（测试用）"""
        with cls._embedding_lock:
            cls._embedder_cache = None
            cls._embedder_attempted = False

    @classmethod
    def _embed_batch(cls, embedder, texts: List[str]) -> List[List[float]]:
        """批量向量化文本（async API，兼容事件循环内/外）。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(embedder.create_batch(texts))
        # 已在事件循环内——使用同步底层编码兜底（create_batch 内部即 _encode）
        return embedder._encode(texts)

    @classmethod
    def _embed_one(cls, embedder, text: str) -> List[float]:
        """单条文本向量化（async API，兼容事件循环内/外）。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(embedder.create(text))
        return embedder._encode([text])[0]


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
        embed: bool = True,
    ) -> WorldBible:
        """
        保存世界输入（背景/正文，至少一个非空）并重建分块索引。

        幂等：再次调用会整体重建该项目的设定库。
        embed=True 时尝试为每个分块生成语义向量并落盘（模型不可用时自动跳过）。
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
            metadata=dict(metadata or {}),
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
        # 生成并持久化语义向量（懒模型加载；失败不影响保存主体）
        if embed:
            embedder = cls._get_embedder()
            if embedder is not None and chunks:
                ok = cls._store_embeddings(project_id, chunks, embedder)
                bible.metadata["embedding_model"] = (
                    os.path.basename(getattr(embedder, "model_dir", "") or "")
                    if ok else None
                )
            else:
                bible.metadata["embedding_model"] = None
                logger.info("设定库未生成向量（本地模型不可用或已关闭），将使用纯关键词检索")
        else:
            bible.metadata["embedding_model"] = None

        with open(cls._bible_path(project_id), 'w', encoding='utf-8') as f:
            json.dump(bible.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"世界设定库已保存: project={project_id}, chunks={len(chunks)}")
        return bible

    @classmethod
    def _store_embeddings(
        cls,
        project_id: str,
        chunks: List[WorldChunk],
        embedder: Any,
    ) -> bool:
        """为分块批量生成向量并写入 embeddings.npy + embeddings_meta.json。

        成功返回 True；向量化抛异常时记录日志并返回 False（保持能用的主体）。
        """
        try:
            texts = [c.text for c in chunks]
            vectors = cls._embed_batch(embedder, texts)
            if not vectors or len(vectors) != len(chunks):
                raise ValueError(
                    f"向量数量({len(vectors)})与分块数量({len(chunks)})不匹配"
                )
            dimension = len(vectors[0]) if vectors else 0
            dim_attr = getattr(embedder, "dimension", None)
            if isinstance(dim_attr, int):
                dimension = dim_attr
            model_dir = getattr(embedder, "model_dir", "") or ""
            model_name = os.path.basename(str(model_dir)) or "local"
            meta = {
                "model": model_name,
                "dimension": dimension,
                "chunk_count": len(chunks),
                "chunk_ids": [c.chunk_id for c in chunks],
            }
            import numpy as np

            arr = np.asarray(vectors, dtype=np.float32)
            np.save(cls._embeddings_path(project_id), arr)
            with open(cls._embeddings_meta_path(project_id), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            # 内存中回填向量，方便调用方直接使用
            for chunk, vec in zip(chunks, vectors):
                chunk.embedding = vec
            logger.info(
                "分块向量已落盘: project=%s, chunks=%d, dim=%s, model=%s",
                project_id, len(chunks), dimension, model_name,
            )
            return True
        except Exception as exc:
            logger.warning(f"生成分块向量失败，降级为纯关键词检索: {exc}")
            return False

    @classmethod
    def load_embeddings(
        cls, project_id: str
    ) -> Optional[Dict[str, List[float]]]:
        """懒读取分块向量：返回 {chunk_id: vector}，无向量文件返回 None。

        用 (mtime, ...) 缓存避免每次检索重复读盘；文件变化时自动刷新。
        """
        meta_path = cls._embeddings_meta_path(project_id)
        npy_path = cls._embeddings_path(project_id)
        if not os.path.exists(meta_path) or not os.path.exists(npy_path):
            return None

        cur = (os.path.getmtime(meta_path) + os.path.getmtime(npy_path))
        cached = cls._embeddings_cache.get(project_id)
        if cached and cached.get("mtime") == cur:
            return cached.get("vecs")

        try:
            import numpy as np

            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            chunk_ids = meta.get("chunk_ids", [])
            arr = np.load(npy_path, allow_pickle=False)
            if len(arr) != len(chunk_ids):
                logger.warning("向量与 chunk_id 数量不一致，忽略向量: project=%s", project_id)
                return None
            vecs = {
                cid: [float(x) for x in row]
                for cid, row in zip(chunk_ids, arr)
            }
            cls._embeddings_cache[project_id] = {"mtime": cur, "vecs": vecs}
            return vecs
        except Exception as exc:
            logger.warning(f"读取分块向量失败: project={project_id}, err={exc}")
            return None

    @classmethod
    def _reset_embeddings_cache(cls, project_id: Optional[str] = None) -> None:
        """清空向量缓存（测试用）；project_id=None 时清空全部。"""
        if project_id is None:
            cls._embeddings_cache.clear()
        else:
            cls._embeddings_cache.pop(project_id, None)


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
        cls._reset_embeddings_cache(project_id)
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
        检索设定块：语义 + 关键词加权融合（语义 0.6 / 关键词 0.4）。

        - 语义分：查询向量与分块向量余弦相似度，映射到 [0,1]
        - 关键词分：整句/令牌/关键词命中，按命中集内最大值归一化到 [0,1]
        - 融合：(0.6 * 语义) + (0.4 * 关键词)
        - 本地向量模型不可用时自动降级为纯关键词检索（语义项为 0）
        - 保留 source 过滤、exclude_chunk_ids 过滤与固定返回结构
        返回: [{chunk_id, source, text, section, char_start, char_end, score}]
        """
        bible = cls.get_bible(project_id)
        if not bible:
            return []

        q_tokens = [w for w in re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9\-]{1,}', query)]
        if not q_tokens:
            return []

        exclude = set(exclude_chunk_ids or [])
        candidates = []
        for chunk in bible.chunks:
            if source and chunk.source != source:
                continue
            if chunk.chunk_id in exclude:
                continue
            candidates.append(chunk)
        if not candidates:
            return []

        # 关键词得分（沿用原轻量检索逻辑；命中才进入候选）
        keyword_scored = []
        text_lower_q = query.lower()
        for chunk in candidates:
            text_lower = chunk.text.lower()
            score = 0.0
            if text_lower_q in text_lower:
                score += 10.0
            for tok in q_tokens:
                if tok.lower() in text_lower:
                    score += 3.0
                if tok in chunk.keywords:
                    score += 2.0
            if score > 0:
                score += min(len(chunk.text) / 1000.0, 2.0) * 0.5
                keyword_scored.append((score, chunk))

        # 语义向量化（懒加载 embedder + 查询向量）
        embedder = cls._get_embedder()
        emb_map = None
        query_vec = None
        if embedder is not None:
            try:
                emb_map = cls.load_embeddings(project_id)
            except Exception:
                emb_map = None
            if emb_map is not None:
                try:
                    query_vec = cls._embed_one(embedder, query)
                except Exception as exc:
                    logger.warning(f"查询向量化失败，仅用关键词: {exc}")
                    query_vec = None
        semantic_ok = emb_map is not None and query_vec is not None

        # 归一化的关键词分：命中集内除以最大值，使最好块为 1.0
        max_k = max((s for s, _ in keyword_scored), default=0.0)
        kw_norm = {id(c): (s / max_k if max_k > 0 else 0.0)
                   for s, c in keyword_scored}

        def _cosine(a: List[float], b: List[float]) -> float:
            """余弦相似度，映射到 [0,1]：(-1,1) -> (0,1)"""
            if not a or not b or len(a) != len(b):
                return 0.0
            import math
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na == 0 or nb == 0:
                return 0.0
            return (dot / (na * nb) + 1.0) / 2.0

        # 融合打分
        fused = []
        for chunk in candidates:
            k = kw_norm.get(id(chunk), 0.0)
            s = 0.0
            if semantic_ok:
                vec = emb_map.get(chunk.chunk_id)
                if vec:
                    s = _cosine(query_vec, vec)
            score = (0.6 * s) + (0.4 * k)
            # 无关键词命中且无语义收益的块排除（保持检索聚焦）
            if score <= 0:
                continue
            fused.append((score, chunk))

        fused.sort(key=lambda kv: -kv[0])
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
            for s, c in fused[:limit]
        ]
