#!/bin/bash
# ==============================================================================
# Miroworld 一键更新脚本 (macOS / Linux)
# 特性：
#   - 采用 HTTPS 公共拉取，无需 SSH Key 或 GitHub Token 凭证
#   - 自动检测代理与本地代理工具，智能选择最快镜像源
#   - 自动检测并拉取 GitHub 仓库最新代码 (git pull)
#   - 免 Git 模式支持版本检查、断点续传、校验与本地数据保护
#   - 自动按需安装/更新 Python 与 Node.js 依赖
#   - 自动重新构建前端静态产物 (vite build)
#   - 智能保留本地配置 (.env, 数据库, 运行时日志) 不受影响
#   - 全程写入更新日志 logs/update.log 便于诊断
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"

# 载入网络 / 代理 / 镜像检测共享库
# shellcheck source=net-detect.sh
. "$SCRIPT_DIR/net-detect.sh"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ==============================================================================
# 以下为辅助函数（下载 / 校验 / 解压 / 覆盖复制 / Git 拉取）
# 注意：必须定义在主流程之前，bash 按顺序执行，先定义后调用
# ==============================================================================

# 断点续传下载（多尝试，失败自动续传）
download_zip() {
    local url="$1"
    local out="$2"
    local attempt
    for attempt in 1 2 3; do
        if curl -fSL -C - --retry 3 --retry-delay 2 --connect-timeout 15 -m 60 -o "$out" "$url" 2>/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# 校验 zip 完整性
verify_zip() {
    local f="$1"
    if command -v unzip >/dev/null 2>&1; then
        unzip -t "$f" >/dev/null 2>&1
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).testzip()" "$f" >/dev/null 2>&1
    elif command -v python >/dev/null 2>&1; then
        python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).testzip()" "$f" >/dev/null 2>&1
    else
        # 没有 unzip/python 时退化为基础校验：非空 + ZIP magic("PK") 文件头。
        # 既不假装成功（原来直接 return 0 会让损坏包混过去），
        # 也不会让缺工具的环境彻底无法更新（全判失败会导致所有镜像都被换掉）。
        log_warn "系统缺少 unzip 与 python，仅做基础完整性校验（文件头 + 体积）。"
        log_update "WARN: 无 unzip/python，退化为 PK magic 基础校验"
        [ -s "$f" ] || return 1
        local magic
        magic="$(head -c 2 "$f" 2>/dev/null || echo "")"
        [ "$magic" = "PK" ]
    fi
}

# 可选的 SHA256 校验：仅当远端发布了 SHA256SUMS 时才生效。
# 结构校验（unzip -t）只能发现损坏，无法发现镜像被投毒；有校验和时做强校验。
# 远端没有该文件（当前即如此）则跳过并返回成功，不阻塞更新。
verify_sha256() {
    local f="$1"
    local sums="" expected="" actual="" sumurl

    for sumurl in $(github_mirror_urls "qi-1021/miroworld/raw/main/SHA256SUMS"); do
        # 代理已在前面 export 为 http_proxy/https_proxy，curl 会自动继承
        sums="$(curl -fsSL -m 15 "$sumurl" 2>/dev/null || true)"
        [ -n "$sums" ] && break
    done

    if [ -z "$sums" ]; then
        log_update "未发布 SHA256SUMS，跳过校验和验证"
        return 0
    fi

    # 取 main.zip 对应的校验和（格式：<sha256>  <文件名>）
    expected="$(echo "$sums" | awk '/main\.zip/ {print $1; exit}')"
    if [ -z "$expected" ]; then
        log_update "SHA256SUMS 中未找到 main.zip 条目，跳过校验和验证"
        return 0
    fi

    if command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$f" 2>/dev/null | awk '{print $1}')"
    else
        log_update "系统缺少 shasum/sha256sum，跳过校验和验证"
        return 0
    fi

    if [ "$actual" = "$expected" ]; then
        log_update "SHA256 校验通过"
        return 0
    fi
    log_warn "源码包 SHA256 校验和不匹配，可能下载不完整或镜像异常。"
    log_update "ERROR: SHA256 不匹配 (期望 $expected 实际 $actual)"
    return 1
}

# 解压 zip 到指定目录
extract_zip() {
    local f="$1"
    local dir="$2"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$f" -d "$dir"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$f" "$dir"
    elif command -v python >/dev/null 2>&1; then
        python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$f" "$dir"
    else
        return 1
    fi
}

# 需要保护的本地路径（相对源码树根目录；裸名称会匹配任意层级）
EXCLUDE_PATHS=(
    "data"
    "neo4j"
    "logs"
    ".env"
    ".venv"
    "node_modules"
    "app/data/model-config"
    "app/backend/data"
    "app/backend/logs"
    "app/frontend/node_modules"
    "app/backend/.venv"
    "app/backend/.venv-simulation"
)

# 覆盖复制源码树，跳过受保护路径
copy_tree_excluding() {
    local src="$1"
    local dst="$2"
    shift 2
    local excludes=("$@")

    # 优先使用 rsync（macOS / Linux 均常见），失败则继续尝试其他方式
    if command -v rsync >/dev/null 2>&1; then
        local args=(-a)
        local ex
        for ex in "${excludes[@]}"; do
            args+=("--exclude=$ex")
        done
        if rsync "${args[@]}" "$src/" "$dst/"; then
            return 0
        fi
    fi

    # 其次使用 tar --exclude
    if command -v tar >/dev/null 2>&1; then
        local targs=()
        local ex2
        for ex2 in "${excludes[@]}"; do
            targs+=("--exclude=$ex2")
        done
        if (cd "$src" && tar cf - "${targs[@]}" .) | (cd "$dst" && tar xf -); then
            return 0
        fi
    fi

    # 兜底：手动递归复制
    _manual_copy "$src" "$dst" "" "${excludes[@]}"
}

# 手动递归复制（跳过受保护路径）
_manual_copy() {
    local src="$1"
    local dst="$2"
    local rel="$3"
    shift 3
    local excludes=("$@")
    local item base relpath
    for item in "$src"/* "$src"/.[!.]* "$src"/..?*; do
        [ -e "$item" ] || continue
        base="$(basename "$item")"
        relpath="$base"
        if [ -n "$rel" ]; then relpath="$rel/$base"; fi
        if _is_excluded "$relpath" "${excludes[@]}"; then
            continue
        fi
        if [ -d "$item" ]; then
            mkdir -p "$dst/$base"
            _manual_copy "$item" "$dst/$base" "$relpath" "${excludes[@]}"
        else
            cp -f "$item" "$dst/$base" 2>/dev/null || cp "$item" "$dst/$base"
        fi
    done
}

# 判断相对路径是否命中受保护路径（精确匹配或位于其子目录）
_is_excluded() {
    local relpath="$1"
    shift
    local ex e
    for ex in "$@"; do
        e="${ex%/}"
        if [ "$relpath" = "$e" ] || [ "${relpath#${e}/}" != "$relpath" ]; then
            return 0
        fi
    done
    return 1
}

# Git 拉取辅助：显式应用代理（若已检测到）
git_pull() {
    local remote="$1"
    local branch="$2"
    if [ -n "$PROXY" ] && [ "$PROXY" != "none" ]; then
        git -c http.proxy="$PROXY" -c https.proxy="$PROXY" pull "$remote" "$branch"
    else
        git pull "$remote" "$branch"
    fi
}

# 读取远端分支最新 commit（轻量请求，用于判断是否真的有更新）
# 用法：git_remote_head <remote> <branch>；无法获取时输出空字符串
git_remote_head() {
    local remote="$1"
    local branch="$2"
    if [ -n "$PROXY" ] && [ "$PROXY" != "none" ]; then
        git -c http.proxy="$PROXY" -c https.proxy="$PROXY" \
            ls-remote "$remote" "refs/heads/$branch" 2>/dev/null | awk '{print $1}' | head -1
    else
        git ls-remote "$remote" "refs/heads/$branch" 2>/dev/null | awk '{print $1}' | head -1
    fi
}

# ==============================================================================
# 主流程
# ==============================================================================

echo "================================================================="
echo "        🚀 Miroworld 一键无密更新程序 (GitHub Public Sync)       "
echo "================================================================="

cd "$PROJECT_ROOT"

# 确保版本文件存在
VERSION_FILE="$PROJECT_ROOT/VERSION"
if [ ! -f "$VERSION_FILE" ]; then
    echo "1.0.0" > "$VERSION_FILE"
    log_update "已创建版本文件 VERSION (1.0.0)"
fi
LOCAL_VERSION="$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')"
log_update "===== 开始更新 ====="
log_update "本地版本: ${LOCAL_VERSION:-未知}"

# 检测代理环境
PROXY_ENV="$(detect_proxy_env)"
PROXY="$(effective_proxy)"
if [ "$PROXY_ENV" != "none" ]; then
    log_info "检测到环境代理: $PROXY_ENV"
    log_update "环境代理: $PROXY_ENV"
fi
if [ -n "$PROXY" ] && [ "$PROXY" != "none" ]; then
    log_info "将使用代理: $PROXY"
    log_update "生效代理: $PROXY"
    export http_proxy="$PROXY"
    export https_proxy="$PROXY"
    export HTTP_PROXY="$PROXY"
    export HTTPS_PROXY="$PROXY"
else
    log_info "未检测到代理，将尝试直连与镜像加速。"
fi

# 1 & 2. 检查 Git 或自动降级为原生 ZIP 覆盖更新
log_step "正在从 GitHub 获取最新版本代码..."

if command -v git >/dev/null 2>&1; then
    # ============================ Git 模式 ============================
    # 确保 remote 使用 HTTPS 公开地址（免 key）
    CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$CURRENT_REMOTE" == git@github.com:* ]]; then
        HTTPS_REMOTE="https://github.com/${CURRENT_REMOTE#git@github.com:}"
        log_info "检测到 SSH 远程地址，切换为公开免密 HTTPS 地址: $HTTPS_REMOTE"
        log_update "切换 remote 为 HTTPS: $HTTPS_REMOTE"
        git remote set-url origin "$HTTPS_REMOTE"
    elif [[ -z "$CURRENT_REMOTE" ]]; then
        git remote add origin "https://github.com/qi-1021/miroworld.git"
    fi

    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    log_info "当前分支: $BRANCH"

    # ---- 增量判断：本地 HEAD 与远端一致时无需拉取（慢链接下省掉整次网络往返）----
    log_step "正在检查是否有新版本..."
    LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null || echo "")"
    REMOTE_HEAD="$(git_remote_head origin "$BRANCH")"
    if [ -n "$LOCAL_HEAD" ] && [ -n "$REMOTE_HEAD" ] && [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
        log_info "✅ 已是最新版本（${LOCAL_HEAD:0:8}），无需更新。"
        log_update "git 模式：本地与远端一致 ($LOCAL_HEAD)，跳过拉取"
        echo ""
        echo "如需强制重新同步依赖，请运行：bash scripts/setup-env.sh"
        exit 0
    fi
    if [ -z "$REMOTE_HEAD" ]; then
        log_warn "无法获取远端版本信息（网络或代理问题），仍将尝试拉取。"
        log_update "git 模式：ls-remote 失败，继续尝试 pull"
    fi

    PULL_OK=0
    if git_pull origin "$BRANCH"; then
        PULL_OK=1
        log_info "✅ 源代码已成功同步至最新版本！"
        log_update "git pull 成功 (origin/$BRANCH)"
    else
        log_warn "官方源拉取失败，正在尝试保留本地修改并重试..."
        log_update "git pull 失败，尝试 stash"
        git stash 2>/dev/null || true
        if git_pull origin "$BRANCH"; then
            git stash pop 2>/dev/null || true
            PULL_OK=1
            log_info "✅ 代码已合并更新完成。"
            log_update "git pull (stash) 成功"
        else
            git stash pop 2>/dev/null || true
            log_warn "官方源仍失败，尝试镜像源..."
            log_update "官方源失败，尝试镜像源"
            for m in "${GITHUB_MIRRORS[@]}"; do
                [ "$m" = "github.com" ] && continue
                MIRROR_URL="$(github_mirror_url "$m" "qi-1021/miroworld.git")"
                log_info "尝试镜像源: $m"
                log_update "尝试镜像源: $m"
                git remote remove mirror 2>/dev/null || true
                git remote add mirror "$MIRROR_URL" 2>/dev/null || true
                if git_pull mirror "$BRANCH"; then
                    PULL_OK=1
                    log_info "✅ 已通过镜像源同步至最新版本！"
                    log_update "git pull 成功 (mirror: $m)"
                    break
                fi
            done
            git remote remove mirror 2>/dev/null || true
        fi
    fi

    if [ "$PULL_OK" -ne 1 ]; then
        log_error "Git 拉取失败，请检查网络连接。"
        log_update "ERROR: git pull 失败 (origin 与所有镜像均失败)"
        echo "更新日志：$PROJECT_ROOT/logs/update.log"
        exit 1
    fi

    # Git 模式下，从拉取后的文件更新本地版本号
    if [ -f "$VERSION_FILE" ]; then
        LOCAL_VERSION="$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')"
        log_update "更新后版本: ${LOCAL_VERSION:-未知}"
    fi
else
    # ============================ 免 Git 模式 ============================
    log_warn "检测到当前环境未安装 Git，自动启用免 Git 原生 ZIP 极速增量更新通道..."
    log_update "启用免 Git ZIP 更新通道"

    # ---- 版本检查：先获取远端版本，相同则无需更新 ----
    log_step "正在检查远端版本..."
    REMOTE_VERSION=""
    for vurl in $(github_mirror_urls "qi-1021/miroworld/raw/main/VERSION"); do
        REMOTE_VERSION="$(curl -fsSL -m 15 "$vurl" 2>/dev/null | tr -d '[:space:]')"
        if [ -n "$REMOTE_VERSION" ]; then
            log_update "远端版本获取成功: $REMOTE_VERSION (来源: $vurl)"
            break
        fi
    done

    if [ -n "$REMOTE_VERSION" ]; then
        if [ -n "$LOCAL_VERSION" ] && [ "$REMOTE_VERSION" = "$LOCAL_VERSION" ]; then
            log_info "✅ 已是最新版本 (v$LOCAL_VERSION)，无需更新"
            log_update "已是最新版本 (v$LOCAL_VERSION)，无需更新"
            echo ""
            echo "================================================================="
            log_info "🎉 Miroworld 已是最新版本！"
            echo "================================================================="
            exit 0
        fi
        log_info "发现新版本: 本地 v${LOCAL_VERSION:-?} → 远端 v$REMOTE_VERSION，开始更新..."
        log_update "发现新版本: 本地 v${LOCAL_VERSION:-?} → 远端 v$REMOTE_VERSION"
    else
        log_warn "无法获取远端版本号（网络受限），将直接下载更新。"
        log_update "WARN: 远端版本获取失败，直接下载"
    fi

    # ---- 下载源码包（多镜像 + 断点续传 + 校验）----
    ZIP_FILE="miroworld-update-temp.zip"
    TEMP_DIR="miroworld-update-temp"
    rm -f "$ZIP_FILE"
    rm -rf "$TEMP_DIR"

    CANDIDATES="$(github_mirror_urls "qi-1021/miroworld/archive/refs/heads/main.zip")"
    log_step "正在测试并选择最快的下载镜像..."
    BEST="$(pick_fastest_mirror "$CANDIDATES")"

    # 组装尝试顺序：最快镜像优先，其余镜像兜底
    TRY_URLS=""
    if [ -n "$BEST" ]; then
        TRY_URLS="$BEST"
        log_info "已选择最快镜像: $BEST"
        log_update "最快镜像: $BEST"
    fi
    for u in $CANDIDATES; do
        case " $TRY_URLS " in *" $u "*) ;; *) TRY_URLS="$TRY_URLS $u";; esac
    done

    DOWNLOAD_OK=0
    for url in $TRY_URLS; do
        log_info "正在从镜像下载源码包: $url"
        log_update "尝试下载: $url"
        if download_zip "$url" "$ZIP_FILE"; then
            if verify_zip "$ZIP_FILE" && verify_sha256 "$ZIP_FILE"; then
                DOWNLOAD_OK=1
                log_info "✅ 源码包下载并校验成功！"
                log_update "下载并校验成功: $url"
                break
            else
                log_warn "源码包校验失败，删除后尝试下一个镜像..."
                log_update "WARN: 校验失败，切换镜像: $url"
                rm -f "$ZIP_FILE"
            fi
        else
            log_warn "该镜像下载失败，正在切换下一个镜像..."
            log_update "WARN: 下载失败，切换镜像: $url"
            rm -f "$ZIP_FILE"
        fi
    done

    if [ "$DOWNLOAD_OK" -ne 1 ]; then
        log_error "所有下载源均失败，请检查网络连接。"
        log_update "ERROR: 所有下载源均失败"
        echo "更新日志：$PROJECT_ROOT/logs/update.log"
        exit 1
    fi

    # ---- 解压到临时目录 ----
    log_step "正在解压源码包..."
    if ! extract_zip "$ZIP_FILE" "$TEMP_DIR"; then
        log_error "源码包解压失败，文件可能已损坏。"
        log_update "ERROR: 解压失败"
        rm -f "$ZIP_FILE"
        rm -rf "$TEMP_DIR"
        echo "更新日志：$PROJECT_ROOT/logs/update.log"
        exit 1
    fi

    # ---- 覆盖更新（保护本地数据）----
    SRC_TREE="$TEMP_DIR/miroworld-main"
    if [ -d "$SRC_TREE" ]; then
        log_step "正在同步源码（已自动保护本地数据与配置）..."
        log_update "开始同步源码，保护本地数据"
        if copy_tree_excluding "$SRC_TREE" "$PROJECT_ROOT" "${EXCLUDE_PATHS[@]}"; then
            log_info "✅ 源码包已自动同步至最新版本！"
            log_update "源码同步完成"
        else
            log_error "源码同步失败，请检查磁盘空间与权限。"
            log_update "ERROR: 源码同步失败"
            rm -f "$ZIP_FILE"
            rm -rf "$TEMP_DIR"
            echo "更新日志：$PROJECT_ROOT/logs/update.log"
            exit 1
        fi
        rm -rf "$TEMP_DIR"
        rm -f "$ZIP_FILE"
    else
        log_error "解压后未找到源码目录，更新中止。"
        log_update "ERROR: 未找到源码目录"
        rm -f "$ZIP_FILE"
        rm -rf "$TEMP_DIR"
        echo "更新日志：$PROJECT_ROOT/logs/update.log"
        exit 1
    fi

    # 更新本地版本号
    if [ -n "$REMOTE_VERSION" ]; then
        echo "$REMOTE_VERSION" > "$VERSION_FILE"
        log_update "本地版本已更新为: $REMOTE_VERSION"
    fi
    LOCAL_VERSION="$(cat "$VERSION_FILE" 2>/dev/null | tr -d '[:space:]')"
    log_update "更新后版本: ${LOCAL_VERSION:-未知}"
fi

# 3. 检查并更新后端 Python 依赖
log_step "检查并同步后端 Python 环境依赖 (国内镜像加速)..."
# 仅在仿真虚拟环境明显损坏时清除（缺少可执行 python 即视为残缺）。
# 早期版本每次更新都无条件删除，导致慢网络下反复重建、更新奇慢。
SIM_VENV="$APP_DIR/backend/.venv-simulation"
if [ -d "$SIM_VENV" ]; then
    if [ ! -x "$SIM_VENV/bin/python" ] && [ ! -x "$SIM_VENV/Scripts/python.exe" ]; then
        log_warn "检测到仿真虚拟环境残缺，正在清除以便重建..."
        log_update "清除损坏的 .venv-simulation"
        rm -rf "$SIM_VENV" >/dev/null 2>&1 || true
    else
        log_update "保留可用的 .venv-simulation（跳过重建）"
    fi
fi

if [ -f "$APP_DIR/backend/requirements.txt" ]; then
    PYTHON_CMD=""
    if [ -f "$APP_DIR/backend/.venv/bin/python" ]; then
        PYTHON_CMD="$APP_DIR/backend/.venv/bin/python"
    elif [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
        PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
    elif [ -f "$APP_DIR/backend/venv/bin/python" ]; then
        PYTHON_CMD="$APP_DIR/backend/venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    fi

    if [ -n "$PYTHON_CMD" ]; then
        log_info "使用 Python: $($PYTHON_CMD --version 2>&1)"
        if command -v uv >/dev/null 2>&1; then
            uv pip install -r "$APP_DIR/backend/requirements.txt" --python "$PYTHON_CMD" --index-url https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ >/dev/null 2>&1 || true
        else
            $PYTHON_CMD -m pip install -r "$APP_DIR/backend/requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/ --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.huaweicloud.com/repository/pypi/simple/ -q --disable-pip-version-check || log_warn "Python 依赖增量安装跳过或已是最新"
        fi
    else
        log_warn "未检测到独立虚拟环境，若后端运行异常请运行 scripts/setup-env.sh"
    fi
fi

# 4. 检查并编译前端产物
log_step "检查并构建前端生产包..."
if [ -d "$APP_DIR/frontend" ] && command -v npm >/dev/null 2>&1; then
    cd "$APP_DIR/frontend"
    if [ -f "package.json" ]; then
        log_info "执行前端极速构建..."
        npm run build || log_warn "前端构建失败，请检查 node/npm 环境"
    fi
    cd "$PROJECT_ROOT"
fi

log_update "===== 更新完成 ====="
echo ""
echo "================================================================="
log_info "🎉 Miroworld 更新完成！"
echo "👉 您可以随时运行以下命令启动最新版系统："
echo "   bash scripts/start.sh"
echo "================================================================="