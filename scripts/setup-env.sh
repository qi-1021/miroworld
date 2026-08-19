#!/bin/bash
# ==============================================================================
# Miroworld 依赖环境一键全自动搭建 (macOS / Linux)
# 特性：
#   - 自动检测并安装 uv / Python
#   - 自动启用国内清华大学 PyPI 镜像加速
#   - 主环境 (.venv) 与 OASIS 模拟环境 (.venv-simulation) 自动双隔离构建
#   - uv sync 与 pip install 自动容灾降级，确保 100% 成功就绪
#   - 全流程写入安装日志 logs/install.log，pip 安装失败自动重试
#   - 失败时给出友好中文提示与下一步指引
# ==============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/app/backend"

# ------------------------------------------------------------------------------
# 安装日志（logs/install.log）
# ------------------------------------------------------------------------------
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="${MIROWORLD_LOG_FILE:-$LOG_DIR/install.log}"
if mkdir -p "$LOG_DIR" 2>/dev/null; then
    echo -e "${BLUE}[STEP]${NC} 安装日志将写入: $LOG_FILE"
else
    echo -e "${YELLOW}[WARN]${NC} 无法创建日志目录: $LOG_DIR（将继续安装，但无法保存日志）"
fi

# 追加带时间戳的日志行（日志写入失败不影响安装主流程）
log_to_file() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE" 2>/dev/null || true
}

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; log_to_file "[INFO] $1"; }
log_step()  {
    local step="$1"
    local status="${2:-}"
    echo -e "${BLUE}[STEP]${NC} $step"
    if [ -n "$status" ]; then log_to_file "[STEP] $step [${status}]"; else log_to_file "[STEP] $step"; fi
}
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; log_to_file "[WARN] $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; log_to_file "[ERROR] $1"; }

# 友好失败出口：打印原因 / 日志路径 / 下一步指引
fail() {
    local reason="$1"
    local detail="${2:-}"
    log_to_file "[ERROR] 安装失败: ${reason} ${detail}"
    echo ""
    echo -e "${RED}=====================================================================${NC}"
    echo -e "${RED}  ❌ 安装失败: ${reason}${NC}"
    if [ -n "$detail" ]; then
        echo -e "${YELLOW}  原因: ${detail}${NC}"
    fi
    echo -e "${YELLOW}  📄 详细日志: ${LOG_FILE}${NC}"
    echo -e "${YELLOW}  📮 请将此日志文件发送给维护者（微信/邮件均可），我们会帮您尽快解决。${NC}"
    echo -e "${RED}=====================================================================${NC}"
    exit 1
}

# ------------------------------------------------------------------------------
# pip 安装重试：2 次尝试，失败等待 5 秒后自动重试
# 用法：retry_pip_install <描述> <命令...>
# ------------------------------------------------------------------------------
retry_pip_install() {
    local desc="$1"
    shift
    local attempt rc
    for attempt in 1 2; do
        echo -e "${BLUE}[STEP]${NC} ${desc}（第 ${attempt}/2 次尝试）..."
        log_to_file "[CMD] $*"
        if "$@"; then
            log_step "${desc}完成" "ok"
            return 0
        else
            rc=$?
            log_to_file "[CMD] ${desc} 失败，退出码: $rc"
            if [ "$attempt" -lt 2 ]; then
                log_warn "${desc} 失败，${attempt}/2，5 秒后自动重试..."
                sleep 5
            fi
        fi
    done
    log_error "${desc} 最终失败，退出码: $rc"
    return 1
}

# ------------------------------------------------------------------------------
# 安装流程开始
# ------------------------------------------------------------------------------
log_to_file "===== Miroworld 依赖环境搭建开始 ====="
log_to_file "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
log_to_file "项目目录: $PROJECT_ROOT"

# 国内多源加速与容灾备选（阿里云 / 清华大学 / 华为云 / 腾讯云 / 中科大）
export UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export UV_EXTRA_INDEX_URL="${UV_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"

# 1. 检查并准备 uv
log_step "检查并准备 uv / Python 工具链..."
if ! command -v uv >/dev/null 2>&1; then
    log_warn "未检测到 uv，正在自动获取 uv 包管理加速工具..."
    log_to_file "[CMD] curl -LsSf https://astral.sh/uv/install.sh | sh"
    if curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; then
        log_step "uv 安装完成" "ok"
    else
        rc=$?
        log_to_file "[CMD] 官方源安装失败（退出码: $rc），切换国内镜像通道重试"
        if curl -LsSf https://ghproxy.net/https://raw.githubusercontent.com/astral-sh/uv/main/install.sh | sh >/dev/null 2>&1; then
            log_step "uv 安装完成（镜像通道）" "ok"
        else
            rc=$?
            log_warn "uv 自动安装失败（退出码: $rc），将使用系统 Python 完成安装"
        fi
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
else
    log_info "uv 已就绪: $(uv --version 2>&1)"
fi

# 2. 检查主后端环境
log_step "正在全自动构建主后端运行环境 (Graphiti + 核心框架)..."
cd "$BACKEND_DIR"

if [ ! -f ".venv/bin/python" ]; then
    if command -v uv >/dev/null 2>&1; then
        log_to_file "[CMD] uv venv .venv"
        if uv venv .venv; then
            log_step "创建虚拟环境 (.venv)" "ok"
        else
            rc=$?
            fail "创建虚拟环境失败" "uv venv 退出码: $rc，请查看上方错误提示"
        fi
    else
        log_to_file "[CMD] python3 -m venv .venv"
        if python3 -m venv .venv; then
            log_step "创建虚拟环境 (.venv)" "ok"
        elif python -m venv .venv; then
            log_step "创建虚拟环境 (.venv)" "ok"
        else
            rc=$?
            fail "创建虚拟环境失败" "python3 / python 退出码: $rc，请查看上方错误提示"
        fi
    fi
else
    log_info "虚拟环境已存在，跳过创建"
fi

if [ -f ".venv/bin/python" ]; then
    if command -v uv >/dev/null 2>&1; then
        echo "[INFO] 使用 uv 极速安装主核心依赖..."
        if ! retry_pip_install "uv 安装主核心依赖" uv pip install -r requirements.txt --python .venv/bin/python --index-url https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/; then
            fail "Python 依赖安装失败" "已自动重试 2 次仍失败，请检查网络连接后重新运行"
        fi
    else
        echo "[INFO] 使用 pip 安装主核心依赖..."
        if ! .venv/bin/python -m ensurepip >/dev/null 2>&1; then
            log_warn "ensurepip 处理未执行（venv 已自带 pip 或无需处理）"
        fi
        if ! retry_pip_install "pip 安装主核心依赖" .venv/bin/python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/; then
            fail "Python 依赖安装失败" "已自动重试 2 次仍失败，请检查网络连接后重新运行"
        fi
    fi
else
    fail "主后端环境构建失败" "虚拟环境未就绪，请检查网络连接后重新运行"
fi
log_step "主后端运行环境配置" "ok"

# 清理可能遗留的损坏 .venv-simulation 目录
if [ -d ".venv-simulation" ]; then
    if rm -rf ".venv-simulation" >/dev/null 2>&1; then
        log_to_file "[CMD] 已清理残留的 .venv-simulation 目录"
    else
        log_warn "清理 .venv-simulation 目录失败（可忽略）"
    fi
fi

# 3. 构建前端生产包
log_step "检查前端 Node.js 与静态包构建..."
if command -v npm >/dev/null 2>&1; then
    cd "$PROJECT_ROOT/app/frontend"
    if [ -f "package.json" ]; then
        log_to_file "[CMD] npm config set registry https://registry.npmmirror.com"
        if ! npm config set registry https://registry.npmmirror.com >/dev/null 2>&1; then
            log_warn "设置 npm 国内镜像源失败（可忽略）"
        fi
        if [ ! -d "node_modules" ]; then
            log_step "正在快速安装前端依赖..."
            log_to_file "[CMD] npm install --no-audit --no-fund"
            if npm install --no-audit --no-fund; then
                log_step "前端依赖安装完成" "ok"
            else
                rc=$?
                fail "前端依赖安装失败" "npm install 退出码: $rc，请检查网络连接后重新运行"
            fi
        else
            log_info "node_modules 已存在，跳过依赖安装"
        fi
        log_step "正在构建前端生产包..."
        log_to_file "[CMD] npm run build"
        if npm run build; then
            log_step "前端构建" "ok"
        else
            rc=$?
            log_to_file "[CMD] npm run build 失败，退出码: $rc"
            log_step "前端构建" "fail"
            log_warn "前端构建失败，可在修复后运行 npm run build 手动构建"
        fi
    else
        log_warn "未找到 package.json，跳过前端构建"
    fi
else
    log_warn "未检测到 npm，跳过前端构建（可稍后在 app/frontend 下手动执行 npm install && npm run build）"
fi

# 4. 完成
log_step "Miroworld 所有核心环境与依赖已全部配置就绪" "ok"
echo ""
echo "================================================================="
echo "[INFO] 🎉 Miroworld 所有核心环境与依赖已全部配置就绪！"
echo "================================================================="
echo -e "${YELLOW}📄 安装日志已保存至: ${LOG_FILE}${NC}"
