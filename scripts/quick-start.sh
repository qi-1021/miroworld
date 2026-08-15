#!/bin/bash
# MiroFish 快速启动入口（统一到 scripts/start.sh）
#
# 用法: bash scripts/quick-start.sh
# 说明：quick-start.sh 已统一到 scripts/start.sh —— 同一套"独立启动 + 逐服务端口校验 +
#       失败引导 + 前台日志"逻辑，避免两套启动代码分叉。本文件仅保留便捷别名入口。
#       start.sh 会在 app/backend/logs/ 下写 start-backend.log / start-frontend.log，
#       停止方式相同：CTRL+C，或 bash scripts/stop.sh（可加 --neo4j / --all）。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

YELLOW='\033[1;33m'
NC='\033[0m'

echo "🚀 MiroFish 快速启动（统一调用 scripts/start.sh）"
echo "=================="
echo ""
echo -e "${YELLOW}[WARN]${NC} quick-start.sh 已统一到 start.sh，本脚本等价于直接运行 scripts/start.sh。"
echo -e "${YELLOW}[WARN]${NC} 如需保持前台/后台或自定义并发，请直接：bash scripts/start.sh"
echo ""

bash "$SCRIPT_DIR/start.sh" "$@"
