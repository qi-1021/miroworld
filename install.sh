#!/usr/bin/env bash
# ==============================================================================
# 🐟 Miroworld 一键傻瓜式全自动安装与极速部署脚本 (macOS / Linux)
#
# 用法（一行命令直接运行）：
#   curl -fsSL https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
# 或者（针对国内网络加速）：
#   curl -fsSL https://ghproxy.net/https://raw.githubusercontent.com/qi-1021/miroworld/main/install.sh | bash
#
# 特性：
#   - 全流程写入安装日志 logs/install.log，方便诊断
#   - 下载自动重试（断点续传 + 退避重试），网络抖动不再中断安装
#   - 安装前自动体检（磁盘 / 网络 / 端口 / 工具版本）
#   - 失败时给出友好中文提示与下一步指引
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

# ------------------------------------------------------------------------------
# 安装日志（logs/install.log）
# ------------------------------------------------------------------------------
PROJECT_ROOT="$(pwd -P)"                       # 本次安装的运行目录
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/install.log"
if mkdir -p "$LOG_DIR" 2>/dev/null; then
    echo -e "${BLUE}[STEP]${NC} 安装日志将写入: $LOG_FILE"
else
    echo -e "${YELLOW}[WARN]${NC} 无法创建日志目录: $LOG_DIR（将继续安装，但无法保存日志）"
fi

# 追加带时间戳的日志行（日志写入失败不影响安装主流程）
log_to_file() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE" 2>/dev/null || true
}

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; log_to_file "[INFO] $1"; }
log_step()  {
    local step="$1"
    local status="${2:-}"
    echo -e "${BLUE}[STEP]${NC} $step"
    if [ -n "$status" ]; then log_to_file "[STEP] $step [${status}]"; else log_to_file "[STEP] $step"; fi
}
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; log_to_file "[WARN] $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; log_to_file "[ERROR] $1"; }

# 友好失败出口：打印原因 / 日志路径 / 下一步指引
fail() {
    local reason="$1"
    local detail="${2:-}"
    log_to_file "[ERROR] 安装失败: ${reason} ${detail}"
    echo ""
    echo -e "${RED}=====================================================================${NC}"
    echo -e "${RED}  ❌ 安装失败: ${reason}${NC}"
    if [ -n "$detail" ]; then
        echo -e "${YELLOW}  原因: ${detail}${NC}"
    fi
    echo -e "${YELLOW}  📄 详细日志: ${LOG_FILE}${NC}"
    echo -e "${YELLOW}  📮 请将此日志文件发送给维护者（微信/邮件均可），我们会帮您尽快解决。${NC}"
    echo -e "${RED}=====================================================================${NC}"
    log_to_file "[END] 安装失败，总耗时 ${SECONDS:-?} 秒"
    exit 1
}

# 兜底：任何未捕获的意外失败也会给出友好提示
trap 'fail "安装过程遇到意外错误" "请查看上方错误提示或安装日志"' ERR

# ------------------------------------------------------------------------------
# 重试下载：断点续传 + 指数退避
# 用法：retry_download <url> <输出文件> [最大尝试次数=3] [单次超时=60]
# ------------------------------------------------------------------------------
retry_download() {
    local url="$1"
    local output="$2"
    local max_attempts="${3:-3}"
    local timeout="${4:-60}"
    local attempt rc out
    out="$(mktemp)" || return 1
    for attempt in $(seq 1 "$max_attempts"); do
        echo -e "${BLUE}[STEP]${NC} 正在下载（第 ${attempt}/${max_attempts} 次尝试）..."
        log_to_file "[CMD] curl -fSL -C - -m ${timeout} ${url} -> ${output}"
        if curl -fSL -C - --retry 2 --retry-delay 3 -m "$timeout" "$url" -o "$output" >"$out" 2>&1; then
            log_step "下载完成: $output" "ok"
            rm -f "$out" || true
            return 0
        fi
        rc=$?
        if [ "$attempt" -lt "$max_attempts" ]; then
            local wait=$((2 ** attempt))
            log_warn "下载失败，${attempt}/${max_attempts}，${wait}秒后重试..."
            log_to_file "[CMD] 下载失败，退出码: $rc"
            tail -n 10 "$out" >> "$LOG_FILE" 2>/dev/null || true
            sleep "$wait"
        fi
    done
    log_to_file "[CMD] 下载最终失败，退出码: $rc，最后 10 行输出:"
    tail -n 10 "$out" >> "$LOG_FILE" 2>/dev/null || true
    echo -e "${RED}[ERROR]${NC} 下载失败，最近输出："
    tail -n 10 "$out" 2>/dev/null || true
    rm -f "$out" || true
    log_error "下载失败: $url (已重试${max_attempts}次)"
    return 1
}

# ------------------------------------------------------------------------------
# 通用命令重试：retry_run <次数> <描述> <命令...>
# 失败时记录命令、退出码与最后 10 行输出
# ------------------------------------------------------------------------------
retry_run() {
    local max_attempts="$1"
    local desc="$2"
    shift 2
    local attempt rc out
    out="$(mktemp)" || return 1
    for attempt in $(seq 1 "$max_attempts"); do
        echo -e "${BLUE}[STEP]${NC} ${desc}（第 ${attempt}/${max_attempts} 次尝试）..."
        log_to_file "[CMD] $*"
        if "$@" >"$out" 2>&1; then
            log_step "${desc}完成" "ok"
            rm -f "$out" || true
            return 0
        fi
        rc=$?
        if [ "$attempt" -lt "$max_attempts" ]; then
            local wait=$((2 ** attempt))
            log_warn "${desc} 失败，${attempt}/${max_attempts}，${wait}秒后重试..."
            log_to_file "[CMD] ${desc} 失败，退出码: $rc"
            sleep "$wait"
        fi
    done
    log_to_file "[CMD] ${desc} 最终失败，退出码: $rc，最后 10 行输出:"
    tail -n 10 "$out" >> "$LOG_FILE" 2>/dev/null || true
    echo -e "${RED}[ERROR]${NC} ${desc} 失败，最近输出："
    tail -n 10 "$out" 2>/dev/null || true
    rm -f "$out" || true
    return 1
}

# ------------------------------------------------------------------------------
# 免 Git 模式下需要保护的本地目录/文件（不覆盖用户已有数据与配置）
# ------------------------------------------------------------------------------
EXCLUDES=("data" "neo4j" "logs" ".env" "model-config" ".venv" "node_modules" ".git")

# 判断路径是否命中受保护路径（任意一层目录名匹配即跳过）
path_is_excluded() {
    local relpath="$1"
    local comp ex comps
    IFS='/' read -r -a comps <<< "$relpath"
    for comp in "${comps[@]}"; do
        for ex in "${EXCLUDES[@]}"; do
            if [ "$comp" = "$ex" ]; then
                return 0
            fi
        done
    done
    return 1
}

# 覆盖复制源码树，自动跳过受保护路径（含隐藏文件，如 .env/.git）
copy_tree_with_excludes() {
    local src="$1"
    local dst="$2"
    local item base relpath

    # 优先使用 rsync（macOS / Linux 均常见）
    if command -v rsync >/dev/null 2>&1; then
        local args=(-a)
        local ex
        for ex in "${EXCLUDES[@]}"; do
            args+=("--exclude=$ex")
        done
        if rsync "${args[@]}" "$src/" "$dst/"; then
            return 0
        fi
    fi

    # 兜底：手动逐个复制（包含隐藏文件），跳过受保护路径
    for item in "$src"/* "$src"/.[!.]* "$src"/..?*; do
        [ -e "$item" ] || continue
        base="$(basename "$item")"
        relpath="$base"
        if path_is_excluded "$relpath"; then
            log_info "已跳过本地数据/配置: $relpath"
            continue
        fi
        if [ -d "$item" ]; then
            mkdir -p "$dst/$base"
            copy_tree_with_excludes "$item" "$dst/$base"
        else
            cp -f "$item" "$dst/$base" 2>/dev/null || cp "$item" "$dst/$base"
        fi
    done
    return 0
}

# ------------------------------------------------------------------------------
# 环境体检（安装前预检）
# ------------------------------------------------------------------------------
preflight_check() {
    log_step "环境体检（磁盘 / 网络 / 端口 / 工具版本）..."
    log_to_file "操作系统: $(uname -srm 2>/dev/null || echo 未知)"
    log_to_file "Shell: $(bash --version 2>/dev/null | head -1 || echo 未知)"

    # 磁盘空间（建议 ≥ 2GB）
    local disk_free_mb
    disk_free_mb="$(df -m . 2>/dev/null | awk 'NR==2 {print $4}')"
    if [ -n "$disk_free_mb" ]; then
        if [ "$disk_free_mb" -lt 2048 ]; then
            log_warn "磁盘剩余空间仅 ${disk_free_mb} MB（建议至少 2GB），安装可能因空间不足失败"
        else
            log_info "磁盘剩余空间充足: ${disk_free_mb} MB"
        fi
    else
        log_warn "无法读取磁盘剩余空间"
    fi

    # 网络连通性（GitHub 直连）
    if curl -fsSL -m 5 https://github.com -o /dev/null 2>/dev/null; then
        log_info "网络连通性良好（GitHub 直连可达）"
        NET_OK=1
    else
        log_warn "GitHub 直连不可达，将自动启用国内镜像加速节点"
        NET_OK=0
    fi

    # 常用端口占用检查
    for port in 3000 5001 7687; do
        if (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1; then
            log_warn "端口 $port 已被占用（若有旧版服务在运行，可能造成冲突）"
        else
            log_info "端口 $port 空闲"
        fi
    done

    # 工具版本
    if command -v git >/dev/null 2>&1; then
        log_info "Git: $(git --version 2>&1)"
    else
        log_warn "未检测到 Git，将自动启用免 Git ZIP 下载通道"
    fi
    if command -v python3 >/dev/null 2>&1; then
        log_info "Python: $(python3 --version 2>&1)"
    else
        log_warn "未检测到 python3"
    fi
    if command -v node >/dev/null 2>&1; then
        log_info "Node: $(node --version 2>&1)"
    else
        log_warn "未检测到 Node.js（如缺少将由安装流程自动处理）"
    fi
    log_step "环境体检完成" "ok"
}

echo -e "${CYAN}"
echo "====================================================================="
echo "       🐟 Miroworld 一键全自动傻瓜式安装与环境配置程序               "
echo "        (开箱即用 · 零配置依赖门槛 · 国内全生态智能加速)            "
echo "====================================================================="
echo -e "${NC}"

# 安装计时与日志起点
SECONDS=0
log_to_file "===== Miroworld 一键安装开始 ====="
log_to_file "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
log_to_file "安装目录: $PROJECT_ROOT"
log_to_file "Git: $(git --version 2>&1 || echo 未安装)"
log_to_file "Python3: $(python3 --version 2>&1 || echo 未安装)"
log_to_file "Node: $(node --version 2>&1 || echo 未安装)"

TARGET_DIR="miroworld"
REPO_URL="https://github.com/qi-1021/miroworld.git"
REPO_PROXY_URL="https://ghproxy.net/https://github.com/qi-1021/miroworld.git"

# 0. 安装前环境体检
preflight_check

# 1. 检测网络连接并选择最优 GitHub 下载源
echo -e "${BLUE}[1/6] 正在测试并选择最快速的仓库同步通道...${NC}"
CLONE_URL="$REPO_URL"

# 测试直接连接 GitHub 的连通性
if [ "$NET_OK" = "1" ]; then
    echo -e "${GREEN}[INFO] GitHub 直连状态良好，使用官方源下载。${NC}"
    CLONE_URL="$REPO_URL"
else
    echo -e "${YELLOW}[提示] 检测到直连 GitHub 较慢，已自动为您启用国内高速镜像节点加速拉取。${NC}"
    CLONE_URL="$REPO_PROXY_URL"
fi

# 2. 检查 Git 或自动降级为原生 ZIP 归档极速解压
echo -e "${BLUE}[2/6] 正在下载并同步 Miroworld 核心系统源码...${NC}"

if command -v git >/dev/null 2>&1; then
    echo -e "${GREEN}[INFO] 系统已安装 Git，使用 Git 协议同步...${NC}"
    if [ -d "$TARGET_DIR/.git" ]; then
        echo -e "${GREEN}[INFO] 检测到已存在 $TARGET_DIR 项目目录，正在同步至最新代码...${NC}"
        if ! (cd "$TARGET_DIR" && git pull origin main); then
            log_warn "代码同步未完成（可稍后运行 update.sh 手动更新），继续安装..."
        fi
        cd "$TARGET_DIR"
    else
        log_step "正在克隆仓库: $CLONE_URL"
        if ! retry_run 3 "Git 克隆源码" git clone "$CLONE_URL" "$TARGET_DIR"; then
            log_warn "官方源克隆失败，正在尝试国内镜像加速源..."
            if ! retry_run 3 "Git 镜像克隆" git clone "$REPO_PROXY_URL" "$TARGET_DIR"; then
                fail "源码下载失败" "请检查网络连接后重新运行安装脚本"
            fi
        fi
        cd "$TARGET_DIR"
    fi
else
    echo -e "${YELLOW}[提示] 检测到当前系统未安装 Git，已为您自动启用免 Git 原生 ZIP 极速下载与解压通道...${NC}"
    ZIP_URL="https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    PROXY_ZIP_URL="https://ghproxy.net/https://github.com/qi-1021/miroworld/archive/refs/heads/main.zip"
    ZIP_FILE="miroworld-main.zip"

    # 优先使用高速镜像通道下载（自动重试）
    log_step "正在从高速镜像节点下载源码归档包..."
    if ! retry_download "$PROXY_ZIP_URL" "$ZIP_FILE" 3 60; then
        echo -e "${YELLOW}[提示] 镜像节点重试，尝试官方直连下载...${NC}"
        if ! retry_download "$ZIP_URL" "$ZIP_FILE" 3 60; then
            fail "源码包下载失败" "请检查网络连接后重新运行安装脚本"
        fi
    fi

    # 自动解压
    log_step "正在自动解压源码包..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIP_FILE" || fail "源码包解压失败" "下载的文件可能已损坏，请重新运行安装脚本"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')" || fail "源码包解压失败" "下载的文件可能已损坏，请重新运行安装脚本"
    elif command -v python >/dev/null 2>&1; then
        python -c "import zipfile; zipfile.ZipFile('$ZIP_FILE').extractall('.')" || fail "源码包解压失败" "下载的文件可能已损坏，请重新运行安装脚本"
    elif command -v tar >/dev/null 2>&1; then
        if ! tar -xzf "$ZIP_FILE" 2>/dev/null && ! unzip -q -o "$ZIP_FILE" 2>/dev/null; then
            fail "源码包解压失败" "系统缺少可用的解压工具 (unzip / python)"
        fi
    else
        fail "系统缺少解压工具" "请先安装 unzip 或 python 后再运行安装脚本"
    fi

    if [ -d "miroworld-main" ]; then
        mkdir -p "$TARGET_DIR"
        log_step "正在同步源码（已自动保护本地数据与配置）..."
        if ! copy_tree_with_excludes "miroworld-main" "$TARGET_DIR"; then
            fail "源码目录复制失败" "请检查磁盘空间与目录权限后重试"
        fi
        rm -rf miroworld-main "$ZIP_FILE" 2>/dev/null || log_warn "清理临时文件失败（可忽略）"
    else
        fail "源码包解压失败" "未找到解压后的源码目录，请重新运行安装脚本"
    fi
    log_step "源码包自动解压释放成功" "ok"
    cd "$TARGET_DIR"
fi

# 3. 赋予脚本执行权限
echo -e "${BLUE}[3/6] 配置脚本运行权限与环境探针...${NC}"
chmod +x *.sh scripts/*.sh 2>/dev/null || log_warn "设置脚本执行权限失败（通常可忽略）"

# 4. 执行全自动环境就绪与静默安装
echo -e "${BLUE}[4/6] 正在全自动配置 Python 依赖、Node.js 前端与 Neo4j 数据库组件...${NC}"
echo -e "${CYAN}（首次安装将自动下载配置隔离运行环境，国内环境已自动开启清华源/npm加速，无需人工干预）${NC}"

if [ -f "./scripts/setup-env.sh" ]; then
    export MIROWORLD_LOG_FILE="$LOG_FILE"
    if ! bash ./scripts/setup-env.sh; then
        fail "环境配置失败" "Python 依赖或前端构建失败，请查看上方错误提示"
    fi
else
    log_warn "未找到 scripts/setup-env.sh，跳过依赖环境自动配置"
fi

# 5. 安装完成指引
log_step "安装完成" "ok"
log_to_file "[END] ===== 安装完成，总耗时 ${SECONDS} 秒 ====="
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
echo -e "${GREEN}====================================================================="
echo -e "${YELLOW}📄 安装日志已保存至: ${LOG_FILE}${NC}"
echo -e "${GREEN}=====================================================================${NC}"
