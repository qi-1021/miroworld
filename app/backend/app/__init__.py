"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


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
        logger.info("MiroFish Backend 启动中...")
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

    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response

    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp, models_bp, world_bp, timeline_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    app.register_blueprint(models_bp, url_prefix='/api/models')
    app.register_blueprint(world_bp, url_prefix='/api/world')
    app.register_blueprint(timeline_bp, url_prefix='/api/timeline')

    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

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
            "service": "MiroFish Backend",
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

    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")

    return app
