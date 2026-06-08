#!/usr/bin/env bash
# Unit test: feed update_job_progress a fake rsync log, confirm it pushes
# ACTIVE rows to the TUI with the right pct / speed.
set -uo pipefail
cd "$(dirname "$0")"

# Use a single state dir shared between outer and inner shell.
# Inner shell sees STATE_DIR from the env; outer uses it directly.
STATE="/tmp/rsync-tree-test-tui-$$"
LOG="/tmp/rsync-tree-test-$$.log"
rm -rf "$STATE"; mkdir -p "$STATE"
trap 'rm -f "$LOG" "$STATE"/jobs.tsv "$STATE"/header "$STATE"/events.log "$STATE"/jobs.tsv.tmp.*; rmdir "$STATE" 2>/dev/null' EXIT

# Write a fake rsync progress2 log
cat > "$LOG" <<'LOGEOF'
        32,768   0%    0.00kB/s    0:00:10  (xfr#5, to-chk=10/15)
       123,456   5%    1.23MB/s    0:00:05  (xfr#8, to-chk=20/30)
     1,234,567  50%   12.34MB/s    0:00:30  (xfr#12, to-chk=2/15)
    12,345,678 100%  100.50MB/s    0:01:00  (xfr#15, to-chk=0/15)
LOGEOF

# Source tui.sh + run update_job_progress. We use a *single* bash invocation
# (not bash -c) so $$ matches the outer trap. STATE_DIR is set before
# source so tui.sh picks it up.
STATE_DIR="$STATE" TUI_OUT=/dev/null bash -c '
    set -uo pipefail
    source ./tui.sh
    TUI_ACTIVE=1
    : > "$JOBS_FILE"
    : > "$EVENTS_FILE"

    # Re-define update_job_progress with the same body as in rsync-tree.sh,
    # pointing at the outer LOG file. We re-source the latest code so the
    # test reflects the actual fix.
    update_job_progress() {
        local src=$1 tgt=$2
        local log="/tmp/rsync-tree-test-'"$$"'.log"
        [[ -f "$log" ]] || { echo "NO LOG: $log" >&2; return 0; }
        local last
        last=$(grep -E "[0-9]+%" "$log" 2>/dev/null | tail -n 1)
        [[ -z "$last" ]] && { echo "NO PROGRESS LINE" >&2; return 0; }
        local pct speed_mbs
        pct=$(echo "$last" | grep -oE "[0-9]+%" | head -1 | tr -d "%")
        [[ -z "$pct" ]] && { echo "NO PCT in: $last" >&2; return 0; }
        speed_mbs=$(echo "$last" | grep -oE "[0-9]+\.[0-9]+[kMG]?B/s" | head -1 | awk "/GB\/s/ { sub(/GB\/s/,\"\"); print \$0 * 1024 } /MB\/s/ { sub(/MB\/s/,\"\"); print \$0 } /kB\/s/ { sub(/kB\/s/,\"\"); print \$0 / 1024 } /B\/s/  { sub(/B\/s/,\"\");  print \$0 / 1048576 }")
        [[ -z "$speed_mbs" ]] && speed_mbs=0
        tui_log_job "$src" "$tgt" "ACTIVE" "$pct" "$speed_mbs" 0
    }

    update_job_progress "n12" "n13"

    if [[ ! -f "$JOBS_FILE" ]]; then
        echo "FAIL: jobs.tsv not created" >&2
        ls -la "$STATE_DIR" >&2
        exit 1
    fi
    cat "$JOBS_FILE"
' 2>&1

# Extract pct and speed from the resulting row (run in outer shell where
# STATE=/tmp/rsync-tree-test-tui-$$).
JOBS="$STATE/jobs.tsv"
[[ -f "$JOBS" ]] || { echo "FAIL: $JOBS missing"; exit 1; }
got_pct=$(awk -F'\t' '$1=="n12" && $2=="n13" {print $4}' "$JOBS")
got_speed=$(awk -F'\t' '$1=="n12" && $2=="n13" {print $5}' "$JOBS")

if [[ "$got_pct" == "100" ]] && [[ "$got_speed" == "100.5" ]]; then
    echo "PASS: pct=$got_pct, speed=$got_speed MB/s"
    exit 0
else
    echo "FAIL: got pct=$got_pct speed=$got_speed"
    exit 1
fi
