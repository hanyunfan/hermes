#!/usr/bin/env bash
# Test: no-TTY fallback
#
# Regression for the bug where running over SSH without -t (no controlling
# terminal) caused the script to enter "TUI mode" silently (because bash
# [[ -r /dev/tty ]] returns 0 even when open() would ENXIO), redirect
# stdout to /tmp/rsync-tree.log, and look like a hang.
#
# With the fix, tui_start must detect the missing TTY via an actual open()
# test, return non-zero, and the main script must fall back to PLAIN mode
# so all output goes to the user's stdout.
set -e
cd "$(dirname "$0")"

STATE_DIR="$HOME/.rsync-tree-state-test-no-tty"
rm -rf "$STATE_DIR"
export RSYNC_TREE_STATE_DIR="$STATE_DIR"

# Use setsid to detach from controlling tty, simulate `ssh host cmd` without -t.
# </dev/null ensures stdin is also not a tty.
out=$(setsid bash -c './rsync-tree.sh --dry-run --source node012 --nodes "node0[01-18]"' </dev/null 2>&1)
rc=$?

# Expectations:
# 1. Exit 0 (dry-run completes)
# 2. Output goes to stdout (not silently redirected to LOGFILE)
# 3. TUI mode is rejected with the new clearer error
# 4. PLAIN fallback message appears
# 5. STATE_DIR was used (no /tmp references)
# 6. Real scheduler output (iter markers) is visible
fail=0
[[ $rc -eq 0 ]] || { echo "FAIL: expected exit 0, got $rc"; fail=1; }
echo "$out" | grep -q 'tui: cannot open /dev/tty (no controlling terminal?); use --plain' \
    || { echo "FAIL: missing TTY-rejection message"; fail=1; }
echo "$out" | grep -q 'WARN: TUI not available, continuing in plain mode' \
    || { echo "FAIL: missing plain-mode fallback message"; fail=1; }
echo "$out" | grep -q '\-\-\- iter ' \
    || { echo "FAIL: missing scheduler iter markers (output got swallowed?)"; fail=1; }
echo "$out" | grep -q 'SUMMARY' \
    || { echo "FAIL: missing summary (run didn't complete?)"; fail=1; }
[[ -d "$STATE_DIR" ]] || { echo "FAIL: STATE_DIR not created: $STATE_DIR"; fail=1; }

# Make sure we did NOT touch /tmp for state files
[[ -f /tmp/rsync-tree.log ]] && { echo "FAIL: /tmp/rsync-tree.log was created (should use STATE_DIR)"; fail=1; }

# Cleanup
rm -rf "$STATE_DIR"

if [[ $fail -eq 0 ]]; then
    echo "PASS: no-TTY fallback works (TTY-rejection + plain mode + STATE_DIR)"
    exit 0
else
    echo "--- captured output (first 30 lines) ---"
    echo "$out" | head -30
    exit 1
fi
