#!/bin/bash
# Miroworld 可移植部署 - 主启动脚本 (macOS/Linux)
#
# 统一入口：本脚本吸收 quick-start.sh 的"独立启动 + 逐服务端口校验 + 失败引导"逻辑，
# quick-start.sh 已收敛为指向本脚本的薄包装（见文件末尾提示）。
#
# 用法：
#   bash scripts/start.sh
#   GRAPHITI_MAX_CONCURRENCY=1 bash scripts/start.sh   # 网关不稳时降回串行建图
#
# 说明：
#   - 前端/后端各自独立后台启动并写入独立日志（app/backend/logs/），失败即退出并给排查引导，
#     避免"脚本提示已就绪但页面打不开"的端口失效问题。
#   - 保持前台运行：按 CTRL+C 或新开终端执行 bash scripts/stop.sh 停止。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"
NEO4J_DIR="$PROJECT_ROOT/neo4j"

# 独立日志目录（已被 .gitignore 忽略），前后端各一份，便于失败诊断
LOG_DIR="$APP_DIR/backend/logs"
BACKEND_LOG="$LOG_DIR/start-backend.log"
FRONTEND_LOG="$LOG_DIR/start-frontend.log"

# 建图 LLM 并发（属性/摘要调用并行度）：默认 2 保留性能调优；
# 网关不稳时可用 GRAPHITI_MAX_CONCURRENCY=1 bash scripts/start.sh 降回串行。
export GRAPHITI_MAX_CONCURRENCY="${GRAPHITI_MAX_CONCURRENCY:-2}"

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

# 端口是否在监听
port_listening() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

# 逐服务等待端口就绪；超时则打印日志尾部 + 排查引导并退出（避免"打不开"的端口失效）
# 用法: wait_for_port <端口> <服务名> <日志文件>
wait_for_port() {
    local port="$1" name="$2" logfile="$3" i
    for i in $(seq 1 12); do
        if port_listening "$port"; then
            log_info "✓ $name 已就绪（http://localhost:${port}）"
            return 0
        fi
        sleep 1
    done
    log_error "$name 启动失败（端口 $port 未监听）"
    echo ""
    echo "  最近日志（tail -n 40 ${logfile}）："
    echo ""
    tail -n 40 "$logfile" 2>/dev/null | sed 's/^/    /'
    echo ""
    echo "  实时查看：  tail -f $logfile"
    echo "  常见原因与处理："
    echo "    - 端口 $port 被无关进程占用    → lsof -i :$port （确认后 kill 该进程）"
    echo "    - 依赖/环境不完整            → 运行 bash scripts/setup-env.sh 重新搭建"
    echo "    - 后端连接 Neo4j 失败        → 确认上方 Neo4j 已就绪、app/.env 配置正确"
    echo ""
    exit 1
}

# 自动安装/就绪工具环境
ensure_command() {
    local cmd="$1"
    local install_msg="$2"
    if ! command -v "$cmd" &> /dev/null; then
        log_warn "$cmd 未找到，正在自动准备..."
        return 1
    fi
    return 0
}

# 检查与自动安装所有前置依赖（傻瓜式一键就绪，用户无需手动操作）
check_and_auto_install_dependencies() {
    log_info "检查并自动准备运行环境 (已启用国内镜像自动加速)..."

    # 国内多源加速与容灾备选（阿里云 / 清华大学 / 华为云 / 腾讯云 / 中科大）
    export UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
    export UV_EXTRA_INDEX_URL="${UV_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"
    export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
    export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.huaweicloud.com/repository/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/ https://pypi.mirrors.ustc.edu.cn/simple/}"
    export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"

    # 1. 确保 uv 存在（uv 可以管理独立 Python 与虚拟环境）
    if ! command -v uv &> /dev/null; then
        # 优先检查本地用户目录中的 uv
        if [ -f "$HOME/.cargo/bin/uv" ]; then
            export PATH="$HOME/.cargo/bin:$PATH"
        elif [ -f "$HOME/.local/bin/uv" ]; then
            export PATH="$HOME/.local/bin:$PATH"
        else
            log_info "正在自动安装 uv 包管理工具..."
            # 官方源 + 国内 GitHub 加速镜像重试
            curl -LsSf https://astral.sh/uv/install.sh | sh || curl -LsSf https://mirror.ghproxy.com/https://raw.githubusercontent.com/astral-sh/uv/main/install.sh | sh || true
            export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
        fi
    fi
    if command -v uv &> /dev/null; then
        log_info "✓ uv $(uv --version)"
    else
        log_warn "uv 自动安装未就绪，将尝试使用系统 Python"
    fi

    # 2. 检查并准备 Python 3.10+
    if ! command -v python3 &> /dev/null; then
        log_info "未检测到系统 Python3，正在由 uv 自动准备 Python 3.11..."
        if command -v uv &> /dev/null; then
            uv python install 3.11 || true
        fi
    fi
    if command -v python3 &> /dev/null; then
        log_info "✓ Python3 $(python3 --version 2>&1)"
    elif command -v uv &> /dev/null; then
        log_info "✓ Python 将由 uv 自动托管运行"
    else
        log_error "Python 自动获取失败，请确保系统联网"
        exit 1
    fi

    # 3. 检查并准备 Node.js
    if ! command -v node &> /dev/null; then
        log_warn "Node.js 未安装，尝试自动通过包管理器准备..."
        if command -v brew &> /dev/null; then
            brew install node || true
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y nodejs npm || true
        elif command -v yum &> /dev/null; then
            sudo yum install -y nodejs npm || true
        fi
    fi
    if command -v node &> /dev/null; then
        log_info "✓ Node.js $(node --version)"
    else
        log_error "Node.js 自动准备失败。请访问 https://nodejs.org 安装 Node.js (>=18.0)"
        exit 1
    fi

    # 4. 检查并准备 Java 17+ (Neo4j 所需 JVM)
    if ! command -v java &> /dev/null; then
        log_warn "Java 未安装，正在自动通过包管理器准备 OpenJDK 17..."
        if command -v brew &> /dev/null; then
            brew install openjdk@17 || true
            if [ -d "/opt/homebrew/opt/openjdk@17/bin" ]; then
                export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"
            elif [ -d "/usr/local/opt/openjdk@17/bin" ]; then
                export PATH="/usr/local/opt/openjdk@17/bin:$PATH"
            fi
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y openjdk-17-jre-headless || true
        elif command -v yum &> /dev/null; then
            sudo yum install -y java-17-openjdk || true
        fi
    fi
    if command -v java &> /dev/null; then
        JAVA_VER=$(java -version 2>&1 | head -1 | sed 's/.*version "//;s/".*//')
        log_info "✓ Java $JAVA_VER"
    else
        log_error "Java 17+ 自动准备失败。Neo4j 需要 JVM，请通过 Homebrew 或官网安装 OpenJDK 17"
        exit 1
    fi
}

# 检查依赖别名封装
check_dependencies() {
    check_and_auto_install_dependencies
}

# 检查并启动 Neo4j
start_neo4j() {
    log_info "检查与启动 Neo4j 知识图谱数据库..."

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
    if port_listening 7687; then
        log_info "✓ Neo4j 已在监听端口 7687，跳过启动"
        return 0
    fi

    # 兼容两种安装布局：neo4j/neo4j（安装脚本默认）或 neo4j/neo4j-program（已有便携部署）
    NEO4J_HOME="$NEO4J_DIR/neo4j"
    if [ ! -d "$NEO4J_HOME" ] && [ -d "$NEO4J_DIR/neo4j-program" ]; then
        NEO4J_HOME="$NEO4J_DIR/neo4j-program"
        log_info "检测到 Neo4j 安装在 $NEO4J_HOME"
    fi

    # 自动傻瓜式下载与安装 Neo4j（用户第一次运行无需手动执行 install-neo4j.sh）
    if [ ! -d "$NEO4J_HOME" ]; then
        log_info "未检测到本地 Neo4j，正在自动通过国内多源加速下载并部署 Neo4j 5.26.0 便携版..."
        mkdir -p "$NEO4J_DIR"
        local os_type=$(uname -s)
        local neo4j_urls=(
            "https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz"
            "https://mirrors.huaweicloud.com/neo4j/neo4j-community-5.26.0-unix.tar.gz"
            "https://mirror.iscas.ac.cn/neo4j/neo4j-community-5.26.0-unix.tar.gz"
        )
        local dl_ok=0
        for u in "${neo4j_urls[@]}"; do
            log_info "尝试从加速节点获取: $u"
            if curl -L --connect-timeout 10 -m 300 -o "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz" "$u"; then
                if [ -s "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz" ] && tar -tzf "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz" >/dev/null 2>&1; then
                    dl_ok=1
                    log_info "✓ 下载成功！"
                    break
                fi
            fi
            rm -f "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz"
        done
        if [ "$dl_ok" -ne 1 ]; then
            log_error "所有 Neo4j 下载节点均失败，请检查网络连接"
            exit 1
        fi
        tar -xzf "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz" -C "$NEO4J_DIR"
        mv "$NEO4J_DIR/neo4j-community-5.26.0" "$NEO4J_HOME"
        rm -f "$NEO4J_DIR/neo4j-5.26.0-unix.tar.gz"
        log_info "✓ Neo4j 便携版自动安装就绪"
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

    # 处理 pid 文件与僵死残留进程：全自动自愈强杀，绝不报错退出打断用户流程
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
            log_warn "检测到上次残留的 Neo4j 进程 (pid $OLD_PID) 未监听 7687，正在自动自愈清理..."
            kill "$OLD_PID" 2>/dev/null || true
            sleep 2
            if kill -0 "$OLD_PID" 2>/dev/null; then
                kill -9 "$OLD_PID" 2>/dev/null || true
                sleep 1
            fi
            log_info "✓ 已自动安全清理残留 Neo4j 进程 (pid $OLD_PID)"
        fi
        rm -f "$NEO4J_PID_FILE"
        log_info "✓ 已自动重置 Neo4j pid 状态文件"
    fi

    # 启动 Neo4j（输出记录到日志，便于失败诊断）
    NEO4J_CONSOLE_LOG="$NEO4J_DIR/neo4j-data/logs/neo4j-console.log"
    cd "$NEO4J_HOME/bin"
    ./neo4j console >> "$NEO4J_CONSOLE_LOG" 2>&1 &

    log_info "Neo4j 启动中... (请稍候 15 秒初始化)"
    sleep 15

    # 验证连接
    if port_listening 7687; then
        log_info "✓ Neo4j 已就绪 (neo4j/password)"
    else
        log_error "Neo4j 启动失败，最近日志："
        tail -15 "$NEO4J_CONSOLE_LOG" 2>/dev/null | sed 's/^/  /'
        log_error "完整日志: $NEO4J_CONSOLE_LOG"
        exit 1
    fi
}

# 安装和启动前端/后端（独立启动 + 逐服务端口校验，见 wait_for_port）
start_app() {
    log_info "启动 Miroworld 应用..."
    mkdir -p "$LOG_DIR"

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
        if ! uv venv .venv-simulation --python 3.11; then
            log_error "创建模拟 Python 环境失败，请检查 uv/网络"
            exit 1
        fi
        if ! source .venv-simulation/bin/activate; then
            log_error "激活模拟 Python 环境失败"
            exit 1
        fi
        if ! uv pip install camel-oasis==0.2.5 openai python-dotenv; then
            log_error "安装模拟环境依赖失败（camel-oasis 等），请检查网络/版本"
            exit 1
        fi
        deactivate
        cd "$APP_DIR"
    fi

    # 初始化模型配置（导入旧 .env、检查模型库状态）
    if [ -f "$SCRIPT_DIR/init-models.sh" ]; then
        log_info "初始化模型配置..."
        bash "$SCRIPT_DIR/init-models.sh" || log_warn "模型配置初始化未完成，可稍后在网页中手动配置"
    fi

    # 启动后端（独立后台 + 独立日志）
    # 注意：不要用 `uv run python run.py` —— 它会触发 uv 重新解析依赖，
    # 而 pyproject 中 graphiti/oasis 两个 extra 声明了互相冲突的 neo4j 版本，
    # 导致 "No solution found" 解析失败。这里直接使用已同步好的 .venv 解释器，
    # 与 setup-env.sh / init-models.sh 保持一致，绕过 uv 解析。
    log_info "启动后端 (Flask) → 日志 $BACKEND_LOG"
    cd "$APP_DIR/backend"
    if [ ! -x ".venv/bin/python" ]; then
        log_error "未找到 backend/.venv/bin/python。请先运行 bash scripts/setup-env.sh 搭建环境"
        exit 1
    fi
    nohup .venv/bin/python run.py > "$BACKEND_LOG" 2>&1 &
    BACKEND_PID=$!
    wait_for_port 5001 "后端" "$BACKEND_LOG"

    # 启动前端（独立后台 + 独立日志）
    log_info "启动前端 (Vue3) → 日志 $FRONTEND_LOG"
    cd "$APP_DIR/frontend"
    nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
    FRONTEND_PID=$!
    wait_for_port 3000 "前端" "$FRONTEND_LOG"

    echo ""
    log_info "所有服务已就绪！"
    log_info "前端:   http://localhost:3000"
    log_info "后端:   http://localhost:5001 (健康检查 /health)"
    log_info "Neo4j:  http://localhost:7474 (neo4j/password)"
    log_info "模型设置: 打开前端后点击右下角「模型设置」"
    echo ""
    log_info "日志文件（失败/异常时查看）："
    log_info "  后端: tail -f $BACKEND_LOG"
    log_info "  前端: tail -f $FRONTEND_LOG"
    echo ""
    log_info "停止服务: 按 CTRL+C，或另开终端执行 bash scripts/stop.sh（可加 --neo4j / --all）"
}

# 清理上一次运行残留的进程（端口 3000/5001 上属于本项目的旧进程）。
# 否则"端口被占用"会导致新后端绑定失败、前端被连带杀掉，表现为"打不开"。
# 只清理本项目进程（run.py/vite/concurrently/npm run dev），不误杀占用同端口的无关程序。
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

    # 同时清理上次遗留的模拟子进程（它们通常不监听 3000/5001，
    # 但会继续占内存/CPU；按工作目录识别本项目进程）
    for pat in "run_world_simulation.py" "run_parallel_simulation.py" \
               "run_reddit_simulation.py" "run_twitter_simulation.py"; do
        for pid in $(pgrep -f "$pat" 2>/dev/null || true); do
            cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep '^n' | head -1 | cut -c2-)
            case "$cwd" in
                "$PROJECT_ROOT"*)
                    log_warn "停止遗留模拟子进程 pid=${pid}（$(ps -p $pid -o command= | tail -1 | cut -c1-60)）"
                    kill "$pid" 2>/dev/null || true
                    ;;
            esac
        done
    done

    # 等待端口释放（最多 15 秒）
    local i
    for i in $(seq 1 15); do
        if ! port_listening 3000 && ! port_listening 5001; then
            log_info "✓ 端口已释放"
            return 0
        fi
        sleep 1
    done
    # 超时后强制结束仍占用的本项目进程
    for port in 3000 5001; do
        for pid in $(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true); do
            cmd=$(ps -p "$pid" -o command= 2>/dev/null | head -1)
            case "$cmd" in
                *mirofish-portable*|*run.py*|*vite*|*concurrently*|*npm*run*dev*)
                    log_warn "端口 $port 仍被本项目进程占用，强制结束 pid=$pid"
                    kill -9 "$pid" 2>/dev/null || true
                    ;;
            esac
        done
    done
    sleep 2
    log_warn "端口未完全释放，将继续尝试启动（若失败请手动检查占用：lsof -i :3000 -i :5001）"
}

# 主程序
main() {
    echo "================================================"
    echo "   Miroworld 可移植部署启动脚本"
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

    # 保持前台运行，使 CTRL+C 可停止全部服务
    wait
}

# 错误处理
trap 'echo -e "${RED}[ERROR]${NC} 启动失败，清理资源..."; kill $(jobs -p) 2>/dev/null || true; exit 1' ERR

main "$@"
