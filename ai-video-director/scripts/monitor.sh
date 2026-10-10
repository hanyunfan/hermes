#!/usr/bin/env bash
# ai-video-director project monitor — safe to invoke from cron, systemd timer,
# or interactive shell. Designed to be idempotent and silent when nothing
# meaningful has changed.
#
# What it does:
#   1. Sync any ComfyUI-produced mp4s that aren't yet in
#      projects/<id>/output/clips/<shot_id>.mp4
#   2. Recompute generation_state.json counters
#   3. Print a one-line status if EITHER the runner is dead OR new shots
#      completed since the last monitor run. Otherwise print [SILENT].
#
# Usage:
#   monitor.sh <project_id> [comfyui_video_dir]
#
# Exit code is always 0 unless a hard error occurs (project not found etc.)

set -uo pipefail

PROJECT_ID="${1:-}"
COMFYUI_VIDEO_DIR="${2:-/home/frank/ComfyUI/output/video}"
ROOT=/home/frank/hermes/ai-video-director
LOG_DIR="$ROOT/projects/$PROJECT_ID/output/logs"
STATE_FILE="$LOG_DIR/monitor.last_count"
STATUS_FILE="$LOG_DIR/monitor.last_status"

if [ -z "$PROJECT_ID" ]; then
    echo "usage: $0 <project_id> [comfyui_video_dir]" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"

# === Step 1: sync mp4s from ComfyUI output into project output/clips/ ===
"$ROOT/.venv/bin/python" "$ROOT/scripts/sync_clips.py" "$PROJECT_ID" \
    --comfyui-video-dir "$COMFYUI_VIDEO_DIR" >> "$LOG_DIR/monitor.log" 2>&1

# === Step 2: read counters ===
COUNTERS=$(python3 -c "
import json, sys
with open('$ROOT/projects/$PROJECT_ID/state/generation_state.json') as f:
    s = json.load(f)
print(s.get('completed_shots', 0), s.get('total_shots', 0), s.get('failed_shots', 0))
" 2>/dev/null) || COUNTERS="0 0 0"
COMPLETED=$(echo "$COUNTERS" | awk '{print $1}')
TOTAL=$(echo "$COUNTERS" | awk '{print $2}')
FAILED=$(echo "$COUNTERS" | awk '{print $3}')

# === Step 3: check runner liveness ===
# The runner PID is written to PID_FILE by run_all.sh (we'll add that next).
PID_FILE="$LOG_DIR/runner.pid"
RUNNER_ALIVE=0
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        RUNNER_ALIVE=1
    fi
fi

# === Step 4: detect changes vs last run ===
LAST_COMPLETED=0
if [ -f "$STATE_FILE" ]; then
    LAST_COMPLETED=$(cat "$STATE_FILE")
fi

# === Step 5: emit status ===
if [ "$COMPLETED" -gt "$LAST_COMPLETED" ]; then
    NEW=$((COMPLETED - LAST_COMPLETED))
    STATUS="+${NEW} shot(s) completed: now ${COMPLETED}/${TOTAL}"
    echo "$STATUS" | tee "$STATUS_FILE"
elif [ "$RUNNER_ALIVE" -eq 0 ] && [ "$COMPLETED" -lt "$TOTAL" ]; then
    STATUS="WARNING: runner not running, ${COMPLETED}/${TOTAL} shots done, ${FAILED} failed"
    echo "$STATUS" | tee "$STATUS_FILE"
elif [ "$FAILED" -gt 0 ]; then
    STATUS="${FAILED} failed shots, ${COMPLETED}/${TOTAL} done"
    echo "$STATUS" | tee "$STATUS_FILE"
else
    echo "[SILENT]" > "$STATUS_FILE"
fi

# Remember count for next run
echo "$COMPLETED" > "$STATE_FILE"
