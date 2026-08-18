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

# 1 & 2. 检查 Git 或自动降级为原生 ZIP 覆盖更新
log_step "正在从 GitHub 获取最新版本代码..."

if command -v git >/dev/null 2>&1; then
    # 确保 remote 使用 HTTPS 公开地址（免 key）
    CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$CURRENT_REMOTE" == git@github.com:* ]]; then
        HTTPS_REMOTE="https://github.com/${CURRENT_REMOTE#git@github.com:}"
        log_info "检测到 SSH 远程地址，切换为公开免密 HTTPS 地址: $HTTPS_REMOTE"
        git remote set-url origin "$HTTPS_REMOTE"
    elif [[ -z "$CURRENT_REMOTE" ]]; then
        git remote add origin "https://github.com/qi-1021/miroworld.git"
    fi

    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    log_info "当前分支: $BRANCH"

    if git pull origin "$BRANCH"; then
        log_info "✅ 源代码已成功同步至最新版本！"
    else
        log_warn "拉取时检测到本地未提交修改，正在尝试 stash 保留并更新..."
        git stash
        git pull origin "$BRANCH"
        git stash pop || true
        log_info "✅ 代码已合并更新完成。"
    fi
else
    log_warn "检测到当前环境未安装 Git，自动启用免 Git 原生 ZIP 极速增量更新通道..."
    ZIP_URL="https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    PROXY_ZIP_URL="https://ghproxy.net/https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    ZIP_FILE="miroworld-update-temp.zip"

    if ! curl -fsSL -m 30 "$PROXY_ZIP_URL" -o "$ZIP_FILE" 2>/dev/null; then
        curl -fsSL -m 60 "$ZIP_URL" -o "$ZIP_FILE" || { log_error "更新源码包下载失败，请检查网络"; exit 1; }
    fi

    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIP_FILE"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')"
    elif command -v python >/dev/null 2>&1; then
        python -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')"
    fi

    if [ -d "miroworld-main" ]; then
        cp -R miroworld-main/* "$PROJECT_ROOT/" 2>/dev/null || cp -r miroworld-main/* "$PROJECT_ROOT/"
        rm -rf miroworld-main "$ZIP_FILE"
    fi
    log_info "✅ 源码包已自动同步至最新版本！"
fi

# 3. 检查并更新后端 Python 依赖
log_step "检查并同步后端 Python 环境依赖 (国内镜像加速)..."
if [ -d "$APP_DIR/backend/.venv-simulation" ]; then
    rm -rf "$APP_DIR/backend/.venv-simulation" >/dev/null 2>&1 || true
fi

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
        if command -v uv >/dev/null 2>&1; then
            uv pip install -r "$APP_DIR/backend/requirements.txt" --python "$PYTHON_CMD" --index-url https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ >/dev/null 2>&1 || true
        else
            $PYTHON_CMD -m pip install -r "$APP_DIR/backend/requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ -q --disable-pip-version-check || log_warn "Python 依赖增量安装跳过或已是最新"
        fi
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
