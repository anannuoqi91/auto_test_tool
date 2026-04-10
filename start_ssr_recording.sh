#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.ssr_runtime"
PID_FILE="${STATE_DIR}/simplescreenrecorder.pid"
WINDOW_FILE="${STATE_DIR}/simplescreenrecorder.window"
WINDOW_NAME="${SSR_WINDOW_NAME:-SimpleScreenRecorder}"
LAUNCH_WAIT_SECONDS="${SSR_LAUNCH_WAIT_SECONDS:-1}"
CONTINUE_COUNT="${SSR_CONTINUE_COUNT:-3}"
SEARCH_RETRY_COUNT="${SSR_SEARCH_RETRY_COUNT:-20}"

log() {
    printf '[%s] %s\n' "$SCRIPT_NAME" "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1"
}

find_window_id() {
    xdotool search --onlyvisible --name "$WINDOW_NAME" 2>/dev/null | head -n 1 || true
}

[[ -n "${DISPLAY:-}" ]] || die "未检测到 DISPLAY。SimpleScreenRecorder 需要在 X11 图形会话里运行。"
need_cmd simplescreenrecorder
need_cmd xdotool

if pgrep -x simplescreenrecorder >/dev/null 2>&1; then
    die "检测到已有 SimpleScreenRecorder 进程在运行。为避免 GUI 自动化点错窗口，请先关闭它后再启动脚本。"
fi

mkdir -p "$STATE_DIR"

simplescreenrecorder >/dev/null 2>&1 &
ssr_pid=$!
printf '%s\n' "$ssr_pid" >"$PID_FILE"
sleep "$LAUNCH_WAIT_SECONDS"

window_id=""
for ((i = 0; i < SEARCH_RETRY_COUNT; i++)); do
    window_id="$(find_window_id)"
    if [[ -n "$window_id" ]]; then
        break
    fi
    sleep 0.5
done

[[ -n "$window_id" ]] || die "没有找到 SimpleScreenRecorder 窗口，请确认当前桌面会话可见。"
printf '%s\n' "$window_id" >"$WINDOW_FILE"

xdotool windowactivate --sync "$window_id"
sleep 0.3

for ((i = 0; i < CONTINUE_COUNT; i++)); do
    xdotool key --window "$window_id" Return
    sleep 0.5
done

# 默认假设录制页打开后，焦点停留在“Start recording”按钮上。
xdotool key --window "$window_id" Return

log "已发送启动录制动作。"
log "如果你的界面流程不是 3 次 Continue，可在执行前设置 SSR_CONTINUE_COUNT，例如: SSR_CONTINUE_COUNT=2 ./start_ssr_recording.sh"
