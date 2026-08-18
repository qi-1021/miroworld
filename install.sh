#!/usr/bin/env bash
# ==============================================================================
# 🐟 Miroworld 一键傻瓜式全自动安装与极速部署脚本 (macOS / Linux)
#
# 用法（一行命令直接运行）：
#   curl -fsSL https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
# 或者（针对国内网络加速）：
#   curl -fsSL https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
# ==============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "====================================================================="
echo "       🐟 Miroworld 一键全自动傻瓜式安装与环境配置程序               "
echo "        (开箱即用 · 零配置依赖门槛 · 国内全生态智能加速)            "
echo "====================================================================="
echo -e "${NC}"

TARGET_DIR="miroworld"
REPO_URL="https://github.com/qi-1021/miroworld.git"
REPO_PROXY_URL="https://ghproxy.net/https://github.com/qi-1021/miroworld.git"

# 1. 检测网络连接并选择最优 GitHub 下载源
echo -e "${BLUE}[1/5] 正在测试并选择最快速的仓库同步通道...${NC}"
CLONE_URL="$REPO_URL"

# 测试直接连接 GitHub 的连通性
if ! curl -Is -m 4 https://github.com >/dev/null 2>&1; then
    echo -e "${YELLOW}[提示] 检测到直连 GitHub 较慢，已自动为您启用国内高速镜像节点加速拉取。${NC}"
    CLONE_URL="$REPO_PROXY_URL"
else
    echo -e "${GREEN}[INFO] GitHub 直连状态良好，使用官方源下载。${NC}"
fi

# 2. 检查 Git 或自动降级为原生 ZIP 归档极速解压
echo -e "${BLUE}[2/5] 正在下载并同步 Miroworld 核心系统源码...${NC}"

if command -v git >/dev/null 2>&1; then
    echo -e "${GREEN}[INFO] 系统已安装 Git，使用 Git 协议同步...${NC}"
    if [ -d "$TARGET_DIR/.git" ]; then
        echo -e "${GREEN}[INFO] 检测到已存在 $TARGET_DIR 项目目录，正在同步至最新代码...${NC}"
        cd "$TARGET_DIR"
        git pull origin main || true
    else
        git clone "$CLONE_URL" "$TARGET_DIR" || git clone "$REPO_PROXY_URL" "$TARGET_DIR"
        cd "$TARGET_DIR"
    fi
else
    echo -e "${YELLOW}[提示] 检测到当前系统未安装 Git，已为您自动启用免 Git 原生 ZIP 极速下载与解压通道...${NC}"
    ZIP_URL="https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    PROXY_ZIP_URL="https://ghproxy.net/https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    ZIP_FILE="miroworld-main.zip"
    
    # 优先使用高速镜像通道下载
    if ! curl -fsSL -m 30 "$PROXY_ZIP_URL" -o "$ZIP_FILE" 2>/dev/null; then
        echo -e "${YELLOW}[提示] 镜像节点重试，尝试官方直连下载...${NC}"
        curl -fsSL -m 60 "$ZIP_URL" -o "$ZIP_FILE" || { echo -e "${RED}[ERROR] 源码包下载失败，请检查网络连接。${NC}"; exit 1; }
    fi
    
    # 自动解压
    echo -e "${BLUE}[STEP] 正在自动解压源码包...${NC}"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIP_FILE"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')"
    elif command -v python >/dev/null 2>&1; then
        python -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')"
    elif command -v tar >/dev/null 2>&1; then
        tar -xzf "$ZIP_FILE" 2>/dev/null || unzip -q -o "$ZIP_FILE"
    else
        echo -e "${RED}[ERROR] 系统缺少解压工具 (unzip / python)，请安装后再试。${NC}"
        exit 1
    fi
    
    if [ -d "miroworld-main" ]; then
        mkdir -p "$TARGET_DIR"
        cp -R miroworld-main/* "$TARGET_DIR/" 2>/dev/null || cp -r miroworld-main/* "$TARGET_DIR/"
        rm -rf miroworld-main "$ZIP_FILE"
    fi
    echo -e "${GREEN}[INFO] 源码包自动解压释放成功！${NC}"
    cd "$TARGET_DIR"
fi

# 3. 赋予脚本执行权限
echo -e "${BLUE}[3/5] 配置脚本运行权限与环境探针...${NC}"
chmod +x *.sh scripts/*.sh 2>/dev/null || true

# 4. 执行全自动环境就绪与静默安装
echo -e "${BLUE}[4/5] 正在全自动配置 Python 依赖、Node.js 前端与 Neo4j 数据库组件...${NC}"
echo -e "${CYAN}（首次安装将自动下载配置隔离运行环境，国内环境已自动开启清华源/npm加速，无需人工干预）${NC}"

if [ -f "./scripts/setup-env.sh" ]; then
    bash ./scripts/setup-env.sh
fi

# 5. 安装完成指引
echo ""
echo -e "${GREEN}====================================================================="
echo -e "  🎉 恭喜！Miroworld 已全部安装配置就绪！"
echo -e "=====================================================================${NC}"
echo -e "👉 ${YELLOW}进入项目目录并一键启动服务：${NC}"
echo -e "   ${CYAN}cd $TARGET_DIR && ./start.sh${NC}"
echo ""
echo -e "🌐 ${YELLOW}启动后浏览器直接访问：${NC}"
echo -e "   - 🎨 前端工作台: ${CYAN}http://localhost:3000${NC}"
echo -e "   - ⚙️ 后端 API:    ${CYAN}http://localhost:5001${NC}"
echo -e "   - 🗄️ 图数据库:    ${CYAN}http://localhost:7474${NC}"
echo -e "====================================================================="
