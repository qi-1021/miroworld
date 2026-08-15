"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv


def _sanitize_env_var(key: str) -> None:
    value = os.environ.get(key)
    if value is None:
        return

    cleaned = value.strip()
    if "\n" in cleaned:
        cleaned = cleaned.splitlines()[0].strip()

    if cleaned.startswith("export ") and "=" in cleaned:
        cleaned = cleaned.split("=", 1)[1].strip()

    os.environ[key] = cleaned

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)

# 防御式清洗：避免 shell 误配置把多行 export 内容拼进值里
for env_key in [
    'LLM_API_KEY',
    'LLM_BASE_URL',
    'LLM_MODEL_NAME',
    'OPENAI_API_KEY',
    'OPENAI_BASE_URL',
]:
    _sanitize_env_var(env_key)

# Graphiti 需要 OPENAI_* 环境变量，从 LLM_* 映射
# 仅在未显式设置时才映射，避免覆盖用户的显式配置
if not os.environ.get('OPENAI_API_KEY') and os.environ.get('LLM_API_KEY'):
    os.environ['OPENAI_API_KEY'] = os.environ['LLM_API_KEY']
if not os.environ.get('OPENAI_BASE_URL') and os.environ.get('LLM_BASE_URL'):
    os.environ['OPENAI_BASE_URL'] = os.environ['LLM_BASE_URL']


class Config:
    """Flask配置类"""

    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False

    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    ZEP_BACKEND = os.environ.get('ZEP_BACKEND', 'cloud')  # 'cloud' | 'graphiti'

    # Graphiti / Neo4j 配置（本地部署时使用）
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')

    # Graphiti 边提取模式：
    # - 'skip'（默认）：建图阶段完全跳过边提取。实测 OpenCode 网关对 10+ 实体的
    #   边提取 0% 成功、每次烧 2×100s+，全跳过是净收益；边由"补边队列"
    #   （POST /api/world/<pid>/graph/refill_edges）后续补充。
    # - 'skip-first'：仅首个 episode 跳过（历史遗留选项，保留兼容）。
    # - 'always'：graphiti 原生行为。补边重放时由 GraphitiClient 在事件循环
    #   线程内临时切换使用，不通过本环境变量修改。
    GRAPHITI_EDGE_MODE = os.environ.get('GRAPHITI_EDGE_MODE', 'skip')
    # graphiti 建图 LLM 并发上限：1=串行（最稳）；2-3=并发处理短小的
    # 属性/摘要调用（边提取已跳过，网关压力大减）。env 可覆盖。
    GRAPHITI_MAX_CONCURRENCY = int(os.environ.get('GRAPHITI_MAX_CONCURRENCY', '1') or '1')

    # Graphiti LLM 断路器配置（仅 graphiti 建图路径生效，不碰 LLMClient）
    # 连续失败达到阈值则熔断该模型，熔断窗口内换用回退链中的下一个模型。
    # 默认阈值较高，平时零感知；用 0 关闭断路器。
    GRAPHITI_CIRCUIT_BREAKER_THRESHOLD = int(
        os.environ.get('GRAPHITI_CIRCUIT_BREAKER_THRESHOLD', '5')
    )
    GRAPHITI_CIRCUIT_BREAKER_SECONDS = int(
        os.environ.get('GRAPHITI_CIRCUIT_BREAKER_SECONDS', '120')
    )

    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # 文本处理配置
    # 说明：500 字符/块 会导致长文档拆出大量 episode，每个 episode 要串行
    # 打多次 LLM（实体提取/消歧/关系/摘要），建图时间随块数线性膨胀。
    # 提高默认块大小可减少 3 倍 episode 数；graphiti 对高密度内容会内部再切分。
    DEFAULT_CHUNK_SIZE = 1500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 150  # 默认重叠大小

    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        # 根据后端类型验证配置
        if cls.ZEP_BACKEND == 'cloud':
            if not cls.ZEP_API_KEY:
                errors.append("ZEP_API_KEY 未配置（ZEP_BACKEND=cloud 时必需）")
        elif cls.ZEP_BACKEND == 'graphiti':
            if not all([cls.NEO4J_URI, cls.NEO4J_USER, cls.NEO4J_PASSWORD]):
                errors.append("Neo4j 配置不完整（ZEP_BACKEND=graphiti 时必需）")
        return errors

