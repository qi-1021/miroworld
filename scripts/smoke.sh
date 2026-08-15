#!/bin/bash
# MiroFish 全流程冒烟测试：启动完整栈 → 等待前后端就绪 → 停止全部。
# 用法：
#   bash scripts/smoke.sh
# 退出码 0=通过，非 0=失败（服务未就绪或端口被无关程序占用）。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG="/tmp/mirofish-smoke.log"

cleanup() {
    echo "== 冒烟结束，停止服务 =="
    bash "$SCRIPT_DIR/stop.sh" --all >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== MiroFish 全流程冒烟测试 =="
echo "项目: $PROJECT_ROOT"
echo "日志: $LOG"

# 先确保没有残留服务
bash "$SCRIPT_DIR/stop.sh" --all >/dev/null 2>&1 || true
sleep 1

echo "== 启动完整服务栈 =="
nohup bash "$SCRIPT_DIR/start.sh" > "$LOG" 2>&1 &
START_PID=$!
echo "start.sh pid=$START_PID"

ready=0
for i in $(seq 1 60); do
    if curl -s -m 3 http://127.0.0.1:5001/health >/dev/null 2>&1 && \
       curl -s -m 3 -o /dev/null http://127.0.0.1:3000/ >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done

if [ "$ready" != "1" ]; then
    echo "SMOKE FAIL: 后端/前端未在 120 秒内就绪"
    tail -60 "$LOG" || true
    exit 1
fi

echo "SMOKE OK: backend /health 通过"
echo "SMOKE OK: frontend http://127.0.0.1:3000 返回 200"
neo4j_count=$(lsof -iTCP:7687 -sTCP:LISTEN -t 2>/dev/null | wc -l | tr -d ' ')
echo "SMOKE OK: Neo4j 7687 监听数=$neo4j_count"
echo "== 详细健康检查 =="
curl -s -m 5 http://127.0.0.1:5001/api/health/detailed | python3 -m json.tool 2>/dev/null || echo "详细健康检查不可用"
