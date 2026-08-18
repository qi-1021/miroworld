#!/bin/bash
# ==============================================================================
# Miroworld 一键更新脚本 (macOS / Linux)
# 特性：
#   - 采用 HTTPS 公共拉取，无需 SSH Key 或 GitHub Token 凭证
#   - 自动检测并拉取 GitHub 仓库最新代码 (git pull)
#   - 自动按需安装/更新 Python 与 Node.js 依赖
#   - 自动重新构建前端静态产物 (vite build)
#   - 智能保留本地配置 (.env, 数据库, 运行时日志) 不受影响
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "================================================================="
echo "        🚀 Miroworld 一键无密更新程序 (GitHub Public Sync)       "
echo "================================================================="

cd "$PROJECT_ROOT"

# 1. 检查 git 环境
if ! command -v git >/dev/null 2>&1; then
    log_error "未找到 git 命令，请先安装 Git。"
    exit 1
fi

# 2. 检查远程分支
log_step "正在从 GitHub 获取最新版本代码..."

# 确保 remote 使用 HTTPS 公开地址（免 key）
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [[ "$CURRENT_REMOTE" == git@github.com:* ]]; then
    HTTPS_REMOTE="https://github.com/${CURRENT_REMOTE#git@github.com:}"
    log_info "检测到 SSH 远程地址，切换为公开免密 HTTPS 地址: $HTTPS_REMOTE"
    git remote set-url origin "$HTTPS_REMOTE"
elif [[ -z "$CURRENT_REMOTE" ]]; then
    git remote add origin "https://github.com/qi-1021/miroworld.git"
fi

# 获取当前分支名称
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
log_info "当前分支: $BRANCH"

# 拉取最新代码
if git pull origin "$BRANCH"; then
    log_info "✅ 源代码已成功同步至最新版本！"
else
    log_warn "拉取时检测到本地未提交修改，正在尝试 stash 保留并更新..."
    git stash
    git pull origin "$BRANCH"
    git stash pop || true
    log_info "✅ 代码已合并更新完成。"
fi

# 3. 检查并更新后端 Python 依赖
log_step "检查并同步后端 Python 环境依赖..."
if [ -f "$APP_DIR/backend/requirements.txt" ]; then
    PYTHON_CMD=""
    if [ -f "$APP_DIR/backend/.venv/bin/python" ]; then
        PYTHON_CMD="$APP_DIR/backend/.venv/bin/python"
    elif [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
        PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
    elif [ -f "$APP_DIR/backend/venv/bin/python" ]; then
        PYTHON_CMD="$APP_DIR/backend/venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    fi

    if [ -n "$PYTHON_CMD" ]; then
        log_info "使用 Python: $($PYTHON_CMD --version 2>&1)"
        $PYTHON_CMD -m pip install -r "$APP_DIR/backend/requirements.txt" -q --disable-pip-version-check || log_warn "Python 依赖增量安装跳过或已是最新"
    else
        log_warn "未检测到独立虚拟环境，若后端运行异常请运行 scripts/setup-env.sh"
    fi
fi

# 4. 检查并编译前端产物
log_step "检查并构建前端生产包..."
if [ -d "$APP_DIR/frontend" ] && command -v npm >/dev/null 2>&1; then
    cd "$APP_DIR/frontend"
    if [ -f "package.json" ]; then
        log_info "执行前端极速构建..."
        npm run build || log_warn "前端构建失败，请检查 node/npm 环境"
    fi
    cd "$PROJECT_ROOT"
fi

echo ""
echo "================================================================="
log_info "🎉 Miroworld 更新完成！"
echo "👉 您可以随时运行以下命令启动最新版系统："
echo "   bash scripts/start.sh"
echo "================================================================="
