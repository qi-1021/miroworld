#!/bin/bash
# MiroFish 可移植部署 - 主启动脚本 (macOS/Linux)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"
NEO4J_DIR="$PROJECT_ROOT/neo4j"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 函数：打印带颜色的信息
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查前置依赖
check_dependencies() {
    log_info "检查前置依赖..."
    
    # 检查 Node.js
    if ! command -v node &> /dev/null; then
        log_error "Node.js 未安装。请访问 https://nodejs.org 安装"
        exit 1
    fi
    log_info "✓ Node.js $(node --version)"
    
    # 检查 Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装。请访问 https://python.org 安装"
        exit 1
    fi
    log_info "✓ Python3 $(python3 --version)"
    
    # 检查 uv
    if ! command -v uv &> /dev/null; then
        log_warn "uv 未安装，尝试安装..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    log_info "✓ uv $(uv --version)"
    
    # 检查 Java（Neo4j 需要 JVM）
    if ! command -v java &> /dev/null; then
        log_error "Java 未安装。Neo4j 需要 JVM，请先安装 Java 17+"
        exit 1
    fi
    JAVA_VER=$(java -version 2>&1 | head -1 | sed 's/.*version "//;s/".*//')
    log_info "✓ Java $JAVA_VER"
}

# 检查并启动 Neo4j
start_neo4j() {
    log_info "启动 Neo4j..."
    
    # Neo4j 的配置解析无法正确处理含中文等非 ASCII 字符的路径。
    # 解决方案：创建 ASCII 软链别名（~/mirofish-portable -> 项目目录），
    # 让 Neo4j 通过别名路径访问，数据物理位置仍在项目文件夹内。
    NEO4J_ROOT="$PROJECT_ROOT"
    if printf '%s' "$PROJECT_ROOT" | LC_ALL=C grep -q '[^ -~]'; then
        if printf '%s' "$HOME" | LC_ALL=C grep -q '[^ -~]'; then
            log_error "项目路径和用户主目录都包含非 ASCII 字符，无法创建 ASCII 别名"
            log_error "请将项目移动到纯英文路径（如 /Volumes/Data/mirofish-portable）"
            exit 1
        fi
        ln -sfn "$PROJECT_ROOT" "$HOME/mirofish-portable"
        if [ ! -e "$HOME/mirofish-portable/scripts/start.sh" ]; then
            log_error "创建 ASCII 别名失败，请将项目移动到纯英文路径"
            exit 1
        fi
        NEO4J_ROOT="$HOME/mirofish-portable"
        log_warn "项目路径包含非 ASCII 字符，已通过 ~/mirofish-portable 别名启动 Neo4j"
    fi
    NEO4J_DIR="$NEO4J_ROOT/neo4j"
    
    # 检查 Neo4j 是否已经运行
    if lsof -Pi :7687 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_warn "Neo4j 已在监听端口 7687"
        return 0
    fi
    
    # 兼容两种安装布局：neo4j/neo4j（安装脚本默认）或 neo4j/neo4j-program（已有便携部署）
    NEO4J_HOME="$NEO4J_DIR/neo4j"
    if [ ! -d "$NEO4J_HOME" ] && [ -d "$NEO4J_DIR/neo4j-program" ]; then
        NEO4J_HOME="$NEO4J_DIR/neo4j-program"
        log_info "检测到 Neo4j 安装在 $NEO4J_HOME"
    fi
    
    # 检查 Neo4j 是否存在
    if [ ! -d "$NEO4J_HOME" ]; then
        log_error "Neo4j 未安装。请运行 ./scripts/install-neo4j.sh"
        exit 1
    fi
    
    # 自修复：Homebrew 拷贝布局下 bin/neo4j 可能是损坏的占位文件，恢复为 libexec 软链
    if [ -f "$NEO4J_HOME/libexec/bin/neo4j" ] && [ ! -L "$NEO4J_HOME/bin/neo4j" ]; then
        if [ -f "$NEO4J_HOME/bin/neo4j" ] && [ "$(wc -l < "$NEO4J_HOME/bin/neo4j" 2>/dev/null || echo 999)" -lt 10 ]; then
            log_warn "检测到损坏的 bin/neo4j 启动脚本，正在恢复..."
            rm -f "$NEO4J_HOME/bin/neo4j" "$NEO4J_HOME/bin/neo4j-admin"
            ln -s ../libexec/bin/neo4j "$NEO4J_HOME/bin/neo4j"
            ln -s ../libexec/bin/neo4j-admin "$NEO4J_HOME/bin/neo4j-admin"
        fi
    fi
    
    # 数据目录检查
    if [ ! -d "$NEO4J_DIR/neo4j-data/data" ]; then
        log_warn "未找到数据目录 $NEO4J_DIR/neo4j-data/data，将使用空数据库启动"
    fi
    
    # 生成便携配置：数据/日志目录跟随项目（Neo4j 要求规范化路径，不能写死绝对路径）
    mkdir -p "$NEO4J_DIR/run" "$NEO4J_DIR/neo4j-data/data" "$NEO4J_DIR/neo4j-data/logs"
    sed -e "s|__NEO4J_DATA_DIR__|$NEO4J_DIR/neo4j-data/data|g" \
        -e "s|__NEO4J_LOG_DIR__|$NEO4J_DIR/neo4j-data/logs|g" \
        "$NEO4J_DIR/conf-template/neo4j.conf" > "$NEO4J_DIR/run/neo4j.conf"
    export NEO4J_CONF="$NEO4J_DIR/run"
    
    # 处理 pid 文件残留：Neo4j 以 pid 文件判断"是否已运行"，
    # 可能进程存在但端口未监听（或 pid 文件失效），导致启动被拒。
    NEO4J_PID_FILE=""
    for candidate in "$NEO4J_HOME/run/neo4j.pid" "$NEO4J_HOME/libexec/run/neo4j.pid"; do
        if [ -f "$candidate" ]; then
            NEO4J_PID_FILE="$candidate"
            break
        fi
    done
    if [ -n "$NEO4J_PID_FILE" ]; then
        OLD_PID=$(head -1 "$NEO4J_PID_FILE" 2>/dev/null | tr -dc '0-9')
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            log_warn "检测到 Neo4j 进程 (pid $OLD_PID) 但 7687 未监听，等待其退出..."
            sleep 8
            if kill -0 "$OLD_PID" 2>/dev/null; then
                log_error "Neo4j 进程 (pid $OLD_PID) 仍在运行但未监听 7687"
                log_error "请先停止该进程：kill $OLD_PID，然后重新运行本脚本"
                exit 1
            fi
            log_warn "旧 Neo4j 进程已退出，继续启动"
        fi
        rm -f "$NEO4J_PID_FILE"
        log_warn "已清理失效的 Neo4j pid 文件"
    fi
    
    # 启动 Neo4j（输出记录到日志，便于失败诊断）
    NEO4J_CONSOLE_LOG="$NEO4J_DIR/neo4j-data/logs/neo4j-console.log"
    cd "$NEO4J_HOME/bin"
    ./neo4j console >> "$NEO4J_CONSOLE_LOG" 2>&1 &
    
    log_info "Neo4j 启动中... (请稍候 15 秒初始化)"
    sleep 15
    
    # 验证连接
    if lsof -Pi :7687 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "✓ Neo4j 已就绪 (neo4j/password)"
    else
        log_error "Neo4j 启动失败，最近日志："
        tail -15 "$NEO4J_CONSOLE_LOG" 2>/dev/null | sed 's/^/  /'
        log_error "完整日志: $NEO4J_CONSOLE_LOG"
        exit 1
    fi
}

# 安装和启动前端/后端
start_app() {
    log_info "启动 MiroFish 应用..."
    
    cd "$APP_DIR"
    
    # 安装前端依赖（如果需要）
    if [ ! -d "frontend/node_modules" ]; then
        log_info "安装前端依赖..."
        npm run setup
    fi
    
    # 安装后端依赖（如果需要）
    if [ ! -d "backend/.venv" ]; then
        log_info "安装后端依赖..."
        npm run setup:backend
    fi
    
    # 创建模拟环境（处理 Neo4j 版本冲突）
    if [ ! -d "backend/.venv-simulation" ]; then
        log_info "创建模拟环境..."
        cd "$APP_DIR/backend"
        uv venv .venv-simulation --python 3.11 2>/dev/null || true
        source .venv-simulation/bin/activate 2>/dev/null || true
        uv pip install camel-oasis==0.2.5 openai python-dotenv 2>/dev/null || true
        deactivate 2>/dev/null || true
        cd "$APP_DIR"
    fi
    
    # 初始化模型配置（导入旧 .env、检查模型库状态）
    if [ -f "$SCRIPT_DIR/init-models.sh" ]; then
        log_info "初始化模型配置..."
        bash "$SCRIPT_DIR/init-models.sh" || log_warn "模型配置初始化未完成，可稍后在网页中手动配置"
    fi
    
    # 启动应用
    log_info "启动前端和后端..."
    # 建图 LLM 并发（属性/摘要调用并行度）：默认 2 保留性能调优；
    # 网关不稳时可用 GRAPHITI_MAX_CONCURRENCY=1 ./scripts/start.sh 降回串行。
    export GRAPHITI_MAX_CONCURRENCY="${GRAPHITI_MAX_CONCURRENCY:-2}"
    npm run dev &
    
    # 等待服务启动
    sleep 5
    
    # 验证端口
    if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null 2>&1 && lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "✓ MiroFish 已就绪"
        log_info "前端: http://localhost:3000"
        log_info "后端: http://localhost:5001"
        log_info "Neo4j: http://localhost:7474"
        log_info "模型设置: 打开前端后点击右下角「模型设置」"
    else
        log_warn "部分端口未监听，请检查日志"
    fi
}

# 清理上一次运行残留的进程（端口 3000/5001 上属于本项目的旧进程）。
# 否则"端口被占用"会导致新后端绑定失败、前端被 concurrently 连带杀掉，
# 表现为"打不开"。只清理本项目进程（run.py/vite/concurrently），
# 不误杀占用同端口的无关程序。
cleanup_previous() {
    log_info "清理上一次运行残留（端口 3000/5001）..."
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
                    log_warn "停止旧进程 pid=$pid (${cmd:0:60})，释放端口 $port"
                    kill "$pid" 2>/dev/null || true
                    ;;
                *)
                    log_warn "端口 $port 被无关进程占用 (${cmd:0:60})，跳过清理"
                    ;;
            esac
        done
    done
    if [ -z "$found" ]; then
        log_info "✓ 无残留进程"
    fi
    # 等待端口释放（最多 10 秒）
    local i
    for i in $(seq 1 10); do
        if ! lsof -nP -iTCP:3000 -sTCP:LISTEN -t >/dev/null 2>&1 &&            ! lsof -nP -iTCP:5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
            log_info "✓ 端口已释放"
            return 0
        fi
        sleep 1
    done
    log_warn "端口未完全释放，将继续尝试启动（若失败请手动检查占用）"
}

# 主程序
main() {
    echo "================================================"
    echo "   MiroFish 可移植部署启动脚本"
    echo "================================================"
    echo ""
    
    check_dependencies
    echo ""
    
    cleanup_previous
    echo ""
    
    start_neo4j
    echo ""
    
    start_app
    echo ""
    
    log_info "所有服务已启动！"
    log_info "按 CTRL+C 停止服务"
    
    # 保持运行
    wait
}

# 错误处理
trap 'log_error "启动失败，清理资源..."; kill $(jobs -p) 2>/dev/null || true; exit 1' ERR

main "$@"
