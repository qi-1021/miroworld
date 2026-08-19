#!/bin/bash
# ==============================================================================
# Miroworld 环境自动检测与预配置 (macOS / Linux)
#
# 用途：
#   1) 自动检测代理 / 最快镜像 / 端口占用 / 工具链版本
#   2) 将检测结果持久化到 app/data/env-config.json
#   3) 提供 load_config / get_config_value 供其他脚本复用
#
# 用法：
#   独立执行：  bash scripts/detect-env.sh            # 检测并写入配置
#   source 使用：
#     source scripts/detect-env.sh
#     detect_and_persist
#     load_config
#     get_config_value proxy
#
# 说明：本文件为库文件，可 source 也可独立执行；
#       所有函数均为 POSIX 风格 bash，兼容 macOS / Linux，
#       容忍缺失工具，且绝不 exit 退出调用方。
# ==============================================================================

# 若未定义 PROJECT_ROOT，则根据本文件位置推导
if [ -z "${PROJECT_ROOT:-}" ]; then
    if [ -n "${BASH_SOURCE[0]:-}" ]; then
        DETECT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    else
        # 非 bash（如 zsh）source 时 BASH_SOURCE 为空：按当前目录推导
        case "$PWD" in
            */scripts) DETECT_SCRIPT_DIR="$PWD" ;;
            *) DETECT_SCRIPT_DIR="$PWD/scripts" ;;
        esac
    fi
    PROJECT_ROOT="$(dirname "$DETECT_SCRIPT_DIR")"
fi

# 复用 net-detect.sh 的检测函数（有效代理 / 镜像测速 / 端口连通）
if [ -f "$PROJECT_ROOT/scripts/net-detect.sh" ]; then
    # shellcheck source=net-detect.sh
    source "$PROJECT_ROOT/scripts/net-detect.sh"
fi

# 配置文件路径（可用 DETECT_CONFIG_FILE 覆盖，便于测试）
CONFIG_FILE="${DETECT_CONFIG_FILE:-$PROJECT_ROOT/app/data/env-config.json}"

# 默认端口
DEFAULT_FRONTEND_PORT=3000
DEFAULT_BACKEND_PORT=5001
DEFAULT_NEO4J_PORT=7687

# ------------------------------------------------------------------------------
# 内部：JSON 字符串转义（防止双引号 / 反斜杠破坏格式）
# ------------------------------------------------------------------------------
_escape_json() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# ------------------------------------------------------------------------------
# 内部：安全执行版本命令，取第一行输出（命令缺失时返回空，不报错）
# ------------------------------------------------------------------------------
_version_line() {
    local cmd="$1"
    shift
    if command -v "$cmd" >/dev/null 2>&1; then
        "$cmd" "$@" 2>&1 | head -1
    fi
}

# ------------------------------------------------------------------------------
# 内部：从一行文本中提取版本号
#   例："Python 3.11.5"      → 3.11.5
#       "v18.17.0"           → 18.17.0
#       'openjdk version "17.0.9"' → 17.0.9
# ------------------------------------------------------------------------------
_extract_version() {
    printf '%s' "$1" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1
}

# ------------------------------------------------------------------------------
# 内部：查找从 base 开始第一个可用端口（base..base+10）
# 端口被占用时依次尝试 +1..+10；全部被占用则回退默认端口并告警。
# 输出：可用端口号（或默认端口）
# ------------------------------------------------------------------------------
_find_available_port() {
    local base="$1"
    local i p
    for i in $(seq 0 10); do
        p=$((base + i))
        if ! _tcp_port_open "127.0.0.1" "$p" 2>/dev/null; then
            echo "$p"
            return 0
        fi
    done
    echo "[WARN] 端口 ${base}-$((base + 10)) 均被占用，暂用默认端口 ${base}" >&2
    echo "$base"
    return 0
}

# ------------------------------------------------------------------------------
# 检测并持久化环境配置
#   - 代理：effective_proxy（优先环境变量，其次本地代理探测）
#   - 镜像：pick_fastest_mirror 测速取最快（GitHub 直连 + 国内镜像）
#   - 端口：3000/5001/7687，被占用则 +1..+10 取首个可用
#   - 工具链：python3 / node / java 版本（缺失容忍）
# 写入 app/data/env-config.json（含 detected_at 时间戳）
# ------------------------------------------------------------------------------
detect_and_persist() {
    # 1) 代理
    local proxy=""
    proxy="$(effective_proxy 2>/dev/null || true)"
    [ "$proxy" = "none" ] && proxy=""

    # 2) 最快镜像（逐个测速，全部失败则留空）
    local mirror=""
    if command -v curl >/dev/null 2>&1; then
        mirror="$(pick_fastest_mirror "$(github_mirror_urls 'qi-1021/miroworld/archive/refs/heads/main.zip')" 2>/dev/null || true)"
    fi

    # 3) 端口占用检测（冲突自动 +1..+10）
    local fe be neo4j
    fe="$(_find_available_port "$DEFAULT_FRONTEND_PORT")"
    be="$(_find_available_port "$DEFAULT_BACKEND_PORT")"
    neo4j="$(_find_available_port "$DEFAULT_NEO4J_PORT")"

    # 4) 工具链版本（缺失容忍，返回空字符串）
    local py node java
    py="$(_extract_version "$(_version_line python3 --version)")"
    node="$(_extract_version "$(_version_line node --version)")"
    java="$(_extract_version "$(_version_line java -version)")"

    # 5) 写入配置
    local ts
    ts="$(date '+%Y-%m-%dT%H:%M:%S')"
    mkdir -p "$(dirname "$CONFIG_FILE")" 2>/dev/null || true
    {
        printf '{\n'
        printf '  "proxy": "%s",\n' "$(_escape_json "$proxy")"
        printf '  "mirror": "%s",\n' "$(_escape_json "$mirror")"
        printf '  "ports": {\n'
        printf '    "frontend": %s,\n' "$fe"
        printf '    "backend": %s,\n' "$be"
        printf '    "neo4j": %s\n' "$neo4j"
        printf '  },\n'
        printf '  "tools": {\n'
        printf '    "python": "%s",\n' "$(_escape_json "$py")"
        printf '    "node": "%s",\n' "$(_escape_json "$node")"
        printf '    "java": "%s"\n' "$(_escape_json "$java")"
        printf '  },\n'
        printf '  "detected_at": "%s"\n' "$ts"
        printf '}\n'
    } > "$CONFIG_FILE" 2>/dev/null || true
    return 0
}

# ------------------------------------------------------------------------------
# 读取环境配置
# 输出：配置文件内容（JSON）；文件缺失时输出默认配置
# ------------------------------------------------------------------------------
load_config() {
    local defaults='{"proxy":"","mirror":"","ports":{"frontend":3000,"backend":5001,"neo4j":7687},"tools":{"python":"","node":"","java":""},"detected_at":""}'
    if [ -f "$CONFIG_FILE" ]; then
        cat "$CONFIG_FILE" 2>/dev/null || printf '%s\n' "$defaults"
    else
        printf '%s\n' "$defaults"
    fi
}

# ------------------------------------------------------------------------------
# 读取配置中的单个值
# 用法：get_config_value <key> [默认值]
# 输出：key 对应的值；未找到时输出默认值（缺省为空）
# ------------------------------------------------------------------------------
get_config_value() {
    local key="$1"
    local default="${2:-}"
    local json val
    json="$(load_config)"
    val="$(printf '%s\n' "$json" | sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"*\([^\",}]*\)\"*[[:space:],}]*.*/\1/p" | tail -1)"
    if [ -n "$val" ]; then
        printf '%s\n' "$val"
    else
        printf '%s\n' "$default"
    fi
    return 0
}

# ------------------------------------------------------------------------------
# 独立执行：运行检测并输出结果
# ------------------------------------------------------------------------------
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "Miroworld 环境自动检测..."
    echo ""
    detect_and_persist
    echo "已生成环境配置：$CONFIG_FILE"
    echo ""
    load_config
    exit 0
fi
