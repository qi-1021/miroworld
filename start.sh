#!/usr/bin/env bash
# ==============================================================================
# 🐟 Miroworld 根目录极速启动入口 (macOS / Linux)
# 直接在项目根目录下运行: ./start.sh
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/scripts/start.sh" "$@"
