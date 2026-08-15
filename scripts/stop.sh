#!/bin/bash

# MiroFish 停止脚本：关闭上一次启动的前端+后端（端口 3000/5001 上的本项目进程），
# 可选一并停止 Neo4j。
# 用法:
#   bash scripts/stop.sh           仅停前端+后端（推荐日常使用）
#   bash scripts/stop.sh --neo4j   同时停止本项目 Neo4j
#   bash scripts/stop.sh --all     等价于 --neo4j
#
# 说明：本脚本与 start.sh 的 cleanup_previous 使用同一套"只认本项目进程"的
# 匹配规则，不会误杀占用同端口的无关程序。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
STOP_NEO4J=0
for arg in "$@"; do
    case "$arg" in
        --neo4j|--all) STOP_NEO4J=1 ;;
    esac
done

echo "🛑 MiroFish 停止脚本"
echo "===================="
echo "项目路径: $PROJECT_ROOT"
echo ""

# 按端口停止本项目进程
stop_port() {
    local port="$1"
    local pids pid cmd
    pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -z "$pids" ]; then
        echo "  端口 $port: 无进程在监听"
        return 0
    fi
    for pid in $pids; do
        cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
        case "$cmd" in
            *mirofish-portable*|*run.py*|*vite*|*concurrently*|*npm*run*dev*)
                echo "  停止 pid=$pid（端口 $port）"
                kill "$pid" 2>/dev/null || true
                ;;
            *)
                echo "  ⚠️ 端口 $port 由无关进程占用（${cmd:0:60}），跳过"
                ;;
        esac
    done
}

echo "== 停止前端 + 后端 =="
stop_port 3000
stop_port 5001

# 兜底：清理未绑定端口的残留子进程（concurrently/npm 壳进程 + 模拟子进程）
echo "== 兜底清理残留壳进程 =="
for pat in "run.py" "vite" "concurrently" "npm run dev" \
    "run_world_simulation.py" "run_parallel_simulation.py" \
    "run_reddit_simulation.py" "run_twitter_simulation.py"; do
    # 用 pgrep 全盘匹配 + 工作目录校验属于本项目（避免误杀）
    for pid in $(pgrep -f "$pat" 2>/dev/null || true); do
        cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | head -1 | cut -c2-)
        case "$cwd" in
            "$PROJECT_ROOT"*)
                echo "  停止残留 pid=$pid（$(ps -p $pid -o command= | tail -1 | cut -c1-60)）"
                kill "$pid" 2>/dev/null || true
                ;;
        esac
    done
done

# 可选：停止本项目 Neo4j
if [ "$STOP_NEO4J" = "1" ]; then
    echo ""
    echo "== 停止本项目 Neo4j =="
    found=0
    for pid in $(pgrep -f java 2>/dev/null || true); do
        cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
        case "$cmd" in
            *mirofish-portable*neo4j*|*"$HOME/mirofish-portable"*neo4j*)
                echo "  停止 Neo4j pid=$pid"
                kill "$pid" 2>/dev/null || true
                found=1
                ;;
        esac
    done
    if [ "$found" = "0" ]; then
        echo "  未发现本项目 Neo4j 进程（可能未启动或已被外部管理）"
    fi
else
    echo ""
    echo "Neo4j 未停止（如需停止请加 --neo4j：bash scripts/stop.sh --neo4j）"
fi

# 等待端口释放（最多 8 秒）
echo ""
echo "== 等待端口释放 =="
i=0
while [ $i -lt 8 ]; do
    if ! lsof -nP -iTCP:3000 -sTCP:LISTEN -t >/dev/null 2>&1 && \
       ! lsof -nP -iTCP:5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "✓ 3000/5001 已释放"
        break
    fi
    sleep 1
    i=$((i + 1))
done

echo ""
echo "✅ 停止完成"
echo "再次启动: bash scripts/start.sh   （会自动清理残留）"
echo ""
