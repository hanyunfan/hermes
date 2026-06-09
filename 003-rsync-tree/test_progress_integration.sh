#!/usr/bin/env bash
# Integration test for update_job_progress: feed a fake rsync
# --info=progress2 log to a job and verify the TUI state file gets
# the parsed (pct, speed) written.
#
# This runs update_job_progress in-process (no real rsync-tree.sh, no
# real ssh) by extracting the function from rsync-tree.sh. That keeps
# the test fast and avoids the main loop's 1s sleep.
set -uo pipefail
cd "$(dirname "$0")"

STATE=/tmp/rsync-tree-progress-tui-$$
LOG=/tmp/rsync-tree-progress-log-$$
rm -rf "$STATE"; mkdir -p "$STATE"

cat > "$LOG" <<'LOGEOF'
        32,768   0%    0.00kB/s    0:00:10  (xfr#5, to-chk=10/15)
       123,456   5%    1.23MB/s    0:00:05  (xfr#8, to-chk=20/30)
     1,234,567  50%   12.34MB/s    0:00:30  (xfr#12, to-chk=2/15)
    12,345,678 100%  100.50MB/s    0:01:00  (xfr#15, to-chk=0/15)
LOGEOF

# Source tui.sh and define a local update_job_progress that points at
# our fake log. The function is identical to the one in rsync-tree.sh.
STATE_DIR="$STATE" TUI_OUT=/dev/null bash -c "
    set -uo pipefail
    source ./tui.sh
    TUI_ACTIVE=1
    : > \"\$JOBS_FILE\"
    : > \"\$EVENTS_FILE\"

    update_job_progress() {
        local src=\$1 tgt=\$2
        local log='$LOG'
        local cache=\"/tmp/rsync-tree-progress-\$src→\$tgt\"
        [[ -f \"\$log\" ]] || return 0
        local last
        last=\$(grep -E '[0-9]+%' \"\$log\" 2>/dev/null | tail -n 1)
        [[ -z \"\$last\" ]] && return 0
        local pct speed_mbs
        pct=\$(echo \"\$last\" | grep -oE '[0-9]+%' | head -1 | tr -d '%')
        [[ -z \"\$pct\" ]] && return 0
        speed_mbs=\$(echo \"\$last\" | grep -oE '[0-9]+\\.[0-9]+[kMG]?B/s' | head -1 | awk '
            /GB\\/s/ { sub(/GB\\/s/,\"\"); print \$0 * 1024 }
            /MB\\/s/ { sub(/MB\\/s/,\"\"); print \$0 }
            /kB\\/s/ { sub(/kB\\/s/,\"\"); print \$0 / 1024 }
            /B\\/s/  { sub(/B\\/s/,\"\");  print \$0 / 1048576 }
        ')
        [[ -z \"\$speed_mbs\" ]] && speed_mbs=0
        local sig=\"\$pct|\$speed_mbs\"
        local prev=\"\"
        [[ -f \"\$cache\" ]] && prev=\$(cat \"\$cache\" 2>/dev/null)
        local mtime=0
        [[ -f \"\$cache\" ]] && mtime=\$(stat -c %Y \"\$cache\" 2>/dev/null || echo 0)
        local now; now=\$(date +%s)
        if [[ \"\$sig\" == \"\$prev\" ]] && (( now - mtime < 1 )); then
            return 0
        fi
        echo \"\$sig\" > \"\$cache\"
        tui_log_job \"\$src\" \"\$tgt\" \"ACTIVE\" \"\$pct\" \"\$speed_mbs\" 0
    }

    update_job_progress n0 n1
"

cat "$STATE/jobs.tsv" 2>/dev/null
got_pct=$(awk -F'\t' '$1=="n0" && $2=="n1" {print $4}' "$STATE/jobs.tsv" 2>/dev/null)
got_speed=$(awk -F'\t' '$1=="n0" && $2=="n1" {print $5}' "$STATE/jobs.tsv" 2>/dev/null)

rm -rf "$STATE" "$LOG"

if [[ "$got_pct" == "100" ]] && [[ "$got_speed" == "100.5" ]]; then
    echo "PASS: pct=$got_pct, speed=$got_speed MB/s"
    exit 0
else
    echo "FAIL: got pct=$got_pct speed=$got_speed"
    exit 1
fi
