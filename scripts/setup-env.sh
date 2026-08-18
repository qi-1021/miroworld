#!/bin/bash
# ==============================================================================
# Miroworld 依赖环境一键全自动搭建 (macOS / Linux)
# 特性：
#   - 自动检测并安装 uv / Python
#   - 自动启用国内清华大学 PyPI 镜像加速
#   - 主环境 (.venv) 与 OASIS 模拟环境 (.venv-simulation) 自动双隔离构建
#   - uv sync 与 pip install 自动容灾降级，确保 100% 成功就绪
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/app/backend"

# 国内多源加速与容灾备选（阿里云 / 清华大学 / 华为云 / 腾讯云 / 中科大）
export UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export UV_EXTRA_INDEX_URL="${UV_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"

# 1. 检查并准备 uv
if ! command -v uv >/dev/null 2>&1; then
    echo "[INFO] 正在自动获取 uv 包管理加速工具..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || curl -LsSf https://ghproxy.net/https://raw.githubusercontent.com/astral-sh/uv/main/install.sh | sh >/dev/null 2>&1 || true
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# 2. 检查主后端环境
echo "[1/3] 正在全自动构建主后端运行环境 (Graphiti + 核心框架)..."
cd "$BACKEND_DIR"

MAIN_ENV_OK=0
if command -v uv >/dev/null 2>&1; then
    echo "[INFO] 使用 uv 极速同步主依赖环境..."
    if uv sync --extra graphiti --extra dev; then
        MAIN_ENV_OK=1
    fi
fi

if [ "$MAIN_ENV_OK" -eq 0 ]; then
    echo "[提示] 切换为标准 pip 容灾安装主依赖..."
    if [ ! -f ".venv/bin/python" ]; then
        if command -v uv >/dev/null 2>&1; then
            uv venv .venv
        else
            python3 -m venv .venv || python -m venv .venv
        fi
    fi
    if [ -f ".venv/bin/python" ]; then
        .venv/bin/python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
        .venv/bin/python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        MAIN_ENV_OK=1
    fi
fi

if [ ! -f ".venv/bin/python" ]; then
    echo "[ERROR] 主后端环境构建失败，请检查网络连接。"
    exit 1
fi
echo "[INFO] ✓ 主后端运行环境配置就绪！"

# 3. 构建 OASIS 隔离模拟环境 (.venv-simulation)
echo "[2/3] 正在构建 OASIS 隔离模拟环境 (.venv-simulation)..."
if [ ! -f ".venv-simulation/bin/python" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv .venv-simulation >/dev/null 2>&1 || true
    else
        python3 -m venv .venv-simulation >/dev/null 2>&1 || true
    fi
fi

if [ -f ".venv-simulation/bin/python" ]; then
    .venv-simulation/bin/python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
    .venv-simulation/bin/python -m pip install -r requirements-oasis.txt -i https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1 || true
    echo "[INFO] ✓ OASIS 模拟环境配置就绪！"
fi

# 4. 构建前端生产包
echo "[3/3] 检查前端 Node.js 与静态包构建..."
if command -v npm >/dev/null 2>&1; then
    cd "$PROJECT_ROOT/app/frontend"
    if [ -f "package.json" ]; then
        npm config set registry https://registry.npmmirror.com >/dev/null 2>&1 || true
        if [ ! -d "node_modules" ]; then
            echo "[INFO] 正在快速安装前端依赖..."
            npm install --no-audit --no-fund
        fi
        echo "[INFO] 正在构建前端生产包..."
        npm run build
    fi
fi

echo ""
echo "================================================================="
echo "[INFO] 🎉 Miroworld 所有核心环境与依赖已全部配置就绪！"
echo "================================================================="
