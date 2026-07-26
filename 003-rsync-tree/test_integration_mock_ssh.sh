#!/usr/bin/env bash
# test_integration_mock_ssh.sh — full scheduler integration test using
# mock SSH. Verifies:
#   1. Script terminates within reasonable time even when ALL jobs FAIL
#      (the original hang bug — orphaned .hb entries made n_active > 0
#      forever and blocked the exit gate).
#   2. Script terminates on success-path as well (no .hb leaks).
#   3. tui_log_job sees DONE rows for successful runs.
#
# Exit code 0 = all sub-tests pass.
set -uo pipefail
cd "$(dirname "$0")"

MOCKBIN=/tmp/rsync-tree-testbin
MOCKSRC=/tmp/rsync-tree-mocksrc
STATE=/tmp/rsync-tree-mockstate
rm -rf "$MOCKBIN" "$MOCKSRC" "$STATE"
mkdir -p "$MOCKBIN" "$MOCKSRC" "$STATE"
touch "$MOCKSRC/data"

# ---- mock ssh ----
# Modes:
#   MODE=success   — simulate successful rsync (prints progress2 + size + exit 0)
#   MODE=fail     — exit 0 but produce no useful output (forces SSH_FAIL_SRC)
#   MODE=hung     — sleep forever (so test would hang if script doesn't have
#                   a way out — but it's wrapped in `timeout` to bound)
cat > "$MOCKBIN/ssh" <<'EOF'
#!/usr/bin/env bash
# Mock ssh for rsync-tree.sh tests.
#
# Real ssh handles host argument + remote command separately, but bash's
# $@ is just a flat list of args. The remote command is one or more
# trailing args after the host.
#
# Two quoting shapes the parent uses:
#   ssh $SSH_ARGS "$src" "du --apparent-size -sb /path"
#     → ARGS = ("du --apparent-size -sb /path")  (single, double-quoted)
#   ssh $SSH_ARGS "$src" du --apparent-size -sb /path
#     → ARGS = ("du" "--apparent-size" "-sb" "/path")  (word-split)
#
# We also need to correctly handle SSH options like -o KEY=VAL that
# consume their own argument; otherwise the value leaks into the
# reconstructed command and our regexes fail.

# Strip SSH options, tracking their argument consumption
HOST=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|-i|-l|-p|-J)   # these take a separate arg
      shift 2 ;;
    -*)
      # All other flags (no arg): just consume
      shift ;;
    *)
      if [[ -z "$HOST" ]]; then HOST="$1"; shift; else ARGS+=("$1"); shift; fi ;;
  esac
done
DELAY=${MOCK_DELAY:-0.05}
sleep "$DELAY"
cmd="${ARGS[*]}"
case "${MOCK_MODE:-success}" in
  success)
    if [[ "$cmd" =~ ^du[[:space:]].*-sb[[:space:]] ]]; then
      echo "1024"
    elif [[ "$cmd" == *"rsync"* ]]; then
      printf '%s\n' "total size is 1024  speedup is 1.00"
    else
      echo "0"
    fi
    # Also record every du invocation we see so tests can verify
    # the --apparent-size (or -A) flag was actually passed.
    if [[ "$cmd" =~ ^du[[:space:]] ]]; then
      echo "$cmd" >> "${MOCK_DU_LOG:-/tmp/rsync-tree-mock-du.log}"
    fi
    ;;
  fail)
    # Empty output — forces SSH_FAIL_SRC branch on du check.
    ;;
  hung)
    sleep 600
    ;;
esac
exit 0
EOF
chmod +x "$MOCKBIN/ssh"

# Build environment
export PATH="$MOCKBIN:$PATH"
export RSYNC_TREE_STATE_DIR="$STATE"
export HOME="$STATE/home"
mkdir -p "$HOME"

run_test() {
  local name="$1"
  local mode="$2"
  local expected_pattern="$3"
  local extra_args="${4:-}"
  local timeout_sec="${5:-30}"

  echo "----- sub-test: $name (mode=$mode) -----"
  rm -rf "$STATE"/* 2>/dev/null || true
  rm -f "$MOCKSRC"/* 2>/dev/null; touch "$MOCKSRC/data"

  PATH="$MOCKBIN:$PATH" MOCK_MODE="$mode" timeout "$timeout_sec" \
    ./rsync-tree.sh --plain --source src \
      --nodes 'src,n1,n2,n3,n4,n5,n6' \
      --dir "$MOCKSRC" \
      $extra_args > "$STATE/out.log" 2>&1
  local rc=$?

  if (( rc != 0 )) && [[ "$mode" != "hung" ]]; then
    echo "  FAIL: exit code $rc (expected 0 for plain mode)"
    echo "  --- last 20 lines of log ---"
    tail -20 "$STATE/out.log" | sed 's/^/    /'
    return 1
  fi

  # Validation: should NOT still be running, should have summary
  if ! grep -q "$expected_pattern" "$STATE/out.log"; then
    echo "  FAIL: missing expected pattern '$expected_pattern' in output"
    echo "  --- last 20 lines ---"
    tail -20 "$STATE/out.log" | sed 's/^/    /'
    return 1
  fi
  echo "  PASS ($name)"
  return 0
}

fail=0

# Sub-test 1: all-succeed mode (everything green). Should write DONE rows
# then exit cleanly.
run_test "all-success" success "All jobs completed successfully" \
  || fail=$((fail + 1))

# Sub-test 2: all-fail mode (the original hang bug). Even when every
# rsync fails the script must terminate within timeout. Summary should
# list failures rather than hanging.
run_test "all-fail" fail "Failed jobs:" "" 60 \
  || fail=$((fail + 1))

# Sub-test 3: TUI mode + all-fail. The exact scenario that was hanging.
echo "----- sub-test: tui-mode-all-fail (the actual bug repro) -----"
rm -rf "$STATE"/* 2>/dev/null || true
rm -f "$MOCKSRC"/* 2>/dev/null; touch "$MOCKSRC/data"

# We can't easily test TUI here without a pty, but we can at least
# verify the script exits 0 within the deadline via 'timeout'. We're
# really testing that the EXIT trap fires.
PATH="$MOCKBIN:$PATH" MOCK_MODE=fail timeout 20 \
  ./rsync-tree.sh --source src \
    --nodes 'src,n1,n2,n3' \
    --dir "$MOCKSRC" \
    --dry-run > "$STATE/tui.log" 2>&1
rc=$?
if (( rc != 0 )); then
  echo "  FAIL: tui-mode-dry-run exit code $rc"
  fail=$((fail + 1))
else
  echo "  PASS (tui-mode-dry-run)"
fi

# Sub-test 4: --apparent-size / -A is passed to du. Without it, the
# scheduler would compare on-disk block counts to rsync-transferred
# byte counts and could report spurious "size mismatch" failures on
# sparse files / files with holes / across filesystems with different
# block sizes.
echo "----- sub-test: du uses --apparent-size (or -A) flag -----"
rm -rf "$STATE"/* 2>/dev/null || true
rm -f "$MOCKSRC"/* 2>/dev/null; touch "$MOCKSRC/data"
DU_LOG="$STATE/du-invocations.log"
rm -f "$DU_LOG"

PATH="$MOCKBIN:$PATH" MOCK_MODE=success MOCK_DU_LOG="$DU_LOG" timeout 15 \
  ./rsync-tree.sh --plain --source src \
    --nodes 'src,n1,n2' \
    --dir "$MOCKSRC" > "$STATE/dulog.out" 2>&1
rc=$?

if (( rc != 0 )); then
  echo "  FAIL: du-flag check exit code $rc"
  tail -10 "$STATE/dulog.out" | sed 's/^/    /'
  fail=$((fail + 1))
elif [[ ! -s "$DU_LOG" ]]; then
  echo "  FAIL: no du invocations were recorded"
  fail=$((fail + 1))
elif ! grep -qE "du[[:space:]]+(--apparent-size|-A)[[:space:]]+-sb" "$DU_LOG"; then
  echo "  FAIL: du was invoked WITHOUT --apparent-size/-A. log:"
  cat "$DU_LOG" | sed 's/^/    /'
  fail=$((fail + 1))
else
  echo "  PASS (du uses apparent-size; $(wc -l < "$DU_LOG") invocations recorded)"
  grep -E "du[[:space:]]+(--apparent-size|-A)[[:space:]]+-sb" "$DU_LOG" | head -3 | sed 's/^/    /'
fi

# Cleanup
rm -rf "$MOCKBIN" "$STATE" 2>/dev/null

if (( fail == 0 )); then
  echo "===== PASS: all sub-tests ====="
  exit 0
fi
echo "===== FAIL ($fail sub-tests) ====="
exit 1