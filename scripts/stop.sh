#!/bin/bash

# Miroworld 停止脚本：关闭上一次启动的前端+后端（端口 3000/5001 上的本项目进程），
# 可选一并停止 Neo4j，并清理未绑定端口的残留壳进程/模拟子进程。
# 用法:
#   bash scripts/stop.sh           仅停前端+后端（推荐日常使用）
#   bash scripts/stop.sh --neo4j   同时停止本项目 Neo4j
#   bash scripts/stop.sh --all     等价于 --neo4j
#   bash scripts/stop.sh --force   不等待优雅退出，立即 SIGKILL 本项目进程
#
# 说明：本脚本与 start.sh 的 cleanup_previous 使用同一套"只认本项目进程"的
# 匹配规则，不会误杀占用同端口的无关程序。

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
STOP_NEO4J=0
FORCE_KILL=0
for arg in "$@"; do
    case "$arg" in
        --neo4j|--all) STOP_NEO4J=1 ;;
        --force) FORCE_KILL=1 ;;
    esac
done

echo "🛑 Miroworld 停止脚本"
echo "===================="
echo "项目路径: $PROJECT_ROOT"
echo ""

# 判断 pid 是否属于本项目（命令路径/工作目录命中本项目，避免误杀无关进程）
is_project_pid() {
    local pid="$1" cmd cwd
    cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
    [ -z "$cmd" ] && return 1
    case "$cmd" in
        *mirofish-portable*|*run.py*|*run_world_simulation.py*|*run_parallel_simulation.py*|*run_reddit_simulation.py*|*run_twitter_simulation.py*|*vite*|*concurrently*|*npm*run*dev*)
            return 0 ;;
    esac
    # start.sh / quick-start.sh 前台包装自身也按工作目录归属本项目
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | head -1 | cut -c2-)
    case "$cwd" in
        "$PROJECT_ROOT"*) return 0 ;;
    esac
    return 1
}

# 杀单个 pid；软杀不生效（或 --force）则强杀
kill_one() {
    local pid="$1"
    if [ "${FORCE_KILL:-0}" = "1" ]; then
        kill -9 "$pid" 2>/dev/null || true
    else
        kill "$pid" 2>/dev/null || true
    fi
}

# 按端口停止本项目进程
stop_port() {
    local port="$1" pid cmd
    local pids
    pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -z "$pids" ]; then
        echo "  端口 $port: 无进程在监听"
        return 0
    fi
    for pid in $pids; do
        cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
        if is_project_pid "$pid"; then
            echo "  停止 pid=${pid}（端口 ${port}）"
            kill_one "$pid"
        else
            echo "  ⚠️ 端口 $port 由无关进程占用（${cmd:0:60}），跳过"
        fi
    done
    # 等待退出后，仍未退出的本项目进程才强杀
    if [ "${FORCE_KILL:-0}" != "1" ]; then
        sleep 3
        for pid in $pids; do
            if kill -0 "$pid" 2>/dev/null && is_project_pid "$pid"; then
                cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
                echo "  ⚠️ pid=${pid}（端口 ${port}）未退出，强制结束"
                kill -9 "$pid" 2>/dev/null || true
            fi
        done
    fi
}

echo "== 停止前端 + 后端 =="
stop_port 3000
stop_port 5001

# 兜底：清理未绑定端口的残留壳进程（concurrently/npm 壳 + start.sh 前台包装 + 模拟子进程）
echo "== 兜底清理残留壳进程 =="
kill_project_residual() {
    local force="$1"
    # 覆盖后端前端壳进程与四种模拟子进程
    for pat in "scripts/start.sh" "scripts/quick-start.sh" "run.py" "vite" \
               "concurrently" "npm run dev" \
               "run_world_simulation.py" "run_parallel_simulation.py" \
               "run_reddit_simulation.py" "run_twitter_simulation.py"; do
        for pid in $(pgrep -f "$pat" 2>/dev/null || true); do
            cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | head -1 | cut -c2-)
            case "$cwd" in
                "$PROJECT_ROOT"*)
                    if [ "$force" = "1" ]; then
                        echo "  强制结束残留 pid=${pid}（$(ps -p $pid -o command= | tail -1 | cut -c1-60)）"
                        kill -9 "$pid" 2>/dev/null || true
                    else
                        echo "  停止残留 pid=${pid}（$(ps -p $pid -o command= | tail -1 | cut -c1-60)）"
                        kill "$pid" 2>/dev/null || true
                    fi
                    ;;
            esac
        done
    done
}
kill_project_residual 0
sleep 3
kill_project_residual 1

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
                kill_one "$pid"
                found=1
                ;;
        esac
    done
    if [ "$found" = "0" ]; then
        echo "  未发现本项目 Neo4j 进程（可能未启动或已被外部管理）"
    fi
    # 残留 pid/run 文件一并清理，避免下次启动误判
    rm -f "$PROJECT_ROOT/neo4j/neo4j/run/neo4j.pid" \
          "$PROJECT_ROOT/neo4j/neo4j/libexec/run/neo4j.pid" 2>/dev/null || true
else
    echo ""
    echo "Neo4j 未停止（如需停止请加 --neo4j：bash scripts/stop.sh --neo4j）"
fi

# 等待端口释放（最多 15 秒；若仍被本项目进程占用则强制结束）
echo ""
echo "== 等待端口释放 =="
i=0
while [ $i -lt 15 ]; do
    if ! lsof -nP -iTCP:3000 -sTCP:LISTEN -t >/dev/null 2>&1 && \
       ! lsof -nP -iTCP:5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "✓ 3000/5001 已释放"
        break
    fi
    sleep 1
    i=$((i + 1))
done
# 超时后仍占用则强制清理（只清理本项目进程）
for port in 3000 5001; do
    for pid in $(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true); do
        if is_project_pid "$pid"; then
            echo "  ⚠️ 端口 $port 仍被本项目进程占用，强制结束 pid=$pid"
            kill -9 "$pid" 2>/dev/null || true
        else
            echo "  ⚠️ 端口 $port 被无关进程占用（未强制）；如需停止请手动处理：lsof -i :$port"
        fi
    done
done

echo ""
echo "✅ 停止完成"
echo "再次启动: bash scripts/start.sh   （会自动清理残留）"
echo "日志目录: app/backend/logs/  （start-backend.log / start-frontend.log，可删除）"
echo ""
