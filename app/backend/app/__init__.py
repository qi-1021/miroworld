"""
Miroworld Backend - Flask应用工厂
"""

import gzip
import json
import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger

# 请求/响应体中可能携带密钥的字段名（大小写不敏感，匹配即打码）
_SENSITIVE_KEYS = {
    "api_key", "api_keys", "secret", "token",
    "password", "authorization", "bearer",
}


def _redact_secrets(data):
    """递归遍历 dict/list，把敏感字段的值替换为 [REDACTED]，防止密钥进入日志。

    保留整体结构与其余字段，便于调试时仍能看清请求/响应内容。
    """
    if isinstance(data, dict):
        return {
            key: ("[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS
                  else _redact_secrets(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact_secrets(item) for item in data]
    return data


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # 设置日志
    logger = setup_logger('mirofish')

    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("Miroworld Backend 启动中...")
        logger.info("=" * 50)

    # 启用CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")

    # 启动恢复：重启前中断的图谱构建任务（进程内 TaskManager 已丢）标记为失败，
    # 避免项目永久卡在 graph_building 无法重建。测试环境跳过（避免动真实数据目录）。
    if should_log_startup and not app.config.get("TESTING"):
        try:
            from .models.project import ProjectManager
            recovered = ProjectManager.recover_interrupted_projects()
            if recovered:
                logger.info(f"启动恢复：已重置 {recovered} 个中断的图谱构建项目")
        except Exception as e:
            logger.warning(f"启动恢复扫描失败（忽略）: {e}")

        # 启动时顺带清理过旧的时间线任务状态文件，防止长期运行无限增长
        try:
            from .services.timeline_service import prune_old_task_files
            removed = prune_old_task_files()
            if removed:
                logger.info(f"启动清理：已删除 {removed} 个过期时间线任务状态文件")
        except Exception as e:
            logger.warning(f"启动任务文件清理失败（忽略）: {e}")

        # 通用任务管理器（图谱/报告等）启用磁盘持久化并恢复中断任务
        try:
            from .models.task import TaskManager
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
            )
            TaskManager.PERSIST_DIR = os.path.join(data_dir, "task-manager")
            restored = TaskManager().load_persisted()
            if restored:
                logger.info(f"启动恢复：已恢复 {restored} 个通用任务（中断任务标记为 failed）")
        except Exception as e:
            logger.warning(f"通用任务持久化初始化失败（忽略）: {e}")

    # 请求日志中间件（敏感字段打码后再记录，避免密钥进入日志并被错误报告收集）
    #
    # 高频轮询端点不写请求/响应日志：前端每 1~2 秒轮询一次任务状态与健康检查，
    # 实测这些请求占单日日志行数的 60%，会把日志撑到 8MB+ 并连带撑大错误报告。
    # 需要完整抓包排查时，设 MIROWORLD_LOG_VERBOSE_POLL=1 即可恢复记录。
    _POLL_PATH_MARKERS = (
        '/health',
        '/task/',
        '/status',
        '/api/timeline/status',
        '/api/graph/status',
    )
    _log_poll = (os.environ.get('MIROWORLD_LOG_VERBOSE_POLL') or '').strip() in ('1', 'true', 'True')
    # 请求/响应体最长记录字符数，避免单条巨型 JSON 刷爆日志
    _BODY_LOG_LIMIT = 2000

    def _is_poll_request() -> bool:
        if _log_poll:
            return False
        path = request.path or ''
        return any(marker in path for marker in _POLL_PATH_MARKERS)

    def _clip(payload) -> str:
        """把任意结构转成字符串并限长，避免单条巨型 JSON 刷爆日志。"""
        s = str(payload)
        if len(s) <= _BODY_LOG_LIMIT:
            return s
        return f"{s[:_BODY_LOG_LIMIT]}...(已截断，原长度 {len(s)} 字符)"

    @app.before_request
    def log_request():
        if _is_poll_request():
            return
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {_clip(_redact_secrets(request.get_json(silent=True)))}")

    @app.after_request
    def log_response(response):
        if _is_poll_request():
            return response
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        # 响应体同样打码后再记录；已 gzip 压缩的先解压再解析，失败则跳过（不影响主流程）
        try:
            body = None
            if not response.is_streamed:
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(response.get_data())
                    body = json.loads(raw.decode("utf-8"))
                else:
                    body = response.get_json(silent=True)
            if body is not None:
                logger.debug(f"响应体: {_clip(_redact_secrets(body))}")
        except Exception:
            pass
        return response

    # 注册蓝图
    from .api import (graph_bp, simulation_bp, report_bp, models_bp, world_bp,
                      timeline_bp, assistant_bp, support_bp)
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(models_bp, url_prefix='/api/models')
    app.register_blueprint(world_bp, url_prefix='/api/world')
    app.register_blueprint(timeline_bp, url_prefix='/api/timeline')
    app.register_blueprint(assistant_bp, url_prefix='/api/assistant')
    app.register_blueprint(support_bp, url_prefix='/api/support')

    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'Miroworld Backend'}

    @app.route('/api/health')
    def api_health():
        """兼容 /api/health 别名，方便 CLI/Agent 统一使用。"""
        return {'status': 'ok', 'service': 'Miroworld Backend'}

    @app.route('/api/health/detailed')
    def detailed_health():
        """详细健康检查：Neo4j 端口、模型注册表、数据目录可写性。

        任何单项失败都不会让端点 500，而是把该项标记为 unavailable/error，
        便于运维和 smoke 脚本快速定位。
        """
        import socket
        from datetime import datetime

        checks = {
            "status": "ok",
            "service": "Miroworld Backend",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        # 1) Neo4j Bolt 端口连通性（127.0.0.1:7687）
        try:
            sock = socket.create_connection(("127.0.0.1", 7687), timeout=1)
            sock.close()
            checks["neo4j"] = "ok"
        except Exception:
            checks["neo4j"] = "unavailable"

        # 2) 模型注册表
        try:
            from .services.model_registry import ModelRegistryService
            registry = ModelRegistryService().get_redacted_registry()
            checks["models"] = {
                "verified": sum(
                    1 for m in registry.get("models", []) if m.get("verified")
                ),
                "connections": len(registry.get("connections", [])),
            }
        except Exception as e:
            checks["models"] = {"error": str(e)}

        # 3) 数据目录可写性（临时探测文件）
        try:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
            )
            os.makedirs(data_dir, exist_ok=True)
            probe = os.path.join(data_dir, ".health-write-probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            checks["data_writable"] = True
        except Exception as e:
            checks["data_writable"] = False
            checks["data_writable_error"] = str(e)

        if checks["neo4j"] != "ok":
            checks["status"] = "degraded"
        return checks

    # ============================================================
    # 生产模式前端托管：优先读 app/frontend/dist（Vite 构建产物）。
    # 手机通过隧道访问时只需 1 个端口、个位数静态资源，速度远快于 Vite dev。
    # API 404 保持 JSON 404，不落入 SPA fallback。
    # ============================================================
    def _register_frontend_spa():
        import mimetypes

        from flask import Response, abort as flask_abort

        dist_dir = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist"
        ))
        if not os.path.isdir(dist_dir):
            if should_log_startup:
                logger.info("前端 dist 不存在，跳过 SPA 托管（开发模式请用 Vite :3000）")
            return

        index_file = os.path.join(dist_dir, "index.html")

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_spa(path):
            if path == "api" or path.startswith("api/"):
                flask_abort(404)
            if not path:
                target = index_file
            else:
                target = os.path.normpath(os.path.join(dist_dir, path))
                try:
                    if os.path.commonpath([dist_dir, target]) != dist_dir:
                        flask_abort(404)
                except ValueError:
                    flask_abort(404)
            if os.path.isfile(target):
                # 用 Response(bytes) 而非 send_file：文件响应不再是 streamed，
                # 上面的 gzip 中间件才能压缩（隧道场景下 721KB JS → ~220KB）。
                with open(target, "rb") as fh:
                    data = fh.read()
                mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
                if target.endswith(".html"):
                    mime = "text/html; charset=utf-8"
                return Response(data, mimetype=mime)
            with open(index_file, "rb") as fh:
                data = fh.read()
            return Response(data, mimetype="text/html; charset=utf-8")

        @app.after_request
        def _cache_static(response):
            if request.path.startswith("/assets/"):
                response.headers.setdefault(
                    "Cache-Control", "public, max-age=31536000, immutable"
                )
            elif request.path.endswith((".js", ".css", ".png", ".ico", ".svg", ".woff2")):
                response.headers.setdefault("Cache-Control", "public, max-age=3600")
            else:
                response.headers.setdefault("Cache-Control", "no-cache")
            return response

        if should_log_startup:
            logger.info(f"SPA 托管已启用: {dist_dir}")

    _register_frontend_spa()

    # 压缩文本类响应（静态 JS/CSS/HTML 与 JSON API），手机走隧道时传输量降至约 1/3。
    @app.after_request
    def _gzip_compress(response):
        if (
            response.status_code == 200
            and not response.is_streamed
            and "gzip" in (request.headers.get("Accept-Encoding") or "").lower()
            and not response.headers.get("Content-Encoding")
        ):
            ctype = (response.content_type or "").split(";")[0].strip().lower()
            if ctype in {
                "text/html",
                "text/css",
                "application/javascript",
                "text/javascript",
                "application/json",
                "image/svg+xml",
            }:
                try:
                    data = response.get_data()
                    if len(data) >= 1024:
                        compressed = gzip.compress(data, compresslevel=6)
                        response.set_data(compressed)
                        response.headers["Content-Encoding"] = "gzip"
                        response.headers["Content-Length"] = str(len(compressed))
                        if "Vary" not in response.headers:
                            response.headers["Vary"] = "Accept-Encoding"
                except Exception:
                    pass
        return response

    if should_log_startup:
        logger.info("Miroworld Backend 启动完成")

    return app
