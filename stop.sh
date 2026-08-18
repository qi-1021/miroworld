#!/usr/bin/env bash
# ==============================================================================
# 🐟 Miroworld 根目录停止服务入口 (macOS / Linux)
# 直接在项目根目录下运行: ./stop.sh (或 ./stop.sh --all 停数据库)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/scripts/stop.sh" "$@"
