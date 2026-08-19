"""
Support API路由
提供错误报告生成等支持功能（供非技术测试人员一键打包系统信息+日志）。
"""

import time

from flask import jsonify, request

from . import support_bp
from ..utils.logger import get_logger
from ..utils.report import build_report

logger = get_logger('mirofish.api.support')

# 简单内存限流：同一客户端两次生成报告至少间隔 30 秒（报告打包较耗资源）
_REPORT_INTERVAL_SECONDS = 30
_last_report_time = {}


@support_bp.route('/report', methods=['POST'])
def create_support_report():
    """生成错误报告压缩包（系统信息 + 日志 + 失败任务）。

    请求（JSON，均可选）：
        {
            "description": "问题描述文字",        // 可选
            "frontend_errors": ["错误1", "..."]    // 可选，前端错误缓冲
        }

    返回：
        {
            "success": true,
            "data": {
                "report_path": "....zip 绝对路径",
                "report_dir": "输出目录",
                "files": ["system-info.txt", "logs/....log", "README.txt"],
                "size_bytes": 123456
            }
        }
    """
    # 限流：防止频繁调用打满磁盘/日志
    now = time.time()
    client_key = request.remote_addr or "unknown"
    if now - _last_report_time.get(client_key, 0) < _REPORT_INTERVAL_SECONDS:
        return jsonify({
            "success": False,
            "error": "报告生成过于频繁，请稍后再试",
        }), 429

    try:
        data = request.get_json(silent=True) or {}
        description = data.get("description") or ""
        frontend_errors = data.get("frontend_errors")
        if frontend_errors is not None and not isinstance(frontend_errors, list):
            frontend_errors = [frontend_errors]

        result = build_report(
            description=description,
            frontend_errors=frontend_errors,
        )
        # 只在成功生成后更新时间戳，失败不锁死（允许用户重试）
        _last_report_time[client_key] = time.time()
        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"生成错误报告失败: {e}")
        return jsonify({
            "success": False,
            "error": "生成错误报告失败，请稍后重试，或联系维护者获取帮助。"
        }), 500


@support_bp.route('/report/status', methods=['GET'])
def support_report_status():
    """错误报告功能可用性检查（前端用探活端点）。"""
    return jsonify({"success": True, "data": {"available": True}})
