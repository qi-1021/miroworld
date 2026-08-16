#!/bin/bash
# Miroworld 模型配置初始化 (macOS/Linux)
# 用途：在启动前后端之前运行，完成两件事：
#   1. 首次运行时把旧 .env 的 LLM 配置导入模型注册表（幂等，不会覆盖已有配置）
#   2. 检查模型库状态，并提示如何配置模型
# 用法：bash scripts/init-models.sh   （start.sh 会自动调用，也可单独运行）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# 后端环境未安装时跳过（首次启动 start.sh 会先完成安装）
if [ ! -x "$APP_DIR/backend/.venv/bin/python" ]; then
    log_warn "后端环境未安装，跳过模型配置初始化（请先运行 ./scripts/start.sh 完成安装）"
    exit 0
fi

PYTHON="$APP_DIR/backend/.venv/bin/python"
CLI="$APP_DIR/backend/scripts/mirofish_models.py"

cd "$APP_DIR"

# 1. 导入旧 .env 配置（幂等，仅首次生效）
log_info "检查并导入 .env 中的旧 LLM 配置..."
RESULT=$("$PYTHON" "$CLI" --json env import 2>/dev/null || true)
if [ -n "$RESULT" ]; then
    IMPORTED=$(printf '%s' "$RESULT" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['data'].get('imported', False))" 2>/dev/null || echo "False")
    if [ "$IMPORTED" = "True" ]; then
        log_info "已从 .env 导入旧 LLM 配置（可在网页「模型设置」中随时替换）"
    fi
fi

# 2. 检查模型库状态
COUNT=$("$PYTHON" "$CLI" --json models list 2>/dev/null | "$PYTHON" -c "import json,sys; print(len(json.load(sys.stdin)['data'].get('models', [])))" 2>/dev/null || echo "0")
if [ "$COUNT" -gt 0 ]; then
    log_info "模型库已就绪：已登记 ${COUNT} 个模型"
else
    log_warn "模型库为空：启动后打开 http://localhost:3000 ，点击「模型设置」添加连接"
    log_warn "支持 OpenAI / DeepSeek / 阿里百炼 / OpenCode / Ollama / LM Studio 等兼容接口"
fi
