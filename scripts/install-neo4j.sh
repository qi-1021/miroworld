#!/bin/bash
# Neo4j 自动下载和安装脚本 (macOS/Linux)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NEO4J_DIR="$PROJECT_ROOT/neo4j"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否已安装
if [ -d "$NEO4J_DIR/neo4j" ]; then
    log_warn "Neo4j 已安装在 $NEO4J_DIR/neo4j"
    read -p "是否重新安装? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "取消安装"
        exit 0
    fi
    rm -rf "$NEO4J_DIR/neo4j"
fi

# 创建下载目录
mkdir -p "$NEO4J_DIR"
cd "$NEO4J_DIR"

# 检测系统和架构
OS_TYPE=$(uname -s)
ARCH=$(uname -m)

if [[ "$OS_TYPE" == "Darwin" ]]; then
    if [[ "$ARCH" == "arm64" ]]; then
        # macOS ARM64 (Apple Silicon)
        NEO4J_URL="https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz"
    else
        # macOS x86-64 (Intel)
        NEO4J_URL="https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz"
    fi
elif [[ "$OS_TYPE" == "Linux" ]]; then
    # Linux
    NEO4J_URL="https://dist.neo4j.org/neo4j-community-5.26.0-unix.tar.gz"
else
    log_error "不支持的操作系统: $OS_TYPE"
    exit 1
fi

log_info "下载 Neo4j 5.26.0..."
log_info "URL: $NEO4J_URL"

# 下载
if ! curl -L -o neo4j-5.26.0-unix.tar.gz "$NEO4J_URL"; then
    log_error "下载失败"
    exit 1
fi

log_info "解压..."
tar -xzf neo4j-5.26.0-unix.tar.gz

# 重命名
mv neo4j-community-5.26.0 neo4j

log_info "清理安装文件..."
rm neo4j-5.26.0-unix.tar.gz

# 设置密码
log_info "设置 Neo4j 密码..."
cd neo4j
./bin/neo4j-admin dbms set-initial-password password 2>/dev/null || log_warn "密码设置命令可能需要手动执行"

cd ..

# 验证安装
if [ -f "neo4j/bin/neo4j" ]; then
    log_info "✓ Neo4j 安装完成！"
    log_info "位置: $NEO4J_DIR/neo4j"
    log_info ""
    log_info "下次启动脚本时会自动启动 Neo4j"
else
    log_error "安装验证失败"
    exit 1
fi
