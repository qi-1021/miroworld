"""
Graphiti 本地客户端实现

使用 graphiti-core + Neo4j 实现本地知识图谱服务。
替代 Zep Cloud，实现 ZepClientAdapter 接口。

MVP 范围：
- 图谱创建/删除（使用 group_id 隔离）
- Episode 添加（单条/批量）
- 节点/边检索
- 语义搜索

Ontology 在 MVP 阶段先 no-op。
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from functools import lru_cache

from .zep_adapter import (
    ZepClientAdapter,
    GraphNode,
    GraphEdge,
    SearchResult,
    EpisodeStatus,
)

logger = logging.getLogger('mirofish.graphiti_client')


# ============================================================================
# 单后台线程 + 专用事件循环（方案 A）
# ============================================================================
# 所有 Graphiti/Neo4j 异步操作都在这个专用线程的事件循环中执行
# Flask 线程通过 run_coroutine_threadsafe 提交任务并等待结果
# ============================================================================

_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_thread: Optional[threading.Thread] = None
_init_lock = threading.Lock()
# episode 提交互斥锁：建图与补边重放共用。补边在事件循环线程内临时把
# 边提取环境切换为 always+小块，持锁保证并发建图 episode 不会读到该环境、
# 补边也不会被建图的 skip 模式干扰。所有 acquire 都发生在专用循环线程上
# （asyncio 协作式锁，await 不会阻塞线程，无死锁风险）。
_episode_lock: Optional[asyncio.Lock] = None


def _start_async_loop():
    """在后台线程中启动事件循环"""
    global _async_loop
    _async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_async_loop)
    logger.info("Graphiti 专用事件循环已启动")
    _async_loop.run_forever()


def _ensure_async_loop():
    """确保后台事件循环已启动"""
    global _async_thread
    if _async_thread is None or not _async_thread.is_alive():
        with _init_lock:
            if _async_thread is None or not _async_thread.is_alive():
                _async_thread = threading.Thread(
                    target=_start_async_loop,
                    daemon=True,
                    name="graphiti-async-loop"
                )
                _async_thread.start()
                # 等待循环启动
                while _async_loop is None:
                    import time
                    time.sleep(0.01)
                # 循环就绪后创建互斥锁（首次 acquire 发生在该循环线程上）
                global _episode_lock
                if _episode_lock is None:
                    _episode_lock = asyncio.Lock()


def _run_async(coro):
    """
    在同步上下文中运行异步协程

    使用专用后台线程的事件循环，通过 run_coroutine_threadsafe 提交任务。
    这样 Neo4j driver 始终绑定到同一个循环，避免跨循环问题。
    """
    _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _async_loop)
    return future.result(timeout=600)  # 10分钟超时（兼容网关慢响应+重试）


class DashScopeEmbedderWrapper:
    """
    DashScope 兼容的 Embedder 包装器

    DashScope API 有批次大小限制（max 10），graphiti-core 的 OpenAIEmbedder
    会将所有输入一次性发送。此包装器对请求进行分块处理。

    注意：此类动态继承 EmbedderClient 以满足 Pydantic 类型检查。
    """

    def __init__(self, embedder: Any, max_batch_size: int = 10):
        self._embedder = embedder
        self.max_batch_size = max_batch_size
        # 复制原 embedder 的属性以保持兼容性
        if hasattr(embedder, 'config'):
            self.config = embedder.config

    async def create(self, input_data) -> list[float]:
        """单条 embedding 请求（直接透传）"""
        return await self._embedder.create(input_data)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """批量 embedding 请求（分块处理）"""
        if len(input_data_list) <= self.max_batch_size:
            return await self._embedder.create_batch(input_data_list)

        # 分块处理
        results = []
        for i in range(0, len(input_data_list), self.max_batch_size):
            chunk = input_data_list[i : i + self.max_batch_size]
            chunk_results = await self._embedder.create_batch(chunk)
            results.extend(chunk_results)
        return results


def _create_dashscope_embedder_wrapper(base_embedder: Any, max_batch_size: int = 10) -> Any:
    """
    创建 DashScope 兼容的 Embedder 包装器

    动态继承 EmbedderClient 以满足 graphiti-core 的 Pydantic 类型检查。
    """
    try:
        from graphiti_core.embedder.client import EmbedderClient

        class _DashScopeEmbedderClient(EmbedderClient):
            """动态生成的 EmbedderClient 子类"""

            def __init__(self, embedder: Any, batch_size: int):
                self._embedder = embedder
                self.max_batch_size = batch_size
                if hasattr(embedder, 'config'):
                    self.config = embedder.config

            async def create(self, input_data) -> list[float]:
                return await self._embedder.create(input_data)

            async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
                if len(input_data_list) <= self.max_batch_size:
                    return await self._embedder.create_batch(input_data_list)

                results = []
                for i in range(0, len(input_data_list), self.max_batch_size):
                    chunk = input_data_list[i : i + self.max_batch_size]
                    chunk_results = await self._embedder.create_batch(chunk)
                    results.extend(chunk_results)
                return results

        return _DashScopeEmbedderClient(base_embedder, max_batch_size)

    except ImportError:
        # fallback: 返回普通包装器
        return DashScopeEmbedderWrapper(base_embedder, max_batch_size)


class GraphitiClient(ZepClientAdapter):
    """
    Graphiti 本地客户端实现

    使用 graphiti-core 库连接 Neo4j 图数据库。
    通过 group_id 参数实现多图谱隔离（对应 Miroworld 的 graph_id）。
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        llm_client: Optional[Any] = None,
        embedder: Optional[Any] = None,
    ):
        """
        初始化 Graphiti 客户端

        Args:
            neo4j_uri: Neo4j Bolt 连接 URI (如 bolt://localhost:7687)
            neo4j_user: Neo4j 用户名
            neo4j_password: Neo4j 密码
            llm_client: 可选的 LLM 客户端（用于实体抽取）
            embedder: 可选的 Embedder（用于语义搜索）
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self._llm_client = llm_client
        self._embedder = embedder

        # 延迟初始化 Graphiti 实例
        self._graphiti = None
        self._driver = None
        self._initialized = False

        # 记录创建的 graph_id（用于 group_id 映射）
        self._graph_metadata: Dict[str, Dict[str, Any]] = {}

        # 存储 ontology 定义（MVP 阶段仅记录，不强制执行）
        self._ontology_cache: Dict[str, Dict[str, Any]] = {}

    def _ensure_initialized(self):
        """确保 Graphiti 已初始化"""
        if self._initialized:
            return

        try:
            from graphiti_core import Graphiti

            # 应用 Neo4j 属性 sanitization patch (Issue #683 workaround)
            from .graphiti_patch import apply_patch
            apply_patch()

            llm_client = self._llm_client
            if llm_client is None:
                llm_client = self._build_default_llm_client()

            embedder = self._embedder
            if embedder is None:
                embedder = self._build_default_embedder()

            # 创建 Graphiti 实例
            self._graphiti = Graphiti(
                self.neo4j_uri,
                self.neo4j_user,
                self.neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
            )

            # 初始化索引和约束
            _run_async(self._graphiti.build_indices_and_constraints())

            # 获取底层 Neo4j driver 用于直接查询
            self._driver = self._graphiti.driver

            self._initialized = True
            logger.info("Graphiti 客户端初始化完成")

        except ImportError as e:
            raise ImportError(
                "graphiti-core 未安装。请运行: pip install graphiti-core"
            ) from e
        except Exception as e:
            logger.error(f"Graphiti 初始化失败: {e}")
            raise

    def _build_default_llm_client(self) -> Any:
        """
        构建 Graphiti 默认 LLM client（OpenAI-compatible）

        优先使用模型注册表中已验证的聊天模型（graphiti_llm 角色，或第一个
        已验证的 chat 模型），这样网页里配置的模型（如 OpenCode/百炼）直接生效；
        注册表不可用时回退到环境变量（GRAPHITI_LLM_MODEL / LLM_MODEL_NAME）。
        """
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

        # 1) 模型注册表优先（已验证的聊天模型 + 连接密钥）
        registry_entry = self._resolve_registry_chat_model()
        used_fallback = False
        if registry_entry is not None:
            api_key, base_url, model = registry_entry
            # 断路器：若当前注册表模型正被熔断，换用回退链（GRAPHITI_LLM →
            # PRIMARY → 第一个已验证 chat）中的下一个可用模型重建客户端。
            from .graphiti_patch import get_circuit_breaker, pick_fallback_model
            breaker = get_circuit_breaker()
            if breaker.is_open_for(model):
                alt = pick_fallback_model()
                if alt is not None:
                    api_key, base_url, model = alt
                    used_fallback = True
                    logger.warning(
                        "Detected model %s is circuit-broken, switch to fallback model %s (%s)",
                        registry_entry[2], model, base_url,
                    )
            if not used_fallback:
                logger.info("Graphiti LLM 使用模型注册表配置: %s (%s)", model, base_url)
        else:
            # 2) 回退到环境变量
            api_key = os.environ.get('OPENAI_API_KEY')
            base_url = os.environ.get('OPENAI_BASE_URL')
            model = os.environ.get('GRAPHITI_LLM_MODEL') or os.environ.get('LLM_MODEL_NAME')

        small_model = os.environ.get('GRAPHITI_LLM_SMALL_MODEL') or None
        temperature = float(os.environ.get('GRAPHITI_LLM_TEMPERATURE', '0') or '0')
        max_tokens = int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '8192') or '8192')

        config = LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            small_model=small_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # 显式传入不走系统代理的 http_client：
        # httpx 在 macOS 上会通过 urllib 自动读取系统代理（如 Clash 127.0.0.1:7890），
        # 代理对长连接偶发断开会导致图谱构建随机失败（RemoteProtocolError）。
        # 本地部署的 LLM 端点应直连；用户如需代理，可在 .env 显式设置 HTTP(S)_PROXY。
        try:
            import httpx
            from openai import AsyncOpenAI
            # timeout=300 + max_retries=0：OpenCode 等网关在负载高时可能
            # 长时间无响应（实测边提取等大提示词调用可耗时 90-240 秒）。
            # 45 秒超时会把"慢但正常"的调用误判为失败（边提取几乎必挂，
            # 导致图谱只有节点没有边）。统一由 graphiti_patch 的重试/降级
            # 逻辑处理错误，避免"超时 × 重试"叠加导致整体构建长时间卡死。
            http_client = httpx.AsyncClient(trust_env=False, timeout=300)
            return OpenAIGenericClient(config=config, client=AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
                max_retries=0,
            ))
        except Exception as exc:
            logger.warning(f"创建直连 http_client 失败，回退默认客户端: {exc}")
            return OpenAIGenericClient(config=config)

    @staticmethod
    def _resolve_registry_chat_model():
        """从模型注册表解析一个已验证的聊天模型，返回 (api_key, base_url, model)。

        优先 graphiti_llm 角色的绑定（若有项目级绑定则用项目绑定），
        否则使用第一个已验证的 chat 模型。注册表不可用或没有合适模型时返回 None。
        """
        try:
            from ..models.model_config import ModelRole, RoleBindings
            from .model_registry import ModelRegistryService

            registry = ModelRegistryService()
            state = registry.get_redacted_registry()
            models = state.get("models", [])
            chat_models = [
                m for m in models
                if m.get("verified") and "chat" in m.get("capabilities", [])
            ]
            if not chat_models:
                return None

            # 注意：GraphitiClient 是全局复用、不感知具体项目，因此**不能**遍历项目绑定
            # 来决定默认模型——否则会随机采用某个项目的绑定（例如 opencode），
            # 造成用户明明把项目绑到 SiliconFlow 却仍然走慢网关。
            # 这里只允许全局预设 graphiti_llm，否则用第一个已验证 chat 模型。
            chosen = None
            # 预设中的 graphiti_llm
            for preset in state.get("presets", []):
                roles = preset.get("roles") or {}
                graphiti_id = roles.get(ModelRole.GRAPHITI_LLM.value)
                if graphiti_id:
                    match = next((m for m in chat_models if m["id"] == graphiti_id), None)
                    if match:
                        chosen = match
                        break
            if chosen is None:
                chosen = chat_models[0]

            connection_id = chosen.get("connection_id")
            if not connection_id:
                return None
            api_key = registry.resolve_connection_secret(connection_id)
            connection = registry.get_connection(connection_id)
            return api_key, connection.get("endpoint"), chosen.get("model_id")
        except Exception as exc:
            logger.warning("从模型注册表解析 Graphiti LLM 失败，回退环境变量: %s", exc)
            return None

    def _build_default_embedder(self) -> Any:
        """
        构建 Graphiti 默认 Embedder（OpenAI-compatible /embeddings）

        默认 embedding model 是 `text-embedding-3-small`（OpenAI），DashScope 下需要显式配置：
        - GRAPHITI_EMBEDDING_MODEL=text-embedding-v4

        注意：DashScope API 有批次大小限制（max 10），使用 DashScopeEmbedderWrapper 处理。

        如果模型库中注册了已验证的本地向量模型（app/models/embeddings/ 下的
        Sentence Transformers 目录），优先使用本地模型，注册即生效。
        """
        # 向量模型提供方偏好（cloud / local / auto）
        try:
            from .embedding_resolver import get_embedding_preference
            preference = get_embedding_preference()
        except Exception:
            preference = "auto"

        # cloud 偏好：只用云端；auto：云端优先 → 本地；local：只用本地
        if preference != "local":
            cloud_embedder = self._try_build_registry_cloud_embedder()
            if cloud_embedder is not None:
                return cloud_embedder
            if preference == "cloud":
                logger.warning("向量模型偏好为 cloud 但云端不可用，无本地回退")
                return None

        if preference != "cloud":
            local_embedder = self._try_build_local_embedder()
            if local_embedder is not None:
                return local_embedder

        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        api_key = os.environ.get('OPENAI_API_KEY')
        base_url = os.environ.get('OPENAI_BASE_URL')
        embedding_model = os.environ.get('GRAPHITI_EMBEDDING_MODEL')

        if embedding_model:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
                embedding_model=embedding_model,
            )
        else:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
            )

        # 同样显式直连（避免 macOS 系统代理导致偶发断连）
        try:
            import httpx
            from openai import AsyncOpenAI
            http_client = httpx.AsyncClient(trust_env=False, timeout=300)
            base_embedder = OpenAIEmbedder(
                config=config,
                client=AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                ),
            )
        except Exception as exc:
            logger.warning(f"创建 embedder 直连 http_client 失败，回退默认: {exc}")
            base_embedder = OpenAIEmbedder(config=config)

        # DashScope API 有批次大小限制，需要包装
        if self._is_openai_compatible_only():
            logger.info("检测到非标准 OpenAI API，启用 DashScope Embedder 分块处理")
            return _create_dashscope_embedder_wrapper(base_embedder, max_batch_size=10)

        return base_embedder

    @staticmethod
    def _wrap_as_embedder_client(embedder: Any, dimension: Optional[int]) -> Any:
        """把本地向量模型包装为 graphiti-core 的 EmbedderClient 子类。

        Graphiti 的 GraphitiClients 用 Pydantic 做 is_instance_of(EmbedderClient)
        校验，普通对象无法通过；这里动态生成子类（与 DashScope 包装器同模式）。
        """
        try:
            from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig
        except ImportError:
            # graphiti 未安装时原样返回
            return embedder

        class _LocalEmbedderClient(EmbedderClient):
            def __init__(self, inner: Any, embedding_dim: Optional[int]):
                self._inner = inner
                self.config = EmbedderConfig(embedding_dim=embedding_dim or 1024)

            async def create(self, input_data) -> list[float]:
                return await self._inner.create(input_data)

            async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
                return await self._inner.create_batch(input_data_list)

        return _LocalEmbedderClient(embedder, dimension)

    @staticmethod
    def _try_build_registry_cloud_embedder() -> Any:
        """从模型注册表查找已验证的云端向量模型（无 local_path，如 SiliconFlow）并构建 Embedder。

        与本地模型（local_path 非空）互斥：本地模型走 _try_build_local_embedder。
        返回 None 表示没有可用的云端向量模型。
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
                    continue  # 本地模型不属于云端路径
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
                logger.info("使用云端向量模型: %s (%s, dim=%s)", model_id, endpoint, dimension)
                embedder = CloudOpenAIEmbedder(
                    endpoint=endpoint, api_key=api_key, model=model_id, dimension=dimension,
                )
                return GraphitiClient._wrap_as_embedder_client(embedder, dimension)
        except Exception as exc:
            logger.warning("云端向量模型不可用: %s", exc)
        return None

    @staticmethod
    def _try_build_local_embedder() -> Any:
        """从模型注册表查找已验证的本地向量模型并构建 Embedder。"""
        try:
            from .local_embedding import LOCAL_MODELS_ROOT, LocalSentenceTransformerEmbedder
            from .model_registry import ModelRegistryService

            registry = ModelRegistryService()
            for entry in registry.get_redacted_registry().get("models", []):
                if not entry.get("verified"):
                    continue
                if "embedding" not in entry.get("capabilities", []):
                    continue
                local_path = entry.get("local_path")
                if not local_path:
                    continue
                model_dir = LOCAL_MODELS_ROOT / local_path
                if not model_dir.is_dir():
                    logger.warning("本地向量模型目录不存在: %s", model_dir)
                    continue
                dimension = entry.get("metadata", {}).get("dimension")
                logger.info("使用本地向量模型: %s (dim=%s)", local_path, dimension)
                embedder = LocalSentenceTransformerEmbedder(
                    str(model_dir), dimension=dimension
                )
                return GraphitiClient._wrap_as_embedder_client(embedder, dimension)
        except Exception as exc:
            logger.warning("本地向量模型不可用，回退到云端 Embedding: %s", exc)
        return None

    # ==================== Graph 操作 ====================

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        """
        创建图谱（在 Graphiti 中通过 group_id 隔离）

        Graphiti 没有显式的图谱创建 API，数据通过 group_id 自动隔离。
        这里仅记录元数据，实际数据在 add_episode 时创建。
        """
        self._graph_metadata[graph_id] = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"图谱元数据已记录: graph_id={graph_id}, name={name}")

    def delete_graph(self, graph_id: str) -> None:
        """
        删除图谱（删除 group_id 相关的所有数据）

        使用 Cypher 直接删除 Neo4j 中 group_id 匹配的所有节点和边。
        Graphiti 的所有节点（Entity、Episodic 等）都带 group_id 属性，
        一个通用查询即可覆盖。
        """
        self._ensure_initialized()

        async def _delete():
            # 删除所有带有此 group_id 的节点（级联删除边）
            # Graphiti 的 Entity 和 Episodic 节点都带 group_id，无需分别删除
            result = await self._driver.execute_query(
                """
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                RETURN count(n) as deleted_count
                """,
                group_id=graph_id,
            )
            records = result.records if hasattr(result, 'records') else result[0]
            deleted = records[0]['deleted_count'] if records else 0
            logger.debug(f"删除了 {deleted} 个节点 (group_id={graph_id})")

        _run_async(_delete())

        # 清理本地缓存
        self._graph_metadata.pop(graph_id, None)
        self._ontology_cache.pop(graph_id, None)
        logger.info(f"图谱已删除: graph_id={graph_id}")

    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        设置图谱本体

        MVP 说明：Graphiti 不支持与 Zep Cloud 完全相同的 ontology API。
        这里仅缓存定义，可用于：
        1. 添加 episode 时作为 prompt 提示
        2. 后续对齐时做类型映射

        Full parity 阶段可实现：
        - 动态生成 Pydantic Entity/Edge 模型传递给 add_episode
        - 在 Neo4j 中创建类型约束
        """
        for graph_id in graph_ids:
            self._ontology_cache[graph_id] = {
                "entities": entities or {},
                "edges": edges or {},
            }
            logger.info(
                f"Ontology 已缓存 (MVP no-op): graph_id={graph_id}, "
                f"entity_types={len(entities or {})}, edge_types={len(edges or {})}"
            )

    # ==================== Episode 操作 ====================

    def _build_graphiti_type_models(self, graph_id: str):
        """把缓存的本体转换为 graphiti 的 entity_types/edge_types 模型字典。

        模型名使用本体中的原始名称（支持中文，如 学生/大学），
        描述写入模型 __doc__（graphiti 抽取提示会展示），
        属性来自本体 attributes（英文 snake_case，已避开保留字段）。

        注意：LLM 生成的本体可能给实体类型定义与图谱节点字段同名的属性
        （如 name/uuid/created_at），graphiti 的 validate_entity_types 会
        直接抛 EntityTypeValidationError 导致整个 episode 失败。这里将
        冲突属性重命名为 entity_<原名> 保留数据。
        """
        from pydantic import BaseModel, Field
        from graphiti_core.nodes import EntityNode

        # 图谱节点保留字段（EntityNode.model_fields），冲突即重命名
        protected_field_names = set(EntityNode.model_fields.keys())

        ontology = self._ontology_cache.get(graph_id) or {}
        entity_types: Dict[str, Any] = {}
        edge_types: Dict[str, Any] = {}

        for item in ontology.get("entities") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            annotations: Dict[str, Any] = {}
            field_defs: Dict[str, Any] = {}
            for attr in item.get("attributes") or []:
                attr_name = str(attr.get("name") or "").strip()
                if not attr_name or attr_name.startswith('__'):
                    continue
                if attr_name in protected_field_names:
                    safe_name = f"entity_{attr_name}"
                    logger.warning(
                        f"实体类型 {name} 的属性 {attr_name!r} 与图谱节点字段冲突，"
                        f"已重命名为 {safe_name}"
                    )
                    attr_name = safe_name
                annotations[attr_name] = str
                field_defs[attr_name] = Field(
                    description=str(attr.get("description") or ""),
                    default=None,
                )
            entity_types[name] = type(
                name,
                (BaseModel,),
                {
                    "__doc__": str(item.get("description") or ""),
                    "__annotations__": annotations,
                    **field_defs,
                },
            )

        for item in ontology.get("edges") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            edge_types[name] = type(
                name, (BaseModel,), {"__doc__": str(item.get("description") or "")}
            )

        return entity_types, edge_types

    def _build_source_type(self, episode_type: str):
        """映射 episode_type 到 graphiti EpisodeType。"""
        from graphiti_core.nodes import EpisodeType
        if episode_type == "message":
            return EpisodeType.message
        if episode_type == "json":
            return EpisodeType.json
        return EpisodeType.text

    async def _add_episode_coro(
        self, graph_id: str, data: str, source_type, entity_types, edge_types
    ) -> str:
        """真实 episode 提交协程（在专用事件循环线程上运行）。"""
        result = await self._graphiti.add_episode(
            name=f"episode_{graph_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            episode_body=data,
            source=source_type,
            source_description="mirofish_simulation",
            reference_time=datetime.now(timezone.utc),
            group_id=graph_id,
            entity_types=entity_types or None,
            edge_types=edge_types or None,
        )
        return result.episode.uuid if result and result.episode else ""

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        """添加单条 episode（与补边重放共用 _episode_lock 互斥）。"""
        self._ensure_initialized()
        source_type = self._build_source_type(episode_type)
        entity_types, edge_types = self._build_graphiti_type_models(graph_id)

        async def _guarded():
            async with _episode_lock:
                return await self._add_episode_coro(
                    graph_id, data, source_type, entity_types, edge_types)

        return _run_async(_guarded())

    def add_episode_for_edge_refill(
        self,
        graph_id: str,
        data: str,
        edge_mode: str = "always",
        max_nodes: int = 4,
    ) -> str:
        """
        补边专用重放：持锁状态下在事件循环线程内临时切换边提取环境。

        - 与 add_episode 共用 _episode_lock：并发建图 episode 不会在补边
          窗口内读到 always 模式，反之亦然。
        - 环境改写/恢复都在事件循环线程内逐条完成，不泄漏到调用方线程。
        """
        self._ensure_initialized()
        source_type = self._build_source_type("text")
        entity_types, edge_types = self._build_graphiti_type_models(graph_id)

        from ..config import Config

        async def _refill():
            from graphiti_core.utils.maintenance import edge_operations
            prev_mode = Config.GRAPHITI_EDGE_MODE
            prev_max = getattr(edge_operations, 'MAX_NODES', None)
            async with _episode_lock:
                try:
                    Config.GRAPHITI_EDGE_MODE = edge_mode
                    edge_operations.MAX_NODES = max_nodes
                    return await self._add_episode_coro(
                        graph_id, data, source_type, entity_types, edge_types)
                finally:
                    Config.GRAPHITI_EDGE_MODE = prev_mode
                    if prev_max is not None:
                        edge_operations.MAX_NODES = prev_max

        return _run_async(_refill())

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        max_workers: int = 1
    ) -> List[str]:
        """
        批量添加 episode。

        注意：graphiti 的 add_episode_bulk 会以 SEMAPHORE_LIMIT（默认 20）并发
        调用 LLM（实体提取、关系提取、去重、摘要等多个阶段）。部分网关
        （如 OpenCode / DeepSeek 兼容端点）在并发请求下会返回空内容或断开连接，
        导致整个批次失败。这里默认逐条串行调用 add_episode——单条流程内
        graphiti 本身是顺序的，稳定得多；max_workers 可调到 2-3 换取吞吐
        （仅在网关承受得起并发时使用）。批次数量不大时耗时差异可接受。

        每条处理完成会调用 progress_callback(done, total, msg)（若提供）。
        """
        self._ensure_initialized()

        total = len(episodes)
        if total == 0:
            if progress_callback:
                progress_callback(0, 0, "空批次，无需处理")
            return []

        def _process_one(i: int) -> Optional[str]:
            ep = episodes[i]
            ep_type = ep.get("type", "text")
            data = ep.get("data", "")
            try:
                uuid = self.add_episode(
                    graph_id=graph_id, data=data, episode_type=ep_type,
                )
                if uuid:
                    return uuid
                logger.warning(f"episode {i} 返回空 uuid（可能是空内容），跳过")
            except Exception as e:
                import time as _time
                from .llm_error_normalizer import normalize_llm_error
                logger.warning(
                    f"episode {i} 添加失败（{normalize_llm_error(e)[:160]}），重试 1 次..."
                )
                _time.sleep(0.5)
                try:
                    uuid = self.add_episode(
                        graph_id=graph_id, data=data, episode_type=ep_type,
                    )
                    if uuid:
                        logger.info(f"episode {i} 重试成功")
                        return uuid
                    logger.warning(f"episode {i} 重试后仍返回空 uuid，跳过")
                except Exception as e2:
                    logger.error(f"episode {i} 重试仍失败: {e2}，继续处理剩余批次")
            return None

        episode_uuids: List[str] = []
        failed = 0
        done = 0

        if max_workers and max_workers > 1:
            # 并发处理（默认关：串行最稳，OpenCode 网关并发易空响应）
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for i, result in enumerate(pool.map(_process_one, range(total))):
                    if result:
                        episode_uuids.append(result)
                    else:
                        failed += 1
                    done += 1
                    if progress_callback:
                        progress_callback(done, total, f"episode {done}/{total}")
        else:
            for i in range(total):
                result = _process_one(i)
                if result:
                    episode_uuids.append(result)
                else:
                    failed += 1
                done += 1
                if progress_callback:
                    progress_callback(done, total, f"episode {done}/{total}")

        if failed:
            logger.warning(
                f"批次完成: 成功 {len(episode_uuids)}/{len(episodes)}，失败 {failed}"
            )
        return episode_uuids

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        """
        获取 episode 处理状态

        Graphiti 同步处理 episode，添加完成即为已处理。
        """
        return EpisodeStatus(uuid=episode_uuid, processed=True)

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        """
        等待 episode 处理完成

        Graphiti 同步处理，直接返回 True。
        """
        return True

    # ==================== Node 操作 ====================

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        """获取图谱所有节点"""
        self._ensure_initialized()

        async def _get_nodes():
            # 尝试多种 label 模式，提高 schema 兼容性
            # Graphiti 标准使用 :Entity，但也可能有其他 label
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})
                    RETURN
                        n.uuid AS uuid,
                        n.name AS name,
                        labels(n) AS labels,
                        n.summary AS summary,
                        properties(n) AS props,
                        n.created_at AS created_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            # 所有 label 都没找到，记录警告并返回空
            logger.warning(
                f"get_all_nodes: 未找到 group_id={graph_id} 的节点。"
                f"可能的原因：1) 图谱为空 2) Graphiti schema 不匹配（尝试过 Entity, EntityNode）"
            )
            return []

        records = _run_async(_get_nodes())
        nodes = []
        for record in records:
            props = record.get("props", {})
            # 过滤掉已单独提取的属性
            attributes = {
                k: v for k, v in props.items()
                if k not in ["uuid", "name", "summary", "created_at", "group_id"]
            }
            created_at = record.get("created_at")
            if hasattr(created_at, 'to_native'):
                created_at = created_at.to_native().isoformat()
            elif created_at:
                created_at = str(created_at)

            nodes.append(GraphNode(
                uuid=record.get("uuid", ""),
                name=record.get("name", ""),
                labels=record.get("labels", ["Entity"]),
                summary=record.get("summary", ""),
                attributes=attributes,
                created_at=created_at,
            ))
        return nodes

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        """获取单个节点"""
        self._ensure_initialized()

        async def _get_node():
            # 按 uuid 查找节点，不限定 label（更灵活）
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})
                RETURN
                    n.uuid AS uuid,
                    n.name AS name,
                    labels(n) AS labels,
                    n.summary AS summary,
                    properties(n) AS props,
                    n.created_at AS created_at
                LIMIT 1
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_node())
        if not records:
            logger.debug(f"get_node: 未找到 uuid={node_uuid} 的节点")
            return None

        record = records[0]
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "name", "summary", "created_at", "group_id"]
        }
        created_at = record.get("created_at")
        if hasattr(created_at, 'to_native'):
            created_at = created_at.to_native().isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            labels=record.get("labels", ["Entity"]),
            summary=record.get("summary", ""),
            attributes=attributes,
            created_at=created_at,
        )

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        """获取节点的所有相关边（双向）"""
        self._ensure_initialized()

        async def _get_edges():
            # 不限定节点 label，按 uuid 匹配，获取双向边
            # 优先用 r.name（实际关系名），fallback 到 type(r)（关系类型）
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})-[r]-(m)
                RETURN DISTINCT
                    r.uuid AS uuid,
                    COALESCE(r.name, type(r)) AS name,
                    r.fact AS fact,
                    startNode(r).uuid AS source_uuid,
                    endNode(r).uuid AS target_uuid,
                    properties(r) AS props,
                    r.created_at AS created_at,
                    r.valid_at AS valid_at,
                    r.invalid_at AS invalid_at,
                    r.expired_at AS expired_at
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_edges())
        if not records:
            logger.debug(f"get_node_edges: 节点 uuid={node_uuid} 没有关联的边")
        return [self._record_to_edge(record) for record in records]

    # ==================== Edge 操作 ====================

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        """获取图谱所有边（通过节点的 group_id 过滤）"""
        self._ensure_initialized()

        async def _get_edges():
            # 通过节点的 group_id 过滤边，使用 DISTINCT 避免重复
            # 注意：边本身可能没有 group_id，所以通过连接的节点过滤
            # 优先用 r.name（实际关系名），fallback 到 type(r)（关系类型）
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})-[r]-(m:{label})
                    WHERE n.group_id = m.group_id
                    RETURN DISTINCT
                        r.uuid AS uuid,
                        COALESCE(r.name, type(r)) AS name,
                        r.fact AS fact,
                        startNode(r).uuid AS source_uuid,
                        endNode(r).uuid AS target_uuid,
                        properties(r) AS props,
                        r.created_at AS created_at,
                        r.valid_at AS valid_at,
                        r.invalid_at AS invalid_at,
                        r.expired_at AS expired_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            logger.warning(
                f"get_all_edges: 未找到 group_id={graph_id} 的边。"
                f"可能的原因：1) 图谱无边 2) Graphiti schema 不匹配"
            )
            return []

        records = _run_async(_get_edges())
        return [self._record_to_edge(record) for record in records]

    # ==================== Search 操作 ====================

    def _is_openai_compatible_only(self) -> bool:
        """
        检测是否使用非标准 OpenAI API（如 DashScope、Azure 等）

        这些 API 可能不支持 cross_encoder 需要的 logprobs 功能，
        需要 fallback 到 RRF 重排序。

        可通过 GRAPHITI_FORCE_CROSS_ENCODER=true 强制使用 cross_encoder
        （适用于确认支持 logprobs 的兼容服务）。
        """
        import os

        # 显式覆盖：强制使用 cross_encoder
        if os.environ.get('GRAPHITI_FORCE_CROSS_ENCODER', '').lower() in ('true', '1', 'yes'):
            return False

        base_url = os.environ.get('OPENAI_BASE_URL', '')
        # 标准 OpenAI API
        if not base_url or 'api.openai.com' in base_url:
            return False
        # 非标准 API（DashScope、Azure、本地部署等）
        non_standard_indicators = [
            'dashscope', 'aliyun', 'azure', 'localhost',
            'ollama', 'vllm', 'lmstudio', 'openrouter'
        ]
        return any(indicator in base_url.lower() for indicator in non_standard_indicators)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "rrf"  # 默认改为 rrf，更安全
    ) -> SearchResult:
        """
        图谱混合搜索

        使用 Graphiti 公开的 search_() API（带 config）进行搜索。
        如果 search_() 不可用，fallback 到简单的 search() API。

        注意：reranker="cross_encoder" 需要 OpenAI API 支持 logprobs，
        非标准 API（如 DashScope）会自动降级为 rrf。
        """
        self._ensure_initialized()

        # 非标准 OpenAI API 不支持 cross_encoder，强制使用 rrf
        if reranker == "cross_encoder" and self._is_openai_compatible_only():
            logger.info("检测到非标准 OpenAI API，cross_encoder 降级为 rrf")
            reranker = "rrf"

        from graphiti_core.search.search_config_recipes import (
            NODE_HYBRID_SEARCH_RRF,
            EDGE_HYBRID_SEARCH_RRF,
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
        )

        async def _do_search():
            nodes = []
            edges = []

            # 检查是否有 search_() 方法（公开的高级搜索 API）
            has_search_method = hasattr(self._graphiti, 'search_')

            if not has_search_method:
                # Fallback: 使用简单的 search() API
                logger.info("使用 graphiti.search() 简单 API（search_() 不可用）")
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    # 简单 search 主要返回边
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                    return nodes, edges
                except Exception as e:
                    logger.warning(f"graphiti.search() 失败: {e}，返回空结果")
                    return [], []

            # 使用 search_() 高级 API
            try:
                if scope == "nodes":
                    config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'nodes'):
                        nodes = result.nodes or []

                elif scope == "edges":
                    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'edges'):
                        edges = result.edges or []

                else:  # both
                    if reranker == "cross_encoder":
                        config = COMBINED_HYBRID_SEARCH_CROSS_ENCODER.model_copy(deep=True)
                        config.limit = limit
                        result = await self._graphiti.search_(
                            query=query,
                            config=config,
                            group_ids=[graph_id],
                        )
                        if result:
                            nodes = result.nodes or [] if hasattr(result, 'nodes') else []
                            edges = result.edges or [] if hasattr(result, 'edges') else []
                    else:
                        # 分别搜索 nodes 和 edges
                        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        node_config.limit = limit // 2
                        edge_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        edge_config.limit = limit // 2

                        node_result = await self._graphiti.search_(
                            query=query, config=node_config, group_ids=[graph_id]
                        )
                        edge_result = await self._graphiti.search_(
                            query=query, config=edge_config, group_ids=[graph_id]
                        )

                        if node_result and hasattr(node_result, 'nodes'):
                            nodes = node_result.nodes or []
                        if edge_result and hasattr(edge_result, 'edges'):
                            edges = edge_result.edges or []

            except Exception as e:
                logger.warning(f"graphiti.search_() 失败: {e}，尝试 fallback")
                # Fallback 到简单搜索
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                except Exception as fallback_e:
                    logger.error(f"search fallback 也失败: {fallback_e}")

            return nodes, edges

        raw_nodes, raw_edges = _run_async(_do_search())

        if not raw_nodes and not raw_edges:
            logger.debug(f"search: query='{query}' group_id={graph_id} 无结果")

        # 转换为适配器数据结构
        nodes = [self._graphiti_node_to_graph_node(n) for n in raw_nodes]
        edges = [self._graphiti_edge_to_graph_edge(e) for e in raw_edges]

        return SearchResult(nodes=nodes, edges=edges)

    # ==================== 转换辅助方法 ====================

    def _record_to_edge(self, record: Dict[str, Any]) -> GraphEdge:
        """将 Neo4j 查询结果转换为 GraphEdge"""
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "fact", "created_at", "valid_at", "invalid_at", "expired_at", "group_id"]
        }

        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'to_native'):
                return t.to_native().isoformat()
            return str(t)

        return GraphEdge(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            fact=record.get("fact", ""),
            source_node_uuid=record.get("source_uuid", ""),
            target_node_uuid=record.get("target_uuid", ""),
            attributes=attributes,
            created_at=_format_time(record.get("created_at")),
            valid_at=_format_time(record.get("valid_at")),
            invalid_at=_format_time(record.get("invalid_at")),
            expired_at=_format_time(record.get("expired_at")),
            episodes=[],  # Graphiti 边可能没有 episodes 字段
            fact_type=record.get("name", ""),
        )

    def _graphiti_node_to_graph_node(self, node: Any) -> GraphNode:
        """将 Graphiti 节点对象转换为 GraphNode"""
        created_at = getattr(node, 'created_at', None)
        if hasattr(created_at, 'isoformat'):
            created_at = created_at.isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=getattr(node, 'uuid', ''),
            name=getattr(node, 'name', ''),
            labels=getattr(node, 'labels', ['Entity']),
            summary=getattr(node, 'summary', ''),
            attributes=getattr(node, 'attributes', {}),
            created_at=created_at,
        )

    def _graphiti_edge_to_graph_edge(self, edge: Any) -> GraphEdge:
        """将 Graphiti 边对象转换为 GraphEdge"""
        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'isoformat'):
                return t.isoformat()
            return str(t)

        return GraphEdge(
            uuid=getattr(edge, 'uuid', ''),
            name=getattr(edge, 'name', '') or getattr(edge, 'fact_type', ''),
            fact=getattr(edge, 'fact', ''),
            source_node_uuid=getattr(edge, 'source_node_uuid', ''),
            target_node_uuid=getattr(edge, 'target_node_uuid', ''),
            attributes=getattr(edge, 'attributes', {}),
            created_at=_format_time(getattr(edge, 'created_at', None)),
            valid_at=_format_time(getattr(edge, 'valid_at', None)),
            invalid_at=_format_time(getattr(edge, 'invalid_at', None)),
            expired_at=_format_time(getattr(edge, 'expired_at', None)),
            episodes=getattr(edge, 'episodes', []),
            fact_type=getattr(edge, 'fact_type', '') or getattr(edge, 'name', ''),
        )

    def close(self):
        """关闭连接"""
        if self._graphiti:
            _run_async(self._graphiti.close())
            self._initialized = False
            logger.info("Graphiti 连接已关闭")

    def __del__(self):
        """析构时关闭连接"""
        try:
            self.close()
        except Exception:
            pass
