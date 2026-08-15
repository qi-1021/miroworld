#!/bin/bash
# MiroFish 依赖环境一键搭建（Graphiti 本地优先 + OASIS 隔离）
#
# 背景：
# - 主环境安装 Graphiti/Neo4j 本地图谱依赖（graphiti-core 需要 neo4j>=5.26）
# - OASIS 社交媒体模拟依赖 camel-oasis（锁定 neo4j==5.23.0）
# 两者存在 Neo4j 版本冲突，因此 OASIS 装在独立的 app/backend/.venv-simulation 中。
#
# 用法：
#   bash scripts/setup-env.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/app/backend"

echo "[1/2] 安装主环境（Graphiti + Neo4j 本地优先 + 开发工具）..."
cd "$BACKEND_DIR"
uv sync --extra graphiti --extra dev

echo "[2/2] 创建/更新 OASIS 隔离模拟环境 (.venv-simulation)..."
if [ ! -d "$BACKEND_DIR/.venv-simulation/bin" ]; then
    uv venv "$BACKEND_DIR/.venv-simulation"
fi
"$BACKEND_DIR/.venv-simulation/bin/pip" install --upgrade pip
"$BACKEND_DIR/.venv-simulation/bin/pip" install -r "$BACKEND_DIR/requirements-oasis.txt"

echo "完成。"
echo "启动：bash scripts/start.sh"
echo "测试：cd app/backend && uv run pytest"
