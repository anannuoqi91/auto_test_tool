#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.ssr_runtime"
PID_FILE="${STATE_DIR}/simplescreenrecorder.pid"
WINDOW_FILE="${STATE_DIR}/simplescreenrecorder.window"
WINDOW_NAME="${SSR_WINDOW_NAME:-SimpleScreenRecorder}"
SAVE_TAB_COUNT="${SSR_SAVE_TAB_COUNT:-2}"
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

[[ -n "${DISPLAY:-}" ]] || die "未检测到 DISPLAY。结束录制需要访问当前 X11 图形会话。"
need_cmd xdotool

window_id=""
if [[ -f "$WINDOW_FILE" ]]; then
    window_id="$(cat "$WINDOW_FILE")"
fi

if [[ -z "$window_id" ]]; then
    for ((i = 0; i < SEARCH_RETRY_COUNT; i++)); do
        window_id="$(find_window_id)"
        if [[ -n "$window_id" ]]; then
            break
        fi
        sleep 0.5
    done
fi

[[ -n "$window_id" ]] || die "没有找到 SimpleScreenRecorder 窗口。"

xdotool windowactivate --sync "$window_id"
sleep 0.3

for ((i = 0; i < SAVE_TAB_COUNT; i++)); do
    xdotool key --window "$window_id" Tab
    sleep 0.2
done

# 默认假设录制页按钮焦点顺序为:
# Start/Pause recording -> Cancel recording -> Save recording
xdotool key --window "$window_id" Return

if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE"
fi
if [[ -f "$WINDOW_FILE" ]]; then
    rm -f "$WINDOW_FILE"
fi

log "已发送结束并保存录制动作。"
log "如果你的界面焦点顺序不同，可在执行前设置 SSR_SAVE_TAB_COUNT，例如: SSR_SAVE_TAB_COUNT=1 ./stop_ssr_recording.sh"
