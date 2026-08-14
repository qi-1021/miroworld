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
}

# 检查并启动 Neo4j
start_neo4j() {
    log_info "启动 Neo4j..."
    
    # 检查 Neo4j 是否已经运行
    if lsof -Pi :7687 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_warn "Neo4j 已在监听端口 7687"
        return 0
    fi
    
    # 检查 Neo4j 是否存在
    if [ ! -d "$NEO4J_DIR/neo4j" ]; then
        log_error "Neo4j 未安装。请运行 ./scripts/install-neo4j.sh"
        exit 1
    fi
    
    # 启动 Neo4j
    cd "$NEO4J_DIR/neo4j/bin"
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        ./neo4j console &
    else
        # Linux
        ./neo4j console &
    fi
    
    log_info "Neo4j 启动中... (请稍候 10 秒初始化)"
    sleep 10
    
    # 验证连接
    if lsof -Pi :7687 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_info "✓ Neo4j 已就绪 (neo4j/password)"
    else
        log_error "Neo4j 启动失败"
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

# 主程序
main() {
    echo "================================================"
    echo "   MiroFish 可移植部署启动脚本"
    echo "================================================"
    echo ""
    
    check_dependencies
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
