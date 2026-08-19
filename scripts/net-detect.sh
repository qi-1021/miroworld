#!/bin/bash
# ==============================================================================
# Miroworld 网络 / 代理 / 镜像 检测共享库 (macOS / Linux)
# 本文件为库文件，仅供 source 使用，不直接执行。
# 所有函数均为 POSIX 风格 bash，兼容 macOS 与 Linux，容忍缺失工具，
# 且绝不主动 exit 退出调用方。
# ==============================================================================

# 若未定义 PROJECT_ROOT，则根据本文件位置推导
if [ -z "${PROJECT_ROOT:-}" ]; then
    NET_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$NET_SCRIPT_DIR")"
fi

# ------------------------------------------------------------------------------
# 检测环境变量中的代理设置
# 输出：检测到的 http_proxy / https_proxy / all_proxy 值，若无则输出 "none"
# ------------------------------------------------------------------------------
detect_proxy_env() {
    local found=""
    if [ -n "${http_proxy:-}" ]; then found="$found http_proxy=${http_proxy}"; fi
    if [ -n "${https_proxy:-}" ]; then found="$found https_proxy=${https_proxy}"; fi
    if [ -n "${HTTP_PROXY:-}" ]; then found="$found HTTP_PROXY=${HTTP_PROXY}"; fi
    if [ -n "${HTTPS_PROXY:-}" ]; then found="$found HTTPS_PROXY=${HTTPS_PROXY}"; fi
    if [ -n "${all_proxy:-}" ]; then found="$found all_proxy=${all_proxy}"; fi
    if [ -n "${ALL_PROXY:-}" ]; then found="$found ALL_PROXY=${ALL_PROXY}"; fi
    if [ -z "$found" ]; then
        echo "none"
    else
        echo "${found# }"
    fi
}

# ------------------------------------------------------------------------------
# 探测常见本地代理工具端口（快速 TCP 连接）
# 端口：7890 (Clash HTTP) / 7897 (Clash Verge HTTP) / 10809 (v2rayN HTTP)
#       / 8888 (通用 HTTP) / 1080 (通常是 SOCKS5)
# 输出：第一个开放端口对应的代理地址；SOCKS 端口输出 socks5h:// 前缀，
#       避免把 SOCKS 端口当 HTTP 代理用（curl 会报协议错误，反而误判为断网）
#       若全部未开放则输出 "none"
# 注：把 1080 排在最后，优先选真正的 HTTP 代理端口
# ------------------------------------------------------------------------------
detect_local_proxy() {
    # HTTP 代理端口优先
    local http_ports=(7890 7897 10809 8888)
    # SOCKS 端口（curl 需要 socks5h:// 协议前缀才能正确使用）
    local socks_ports=(1080 1081 10808)
    local port
    for port in "${http_ports[@]}"; do
        if _tcp_port_open "127.0.0.1" "$port"; then
            echo "http://127.0.0.1:$port"
            return 0
        fi
    done
    for port in "${socks_ports[@]}"; do
        if _tcp_port_open "127.0.0.1" "$port"; then
            echo "socks5h://127.0.0.1:$port"
            return 0
        fi
    done
    echo "none"
    return 0
}

# 内部：TCP 端口连通性检测（优先 nc，缺失时用 /dev/tcp 兜底）
_tcp_port_open() {
    local host="$1"
    local port="$2"
    if command -v nc >/dev/null 2>&1; then
        nc -z -w1 "$host" "$port" >/dev/null 2>&1 && return 0
        return 1
    fi
    # /dev/tcp 兜底（bash 内置）
    if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
        exec 3>&- 3<&- 2>/dev/null
        return 0
    fi
    return 1
}

# ------------------------------------------------------------------------------
# 计算最终生效的代理
# 优先使用显式环境变量，其次使用探测到的本地代理
# 输出：代理地址，若无则输出 "none"
# ------------------------------------------------------------------------------
effective_proxy() {
    local env_proxy=""
    if [ -n "${https_proxy:-}" ]; then
        env_proxy="$https_proxy"
    elif [ -n "${HTTPS_PROXY:-}" ]; then
        env_proxy="$HTTPS_PROXY"
    elif [ -n "${http_proxy:-}" ]; then
        env_proxy="$http_proxy"
    elif [ -n "${HTTP_PROXY:-}" ]; then
        env_proxy="$HTTP_PROXY"
    elif [ -n "${all_proxy:-}" ]; then
        env_proxy="$all_proxy"
    elif [ -n "${ALL_PROXY:-}" ]; then
        env_proxy="$ALL_PROXY"
    fi
    if [ -n "$env_proxy" ]; then
        echo "$env_proxy"
        return 0
    fi
    detect_local_proxy
}

# ------------------------------------------------------------------------------
# 测试单个 URL 的下载速度
# 用法：test_url_speed <url> [timeout秒，默认8]
# 输出：耗时秒数（如 0.42），失败则输出 "fail"
# ------------------------------------------------------------------------------
test_url_speed() {
    local url="$1"
    local timeout="${2:-8}"
    if [ -z "$url" ]; then
        echo "fail"
        return 1
    fi
    if ! command -v curl >/dev/null 2>&1; then
        echo "fail"
        return 1
    fi
    local time_total rc
    time_total=$(curl -o /dev/null -s -L --connect-timeout "$timeout" -m "$timeout" -w "%{time_total}" "$url" 2>/dev/null)
    rc=$?
    if [ "$rc" -ne 0 ] || [ -z "$time_total" ] || ! echo "$time_total" | grep -qE '^[0-9]+(\.[0-9]+)?$'; then
        echo "fail"
        return 1
    fi
    echo "$time_total"
    return 0
}

# ------------------------------------------------------------------------------
# 从多个候选 URL 中挑选最快的可用镜像（并行测速）
# 用法：pick_fastest_mirror "url1 url2 url3 ..." [timeout秒，默认8]
# 输出：最快的可用 URL；若全部失败则输出空字符串
# 说明：早期实现串行测速，5 个镜像 × 8 秒超时最差要干等 40 秒；
#       改为并行后总耗时约等于单次超时时间。
# ------------------------------------------------------------------------------
pick_fastest_mirror() {
    local candidates="$1"
    local timeout="${2:-8}"
    local tmpdir url idx best_url="" best_time=""

    # 无 mktemp 时退化为串行，保证极简环境下仍可用
    if ! command -v mktemp >/dev/null 2>&1; then
        local t
        # 用换行迭代而非依赖无引号词拆分：zsh 默认不做词拆分，这样 bash/zsh 都正确
        while IFS= read -r url; do
            [ -n "$url" ] || continue
            t=$(test_url_speed "$url" "$timeout")
            if [ "$t" != "fail" ]; then
                if [ -z "$best_time" ] || _time_lt "$t" "$best_time"; then
                    best_time="$t"; best_url="$url"
                fi
            fi
        done <<EOF
$(echo "$candidates" | tr ' \t' '\n\n')
EOF
        echo "$best_url"
        return 0
    fi

    tmpdir="$(mktemp -d 2>/dev/null)" || { echo ""; return 0; }

    idx=0
    while IFS= read -r url; do
        [ -n "$url" ] || continue
        idx=$((idx + 1))
        # 每个候选放到后台并行测速，结果写入独立文件（避免输出交错）
        (
            t="$(test_url_speed "$url" "$timeout")"
            printf '%s\t%s\n' "$t" "$url" > "$tmpdir/r$idx"
        ) &
    done <<EOF
$(echo "$candidates" | tr ' \t' '\n\n')
EOF
    wait 2>/dev/null || true

    local line t u
    for line in "$tmpdir"/r*; do
        [ -f "$line" ] || continue
        t="$(cut -f1 "$line" 2>/dev/null)"
        u="$(cut -f2 "$line" 2>/dev/null)"
        [ -z "$t" ] && continue
        [ "$t" = "fail" ] && continue
        if [ -z "$best_time" ] || _time_lt "$t" "$best_time"; then
            best_time="$t"; best_url="$u"
        fi
    done

    rm -rf "$tmpdir" 2>/dev/null || true
    echo "$best_url"
}

# 内部：比较两个耗时字符串，a < b 返回 0
_time_lt() {
    local a="$1" b="$2"
    awk -v a="$a" -v b="$b" 'BEGIN { exit !(a < b) }'
}

# ------------------------------------------------------------------------------
# GitHub 镜像列表
# 格式：每个元素为镜像主机名（不含协议），github.com 表示官方直连
# ------------------------------------------------------------------------------
GITHUB_MIRRORS=(
    "github.com"
    "ghproxy.net"
    "gh-proxy.com"
    "ghfast.top"
    "mirror.ghproxy.com"
)

# ------------------------------------------------------------------------------
# 根据镜像主机名与 GitHub 路径构造完整 URL
# 用法：github_mirror_url <mirror主机名> <github路径，如 qi-1021/miroworld/archive/refs/heads/main.zip>
# 输出：完整 URL
# ------------------------------------------------------------------------------
github_mirror_url() {
    local mirror="$1"
    local path="$2"
    if [ "$mirror" = "github.com" ]; then
        echo "https://github.com/$path"
    else
        echo "https://$mirror/https://github.com/$path"
    fi
}

# ------------------------------------------------------------------------------
# 将一组 GitHub 路径展开为对应的镜像 URL 列表（空格分隔）
# 用法：github_mirror_urls <github路径>
# 输出：空格分隔的完整 URL 列表
# ------------------------------------------------------------------------------
github_mirror_urls() {
    local path="$1"
    local mirror
    local out=""
    for mirror in "${GITHUB_MIRRORS[@]}"; do
        out="$out $(github_mirror_url "$mirror" "$path")"
    done
    echo "${out# }"
}

# ------------------------------------------------------------------------------
# 写入更新日志
# 用法：log_update "消息"
# 追加时间戳行到 $PROJECT_ROOT/logs/update.log（自动创建目录）
# ------------------------------------------------------------------------------
log_update() {
    local msg="$1"
    local log_dir="$PROJECT_ROOT/logs"
    local log_file="$log_dir/update.log"
    mkdir -p "$log_dir" 2>/dev/null || true
    if [ -n "$msg" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$log_file" 2>/dev/null || true
    fi
}
