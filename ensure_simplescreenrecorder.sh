#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

log() {
    printf '[%s] %s\n' "$SCRIPT_NAME" "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

require_sudo_if_needed() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        return 0
    fi
    command -v sudo >/dev/null 2>&1 || die "当前用户不是 root，且系统里没有 sudo，无法安装软件。"
}

get_ssr_version() {
    if command -v dpkg-query >/dev/null 2>&1 && dpkg-query -W -f='${Version}\n' simplescreenrecorder >/dev/null 2>&1; then
        dpkg-query -W -f='${Version}\n' simplescreenrecorder
        return
    fi
    if command -v rpm >/dev/null 2>&1 && rpm -q simplescreenrecorder >/dev/null 2>&1; then
        rpm -q --queryformat '%{VERSION}-%{RELEASE}\n' simplescreenrecorder
        return
    fi
    if command -v pacman >/dev/null 2>&1 && pacman -Q simplescreenrecorder >/dev/null 2>&1; then
        pacman -Q simplescreenrecorder | awk '{print $2}'
        return
    fi
    printf 'unknown\n'
}

missing_runtime_tools() {
    local missing=()
    if ! command -v simplescreenrecorder >/dev/null 2>&1; then
        missing+=(simplescreenrecorder)
    fi
    if ! command -v xdotool >/dev/null 2>&1; then
        missing+=(xdotool)
    fi
    printf '%s\n' "${missing[*]}"
}

install_with_apt() {
    require_sudo_if_needed
    local sudo_cmd=()
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" apt-get install -y simplescreenrecorder xdotool
}

install_with_dnf() {
    require_sudo_if_needed
    local sudo_cmd=()
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" dnf install -y simplescreenrecorder xdotool
}

install_with_yum() {
    require_sudo_if_needed
    local sudo_cmd=()
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" yum install -y simplescreenrecorder xdotool
}

install_with_pacman() {
    require_sudo_if_needed
    local sudo_cmd=()
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" pacman -Sy --noconfirm simplescreenrecorder xdotool
}

install_with_zypper() {
    require_sudo_if_needed
    local sudo_cmd=()
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" zypper --non-interactive install simplescreenrecorder xdotool
}

missing_tools="$(missing_runtime_tools)"

if [[ -z "$missing_tools" ]]; then
    log "SimpleScreenRecorder 已安装，版本: $(get_ssr_version)"
    exit 0
fi

log "缺少运行依赖: $missing_tools"
log "开始安装 SimpleScreenRecorder 及其录制辅助依赖。"

if command -v apt-get >/dev/null 2>&1; then
    install_with_apt
elif command -v dnf >/dev/null 2>&1; then
    install_with_dnf
elif command -v yum >/dev/null 2>&1; then
    install_with_yum
elif command -v pacman >/dev/null 2>&1; then
    install_with_pacman
elif command -v zypper >/dev/null 2>&1; then
    install_with_zypper
else
    die "未识别到支持的包管理器，无法自动安装。"
fi

missing_tools="$(missing_runtime_tools)"
[[ -z "$missing_tools" ]] || die "安装完成后仍缺少依赖: $missing_tools"
log "安装完成，版本: $(get_ssr_version)"
