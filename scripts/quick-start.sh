#!/bin/bash

# MiroFish 快速启动脚本（路径自适应版）
# 用法: bash scripts/quick-start.sh
# 功能：清理上一次运行的残留进程 → 启动 Neo4j/后端/前端（nohup + 日志）
# 日志：/tmp/mirofish-backend.log 与 /tmp/mirofish-frontend.log

set -u

# 脚本所在目录推导项目根（兼容从仓库内任意位置调用）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 MiroFish 应用启动"
echo "=================="
echo "项目路径: $PROJECT_ROOT"
echo ""

cleanup_previous() {
    echo "🧹 清理上一次运行的残留（端口 3000/5001）..."
    local port pid cmd found=""
    for port in 3000 5001; do
        local pids
        pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
        [ -z "$pids" ] && continue
        for pid in $pids; do
            cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
            case "$cmd" in
                *mirofish-portable*|*run.py*|*vite*|*concurrently*|*npm*run*dev*)
                    found=yes
                    echo "  ⚠️ 停止旧进程 pid=$pid，释放端口 $port"
                    kill "$pid" 2>/dev/null || true
                    ;;
                *)
                    echo "  ⚠️ 端口 $port 被无关进程占用（${cmd:0:60}），跳过清理"
                    ;;
            esac
        done
    done
    [ -z "$found" ] && echo "  ✓ 无残留进程"
    local i
    for i in $(seq 1 10); do
        if ! lsof -nP -iTCP:3000 -sTCP:LISTEN -t >/dev/null 2>&1 &&            ! lsof -nP -iTCP:5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo "  ✓ 端口已释放"
            return 0
        fi
        sleep 1
    done
    echo "  ⚠️ 端口未完全释放，继续尝试启动"
}

cleanup_previous
echo ""

# 启动 Neo4j (如未运行)
if ! lsof -i :7687 >/dev/null 2>&1; then
    echo "启动 Neo4j..."
    brew services start neo4j 2>/dev/null || true
    sleep 3
fi

if lsof -i :7687 >/dev/null 2>&1; then
    echo "✓ Neo4j 运行在端口 7687"
else
    echo "❌ Neo4j 启动失败（如用便携版请先运行 ./scripts/start.sh 或 ./scripts/install-neo4j.sh）"
    exit 1
fi

echo ""

# 启动后端
echo "启动后端 (Flask)..."
cd "$PROJECT_ROOT/app/backend"
# 建图 LLM 并发：默认 2（性能调优）；网关不稳可用 GRAPHITI_MAX_CONCURRENCY=1 覆盖
export GRAPHITI_MAX_CONCURRENCY="${GRAPHITI_MAX_CONCURRENCY:-2}"
nohup .venv/bin/python run.py > /tmp/mirofish-backend.log 2>&1 &
sleep 4

if lsof -i :5001 >/dev/null 2>&1; then
    echo "✓ 后端运行在端口 5001"
else
    echo "❌ 后端启动失败"
    echo "   查看日志: tail -f /tmp/mirofish-backend.log"
    exit 1
fi

echo ""

# 启动前端
echo "启动前端 (Vue3)..."
cd "$PROJECT_ROOT/app/frontend"
nohup npm run dev > /tmp/mirofish-frontend.log 2>&1 &
sleep 6

if lsof -i :3000 >/dev/null 2>&1; then
    echo "✓ 前端运行在端口 3000"
else
    echo "❌ 前端启动失败"
    echo "   查看日志: tail -f /tmp/mirofish-frontend.log"
    exit 1
fi

echo ""
echo "=================="
echo "✨ 所有服务已启动"
echo "=================="
echo ""
echo "访问 MiroFish:"
echo "  🌐 http://localhost:3000"
echo ""
echo "详细信息:"
echo "  Neo4j:  http://localhost:7474"
echo "  API:    http://localhost:5001"
echo ""
echo "查看日志:"
echo "  后端: tail -f /tmp/mirofish-backend.log"
echo "  前端: tail -f /tmp/mirofish-frontend.log"
echo ""
echo "停止应用:"
echo "  pkill -f 'run.py'          (后端)"
echo "  pkill -f vite              (前端)"
echo "  或直接再次运行本脚本（会自动清理残留）"
echo ""
