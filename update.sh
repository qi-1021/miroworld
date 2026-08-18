#!/usr/bin/env bash
# ==============================================================================
# 🐟 Miroworld 根目录一键更新入口 (macOS / Linux)
# 直接在项目根目录下运行: ./update.sh (无需 Key 免密同步最新代码与依赖)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/scripts/update.sh" "$@"
