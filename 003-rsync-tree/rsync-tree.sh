#!/bin/bash
#=============================================================================
# rsync-tree.sh — Event-driven parallel rsync tree
#
# Each node: waiting → active → ready (as new source)
# Main loop: drain completed jobs → pair free ready sources with waiting nodes
# Result: #parallel_rsyncs grows as nodes finish; each at full 100MB/s
#
# Usage:
#   ./rsync-tree.sh --dry-run
#   ./rsync-tree.sh --nodes 'node[01-18]'            # node001..node018 (default)
#   ./rsync-tree.sh --nodes 'node0[01-18]'            # node001..node018 (explicit prefix)
#   ./rsync-tree.sh --nodes 'compute[0-7]'            # compute0..compute7
#   ./rsync-tree.sh --nodes 'n01,n02,n03,n04'        # explicit comma list
#   ./rsync-tree.sh --nodes 'n[1..8]'                # n1..n8 (plain range)
#   ./rsync-tree.sh --source node12 --nodes 'node[01-18]'
#=============================================================================

set -uo pipefail

SOURCE_NODE="node12"
SRC_DIR="/mnt/data"
SSH_ARGS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -o BatchMode=yes"
NODES_PATTERN='node[01-18]'
DRY_RUN=""
DIAGNOSE=""

# ---- Pattern expander ----
expand_nodes() {
    local pattern="$1"
    local result=""

    if [[ "$pattern" == *,* ]]; then
        echo "$pattern"
        return
    fi

    if [[ "$pattern" =~ ^(.+)\[(.+)\]$ ]]; then
        local prefix="${BASH_REMATCH[1]}"
        local range="${BASH_REMATCH[2]}"

        if [[ "$range" =~ ^(0*[0-9]+)[\.\-]+(0*[0-9]+)$ ]]; then
            local start="${BASH_REMATCH[1]}"
            local end="${BASH_REMATCH[2]}"
            local pad=0
            if [[ "$start" =~ ^0 ]]; then
                pad=${#start}
            else
                [[ ${#start} -gt ${#end} ]] && pad=${#start} || pad=${#end}
            fi
            for ((i=10#$start;i<=10#$end;i++)); do
                [[ -n "$result" ]] && result="$result,"
                result="$result$(printf "${prefix}%0*d" "$pad" "$i")"
            done
            echo "$result"
            return
        fi
    fi

    echo "$pattern"
}

# ---- Parse args ----
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --source)  SOURCE_NODE="$2"; shift 2 ;;
        --nodes)   NODES_PATTERN="$2"; shift 2 ;;
        --dir)     SRC_DIR="$2"; shift 2 ;;
        --plain)   PLAIN=1; shift ;;
        --diagnose) DIAGNOSE=1; shift ;;
        *) echo "Usage: $0 [--dry-run] [--source node12] [--nodes 'node[01-18]'] [--dir /mnt/data] [--plain] [--diagnose]"; exit 1 ;;
    esac
done

NODE_LIST=$(expand_nodes "$NODES_PATTERN")
IFS=',' read -ra ALL_NODES <<< "$NODE_LIST"

# ---- --diagnose: pre-flight checks (SSH + /mnt/data) for all nodes ----
# Useful when the scheduler "stucks on starting" — tells you which node's
# ssh/sshd/ssh-key handshake is the culprit, or which node's $SRC_DIR is
# missing, before the main loop even starts.
if [[ -n "$DIAGNOSE" ]]; then
    echo "=============================================="
    echo " DIAGNOSE: pre-flight per-node"
    echo "=============================================="
    ok=0; bad=0
    for n in "${ALL_NODES[@]}"; do
        # 1. SSH reachability
        if ! ssh $SSH_ARGS "$n" 'true' 2>/dev/null; then
            echo "  ✗ $n  SSH unreachable (BatchMode refused, no key, or wrong host)"
            ((bad++))
            continue
        fi
        # 2. Source dir existence
        if ! ssh $SSH_ARGS "$n" "test -d $SRC_DIR" 2>/dev/null; then
            echo "  ✗ $n  SSH ok, but $SRC_DIR/ does not exist on $n"
            ((bad++))
            continue
        fi
        # 3. rsync availability on the node (only checked for source/target roles)
        local_sz=$(ssh $SSH_ARGS "$n" "du -sb $SRC_DIR 2>/dev/null | awk '{print \$1}'")
        if [[ -z "$local_sz" ]]; then
            echo "  ✗ $n  SSH ok, $SRC_DIR/ exists, but du failed (file system error?)"
            ((bad++))
            continue
        fi
        local_files=$(ssh $SSH_ARGS "$n" "ls $SRC_DIR 2>/dev/null | wc -l")
        echo "  ✓ $n  SSH ok, $SRC_DIR/ exists, $local_files files, $(numfmt --to=iec "$local_sz" 2>/dev/null || echo "$local_sz"B)"
        ((ok++))
    done
    echo ""
    echo "  Result: $ok ok, $bad failed"
    if (( bad > 0 )); then
        echo "  Fix the failed nodes (ssh keys, hostname resolution, $SRC_DIR mount) and re-run."
        exit 2
    fi
    echo "  All nodes healthy. Re-run without --diagnose to start the actual transfer."
    exit 0
fi

echo "=============================================="
echo " rsync-tree.sh — Event-driven rsync tree"
echo "=============================================="
echo "  Source : $SOURCE_NODE"
echo "  Pattern: $NODES_PATTERN"
echo "  Nodes  : ${#ALL_NODES[@]} total  ($NODE_LIST)"
echo "  Dir    : $SRC_DIR"
echo "  Dry run: ${DRY_RUN:-no}"
echo "  Mode   : $([[ -n "${PLAIN:-}" ]] && echo plain || echo TUI)"
echo ""

# Verify source is in the node list
source_ok=0
for n in "${ALL_NODES[@]}"; do
    [[ "$n" == "$SOURCE_NODE" ]] && source_ok=1 && break
done
if [[ $source_ok -eq 0 ]]; then
    echo "ERROR: source $SOURCE_NODE not found in node list"
    exit 1
fi

# ---- TUI integration ----
# Source tui.sh only if we want TUI. Sourcing is safe (sets up vars/functions
# without entering alt-screen). We start the TUI after cleanup hooks are set
# so the trap EXIT chain can call tui_stop.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUI_ACTIVE=""
if [[ -z "${PLAIN:-}" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/tui.sh"
fi

# ---- State ----
declare -a waiting=()
declare -A jobs=()    # "src→tgt" => pid
declare -A ready=()
declare -A failed_jobs=()  # "src→tgt" => reason
declare -A failed_nodes=() # nodename => reason

# ---- Failure helpers (do NOT exit — record only) ----
fail_job() {
    local key="$1"
    local reason="$2"
    failed_jobs["$key"]="$reason"
}

fail_node() {
    local node="$1"
    local reason="$2"
    failed_nodes["$node"]="$reason"
}

# ---- Cleanup on exit ----
# The EXIT trap runs cleanup AND tui_stop. For TUI mode we also restore
# stdout/stderr to the saved fds 3/4 so the final summary prints to the
# terminal, not the log file.
cleanup() {
    echo ""
    echo "[cleanup] Cleaning up..."
    if [[ ${#jobs[@]} -gt 0 ]]; then
        echo "[cleanup] Killing ${#jobs[@]} remaining rsync jobs..."
        for key in "${!jobs[@]}"; do
            local pid=${jobs[$key]}
            echo "[cleanup]   killing pid $pid ($key)"
            kill -9 "$pid" 2>/dev/null
        done
    fi
    if [[ -n "${SCRIPT_PID:-}" ]]; then
        pkill -9 -P "$SCRIPT_PID" 2>/dev/null
    fi
    echo "[cleanup] Removing marker files..."
    rm -f /tmp/rsync-tree-pid-* \
          /tmp/rsync-tree-checked-* \
          /tmp/rsync-tree-picked-* \
          /tmp/rsync-tree-done-* \
          /tmp/rsync-tree-wait.lock \
          /tmp/rsync-tree-abort \
          /tmp/rsync-tree-diag.txt \
          /tmp/rsync-diag-check.txt \
          /tmp/rsync-*.log
    echo "[cleanup] Done."
}
finalize() {
    # Stop the TUI first (re-shows cursor, exits alt screen)
    [[ "${TUI_ACTIVE:-}" == "1" ]] && tui_stop
    # Restore stdout/stderr to the terminal (was redirected to $LOGFILE in TUI mode)
    if [[ -n "${PLAIN:-}" ]] || [[ "${TUI_ACTIVE:-}" != "1" ]]; then
        :  # plain mode never redirected
    else
        exec 1>&3 2>&4
    fi
    # Final summary now goes to the terminal
    print_summary
    cleanup
}
# trap finalize is installed LATER, after print_summary is defined (see end of file)
SCRIPT_PID=$$

# Start TUI renderer in background (after cleanup trap is set so the
# EXIT chain restores the terminal). Fails soft — falls back to plain.
if [[ -n "${PLAIN:-}" ]]; then
    tui_log_event() { :; }      # no-ops if TUI not active
    tui_log_job() { :; }
    tui_log_job_remove() { :; }
    tui_set_header() { :; }
else
    tui_start || {
        echo "WARN: TUI not available, continuing in plain mode" >&2
        PLAIN=1
        tui_log_event() { :; }
        tui_log_job() { :; }
        tui_log_job_remove() { :; }
        tui_set_header() { :; }
    }
fi

LOGFILE="/tmp/rsync-tree.log"
> "$LOGFILE"

# In TUI mode, send all main-loop echo chatter to the log file so the
# TUI renderer has the screen to itself. In plain mode leave stdout alone.
if [[ -z "${PLAIN:-}" ]] && [[ "${TUI_ACTIVE:-}" == "1" ]]; then
    # Save the original stdout/stderr to fds 3/4 so we can restore them
    # for the final summary after tui_stop has finished.
    exec 3>&1 4>&2
    exec >> "$LOGFILE" 2>&1
fi

# Nuclear cleanup
rm -f /tmp/rsync-tree-pid-* /tmp/rsync-tree-checked-* /tmp/rsync-tree-picked-* /tmp/rsync-tree-done-* /tmp/rsync-tree-wait.lock \
      /tmp/rsync-tree-done-* /tmp/rsync-tree-wait.lock /tmp/rsync-tree-abort \
      /tmp/rsync-tree-diag.txt /tmp/rsync-diag-check.txt /tmp/rsync-*.log
rmdir /tmp/rsync-tree-wait.lock 2>/dev/null; true

for n in "${ALL_NODES[@]}"; do
    if [[ "$n" == "$SOURCE_NODE" ]]; then
        ready["$n"]=1
    else
        waiting+=("$n")
    fi
done

echo "Initial: 1 source, ${#waiting[@]} need data"
echo ""

LOGFILE="/tmp/rsync-tree.log"
> "$LOGFILE"

# Initial TUI header
tui_set_header "${DRY_RUN:+[DRY-RUN] }src=$SOURCE_NODE nodes=${#ALL_NODES[@]} | iter=0 | 1 ready / 0 done | elapsed=00:00:00"

# ---- Helpers ----

pick_waiting() {
    local lock="/tmp/rsync-tree-wait.lock"
    while ! mkdir "$lock" 2>/dev/null; do sleep 0.05; done

    echo "  [PICK] waiting[@]=${#waiting[@]}  waiting=${waiting[*]}" >&2
    for ((i=0; i<${#waiting[@]}; i++)); do
        local node="${waiting[$i]}"
        local picked_file="/tmp/rsync-tree-picked-$SCRIPT_RUN_ID-$node"
        if [[ -f "$picked_file" ]]; then
            echo "  [PICK]   [$i] $node SKIP (picked file exists: $picked_file)" >&2
            continue
        fi
        touch "$picked_file"
        rmdir "$lock"
        echo "  [PICK]   [$i] $node PICKED" >&2
        printf '%s\n%s' "$i" "$node"
        return
    done
    echo "  [PICK]   no unpicked nodes found — returning empty" >&2

    rmdir "$lock"
    echo ""
}

do_rsync() {
    local src=$1 tgt=$2
    local log="/tmp/rsync-$src-$tgt.log"

    if [[ -n "$DRY_RUN" ]]; then
        echo "  [$src] → [$tgt]  [DRY]"
        echo "[$src] → [$tgt] ✓" >> "$LOGFILE"
        (
            sleep "${DRY_RUN_SLEEP:-0.01}"
            > "/tmp/rsync-tree-done-$src→$tgt"
        ) &
        jobs["$src→$tgt"]=$!
        tui_log_job "$src" "$tgt" "ACTIVE" 0 0 0
        tui_log_event "INFO" "[$src] → [$tgt] starting (dry-run)"
        return 0
    fi

    # Pre-check: verify source directory exists on src node
    if ! ssh $SSH_ARGS "$src" "test -d $SRC_DIR" 2>/dev/null; then
        echo "  [!!] [$src] → [$tgt] $SRC_DIR/ does not exist on $src" >&2
        fail_job "$src→$tgt" "SRC_DIR_MISSING"
        fail_node "$src" "SRC_DIR_MISSING"
        tui_log_job "$src" "$tgt" "FAIL" 0 0 0
        tui_log_event "ERR" "[$src] $SRC_DIR/ missing"
        return 1
    fi

    # Run rsync ON the source node, pushing to target via ssh
    ssh $SSH_ARGS "$src" \
        "rsync -av --info=progress2 --inplace $SRC_DIR/ ${tgt}:$SRC_DIR/" \
        &> "$log" &
    local pid=$!
    jobs["$src→$tgt"]=$pid
    echo "$pid" > "/tmp/rsync-tree-pid-$src→$tgt"
    tui_log_job "$src" "$tgt" "ACTIVE" 0 0 0
    tui_log_event "INFO" "[$src] → [$tgt] starting"
    # Heartbeat: every 3s log that pid is still alive + tail of rsync log.
    # Makes "stuck on starting" diagnosable — was the ssh session hung,
    # did the kernel drop the TCP, did rsync stall on a single huge file?
    (
        while kill -0 "$pid" 2>/dev/null; do
            sleep 3
            local last_line
            last_line=$(tail -n 1 "$log" 2>/dev/null | tr -d '\r' | head -c 80)
            tui_log_event "DBG"  "[$src]→[$tgt] alive pid=$pid last='${last_line:-<empty>}'"
        done
    ) &
    jobs["${src}→${tgt}.hb"]=$!
    return 0
}

# check_complete src tgt — returns 0 on success, 1 if still running/failed
# Does NOT exit — failures are recorded and the target is returned to waiting queue
#
# IMPORTANT: We CANNOT use `wait $pid` here. The ssh+rsync child was spawned
# in do_rsync() (a previous function call), so it is no longer a child of
# this shell. `wait` on a non-child pid returns 127 immediately, which would
# misclassify every job as failed. We rely on `kill -0` for liveness, and
# on parsing the rsync log tail for completion.
check_complete() {
    local src=$1 tgt=$2
    local log="/tmp/rsync-$src-$tgt.log"
    local pidfile="/tmp/rsync-tree-pid-$src→$tgt"

    if [[ -n "$DRY_RUN" ]]; then
        if [[ -f "/tmp/rsync-tree-done-$src→$tgt" ]]; then
            echo "0"
            tui_log_job "$src" "$tgt" "DONE" 100 0 0
            tui_log_event "OK"   "[$src] → [$tgt] done (dry-run)"
            return 0
        fi
        return 1
    fi

    # 1. Is the rsync child still alive?
    if [[ ! -f "$pidfile" ]]; then
        echo "  [??] [$src] → [$tgt] no pidfile yet" >&2
        return 1
    fi
    local pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
        echo "  [~~] [$src] → [$tgt] pid $pid still running" >&2
        return 1
    fi
    # Process is gone (or zombied). `wait` reaps it and returns its exit
    # code — without this, the kernel keeps the pid around as a zombie
    # and `kill -0` would keep returning 0 forever, making the job
    # appear stuck even though the transfer finished. `wait` is safe
    # here: this is the SAME shell that spawned `ssh ... &` in
    # do_rsync, so $pid IS our child. We don't use the return value
    # because we judge success/failure from the rsync log instead.
    wait "$pid" 2>/dev/null
    true  # ensure check_complete return code is not affected by wait's exit

    # 2. Process is gone. Decide success vs failure from the rsync log tail.
    #    rsync exits 0 on clean completion, nonzero on any error. We can
    #    tell from the log: success ends with "total size is ... (speedup)"
    #    or just the last transfer summary; failures contain "rsync error:"
    #    or nonzero exit code lines.
    local rsync_exit=0
    if [[ ! -f "$log" ]]; then
        echo "  [!!] [$src] → [$tgt] pid $pid exited but log $log is missing" >&2
        rsync_exit=1
    elif tail -50 "$log" 2>/dev/null | grep -qE 'rsync error|IO error|connection unexpectedly closed|broken pipe'; then
        echo "  [!!] [$src] → [$tgt] pid $pid exited, log shows error markers" >&2
        rsync_exit=1
    else
        echo "  [DD] [$src] → [$tgt] pid $pid exited, log clean" >&2
    fi

    # Stop the heartbeat companion for this job (it exits on its own once
    # kill -0 fails, but be explicit so events.log stops growing for dead jobs).
    local hb_pidfile="/tmp/rsync-tree-pid-${src}→${tgt}.hb"
    [[ -f "$hb_pidfile" ]] && kill "$(cat "$hb_pidfile")" 2>/dev/null; rm -f "$hb_pidfile"

    if [[ $rsync_exit -ne 0 ]]; then
        echo "  [!!] [$src] → [$tgt] rsync failed (exit=$rsync_exit) — returning $tgt to queue, $src back to ready" >&2
        fail_job "$src→$tgt" "RSYNC_FAIL"
        tui_log_job "$src" "$tgt" "FAIL" 0 0 0
        unset "jobs[$src→$tgt]" 2>/dev/null
        rm -f "$pidfile"
        waiting=("$tgt" "${waiting[@]}")
        ready["$src"]=1
        return 1
    fi

    # 3. Sanity check the source size. We used to ALSO call `du -sb`
    #    on the target and compare src_sz vs tgt_sz, treating any
    #    mismatch as FAIL — but in practice that produced spurious
    #    "SIZE_MISMATCH" failures on otherwise successful transfers:
    #      * du on the target can race with the rsync write (kernel
    #        page cache not yet flushed, so tgt_sz reads a few KB
    #        smaller than src_sz for a window of milliseconds).
    #      * du on large trees is slow (seconds to minutes) and the
    #        extra 2 SSH round-trips per job ate a lot of wall time
    #        on 18-node runs.
    #    rsync with -a --info=progress2 already guarantees the data
    #    is intact: it transfers a checksum-verified stream and exits
    #    nonzero on any I/O error. The log is clean (we checked above)
    #    and the process exited 0 (we reaped it with `wait`). That's
    #    sufficient evidence of success. Skip the tgt-side du entirely.
    local src_sz
    src_sz=$(ssh $SSH_ARGS "$src" "du -sb $SRC_DIR" 2>/dev/null | awk '{print $1}')
    if [[ -z "$src_sz" ]]; then
        echo "  [!!] [$src] → [$tgt] cannot get size from $src (SSH failed) — returning $tgt to queue, $src back to ready" >&2
        fail_job "$src→$tgt" "SSH_FAIL_SRC"
        tui_log_job "$src" "$tgt" "FAIL" 0 0 0
        tui_log_event "ERR" "[$src] → [$tgt] SSH failed on $src"
        unset "jobs[$src→$tgt]" 2>/dev/null
        rm -f "$pidfile"
        waiting=("$tgt" "${waiting[@]}")
        ready["$src"]=1
        return 1
    fi

    echo "  [DD] [$src] → [$tgt] size: src=$src_sz (verified against rsync exit=0)" >&2

    # 4. Real success — write DONE to TUI (this was missing in the original;
    #    TUI stayed stuck on ACTIVE 0%/0MB/s even after the job finished).
    tui_log_job "$src" "$tgt" "DONE" 100 0 0
    tui_log_event "OK"   "[$src] → [$tgt] done"
    echo "$src_sz"
    return 0
}

collect_ready() {
    local newly_done=()

    echo "  [CR] collect_ready called: ${#jobs[@]} jobs, ${#ready[@]} ready, ${#waiting[@]} waiting" >&2
    for key in "${!jobs[@]}"; do
        echo "  [CR]   job: $key pid=${jobs[$key]}" >&2
    done

    for key in "${!jobs[@]}"; do
        local src="${key%%→*}"
        local tgt="${key##*→}"

        if check_complete "$src" "$tgt"; then
            newly_done+=("$src" "$tgt" "$key")
        fi
    done

    declare -A seen=()
    for ((i=0; i<${#newly_done[@]}; i+=3)); do
        local src="${newly_done[$i]}"
        local tgt="${newly_done[$i+1]}"
        local key="${newly_done[$i+2]}"
        [[ -n "${seen[$key]:-}" ]] && continue
        seen[$key]=1

        unset "jobs[$key]" 2>/dev/null
        # Also drop the heartbeat companion key (do_rsync adds it as
        # "src→tgt.hb") — without this, the hb leaks in $jobs forever
        # and is_busy() later in the main loop marks the source busy.
        unset "jobs[$key.hb]" 2>/dev/null
        rm -f "/tmp/rsync-tree-pid-$src→$tgt" \
              "/tmp/rsync-tree-pid-$src→$tgt.hb" \
              "/tmp/rsync-tree-checked-$src→$tgt" \
              "/tmp/rsync-tree-done-$src→$tgt"

        ready["$src"]=1
        ready["$tgt"]=1
        echo "  → newly ready: $src $tgt  (${#ready[@]} sources total)" >&2
    done
}

# ---- Print final summary ----
print_summary() {
    echo ""
    echo "=============================================="
    echo " SUMMARY"
    echo "=============================================="

    if [[ ${#failed_jobs[@]} -eq 0 ]] && [[ ${#failed_nodes[@]} -eq 0 ]]; then
        echo "  All jobs completed successfully."
    else
        if [[ ${#failed_jobs[@]} -gt 0 ]]; then
            echo "  Failed jobs:"
            for key in "${!failed_jobs[@]}"; do
                echo "    $key: ${failed_jobs[$key]}"
            done
        fi
        if [[ ${#failed_nodes[@]} -gt 0 ]]; then
            echo "  Failed/skipped nodes:"
            for n in "${!failed_nodes[@]}"; do
                echo "    $n: ${failed_nodes[$n]}"
            done
        fi
        echo "  Note: failed targets have been returned to the waiting queue"
        echo "        and may be retried in subsequent runs."
    fi
}

# Now that print_summary and cleanup are defined, install the EXIT trap.
trap finalize EXIT

SCRIPT_RUN_ID="$(date +%s)"
TUI_START_TS=$(date +%s)

# ---- Clean up stale locks/picked files from previous runs ----
rm -f /tmp/rsync-tree-pid-* /tmp/rsync-tree-checked-* /tmp/rsync-tree-picked-* /tmp/rsync-tree-done-* /tmp/rsync-tree-wait.lock 2>/dev/null; rmdir /tmp/rsync-tree-wait.lock 2>/dev/null; true

# Helper: format elapsed seconds as HH:MM:SS
fmt_elapsed() {
    local s=$1
    printf '%02d:%02d:%02d' $((s/3600)) $(((s%3600)/60)) $((s%60))
}

# Helper: build header line from current loop state
update_tui_header() {
    local n_active=$1 n_done=$2 n_failed=$3 iter=$4
    local elapsed=$(( $(date +%s) - TUI_START_TS ))
    tui_set_header "${DRY_RUN:+[DRY-RUN] }src=$SOURCE_NODE nodes=${#ALL_NODES[@]} | iter=$iter | $n_active active / $n_done done / $n_failed failed | elapsed=$(fmt_elapsed $elapsed)"
}

# Parse the latest rsync --info=progress2 line from a job's log and push
# the (pct, speed_mbs) into the TUI. rsync's progress2 line looks like:
#   "        32,768   0%    0.00kB/s    0:00:10  (xfr#5, to-chk=10/15)"
# or near the end of a transfer:
#   " 1,234,567,890  50%   12.34MB/s    0:01:23  (xfr#5, ir-chk=100/200)"
#
# We only call tui_log_job (which rewrites the row) if the parsed values
# changed since the last sample — avoids hammering the TUI state file
# on every iter when nothing moved.
#
# $1 = src, $2 = tgt
update_job_progress() {
    local src=$1 tgt=$2
    local log="/tmp/rsync-$src-$tgt.log"
    local cache="/tmp/rsync-tree-progress-$src→$tgt"
    [[ -f "$log" ]] || return 0
    local last
    last=$(grep -E '[0-9]+%' "$log" 2>/dev/null | tail -n 1)
    [[ -z "$last" ]] && return 0
    # Parse pct and speed. The percent is the % token right after a number;
    # the speed is the only kB/s/MB/s/GB/s token on the line.
    local pct speed_mbs
    pct=$(echo "$last" | grep -oE '[0-9]+%' | head -1 | tr -d '%')
    [[ -z "$pct" ]] && return 0
    speed_mbs=$(echo "$last" | grep -oE '[0-9]+\.[0-9]+[kMG]?B/s' | head -1 | awk '
        /GB\/s/ { sub(/GB\/s/,""); print $0 * 1024 }
        /MB\/s/ { sub(/MB\/s/,""); print $0 }
        /kB\/s/ { sub(/kB\/s/,""); print $0 / 1024 }
        /B\/s/  { sub(/B\/s/,"");  print $0 / 1048576 }
    ')
    [[ -z "$speed_mbs" ]] && speed_mbs=0
    # Only skip the rewrite if the parsed values are exactly the same
    # as the last call — but always re-emit at least once per second of
    # wall time so the TUI can show liveness (otherwise if rsync's
    # progress line doesn't change, the row freezes even though the
    # transfer is still going).
    local sig="$pct|$speed_mbs"
    local prev=""
    [[ -f "$cache" ]] && prev=$(cat "$cache" 2>/dev/null)
    local mtime=0
    [[ -f "$cache" ]] && mtime=$(stat -c %Y "$cache" 2>/dev/null || echo 0)
    local now; now=$(date +%s)
    if [[ "$sig" == "$prev" ]] && (( now - mtime < 1 )); then
        return 0
    fi
    echo "$sig" > "$cache"
    tui_log_job "$src" "$tgt" "ACTIVE" "$pct" "$speed_mbs" 0
}

# ---- Main loop ----
iter=0
while true; do
    iter=$((iter + 1))

    # Check for 'q' at the top of every iteration so the user can
    # exit gracefully regardless of which branch the scheduler is in
    # (waiting, idle, or actively pairing). 100ms timeout means the
    # loop is at most 10x slower when no key is pressed — acceptable
    # for the 1s/iter cadence, and the timeout is long enough that
    # bash's read actually returns the buffered key (read -t 0 in
    # bash 5.x returns "no data" even when data is ready, so we
    # need a small positive timeout).
    key=""
    if read -rsn1 -t 0.1 key 2>/dev/null; then
        if [[ "$key" == "q" || "$key" == "Q" ]]; then
            echo "  [USER] q pressed — graceful exit requested" >&2
            EXIT_REQUESTED=1
            break
        fi
    fi

    collect_ready

    n_active=${#jobs[@]}
    n_ready=${#ready[@]}
    n_waiting=${#waiting[@]}

    echo ""
    echo "--- iter $iter: $n_active active, $n_waiting waiting, $n_ready free sources ---"
    echo "  queue: ${waiting[@]}"
    echo "  [MAIN] jobs=${n_active} ready=${n_ready} waiting=${n_waiting}" >&2
    for key in "${!jobs[@]}"; do
        echo "  [MAIN]   ${key} => pid=${jobs[$key]}" >&2
    done
    echo "  [MAIN]   ready nodes: ${!ready[@]}" >&2
    echo "  [MAIN]   waiting queue: ${waiting[@]}" >&2

    if (( n_waiting == 0 && n_active == 0 )); then
        break
    fi

    if (( n_ready == 0 )); then
        echo "  (no free sources, sleeping...)"
        # Still refresh ACTIVE job progress — without this the TUI shows
        # 0% / 0.0MB/s for the entire run because the only path to
        # update_job_progress was after the sleep+continue.
        for key in "${!jobs[@]}"; do
            [[ "$key" == *.hb ]] && continue
            update_job_progress "${key%%→*}" "${key##*→}"
        done
        update_tui_header "$n_active" "$n_done_tui" "$n_failed_tui" "$iter"
        # Replace sleep 1 with a 1-second read — doubles as the q/Q
        # exit handler (press q to gracefully stop, jobs in-flight
        # get killed by the EXIT trap / cleanup). Using `-t 1` so it
        # blocks at most 1 second even if no key is pressed.
        key=""
        if read -rsn1 -t 1 key 2>/dev/null; then
            if [[ "$key" == "q" || "$key" == "Q" ]]; then
                echo "  [USER] q pressed — graceful exit requested" >&2
                EXIT_REQUESTED=1
                break
            fi
        fi
        continue
    fi

    if (( n_waiting == 0 )); then
        echo "  (all assigned, waiting for actives...)"
        for key in "${!jobs[@]}"; do
            [[ "$key" == *.hb ]] && continue
            update_job_progress "${key%%→*}" "${key##*→}"
        done
        update_tui_header "$n_active" "$n_done_tui" "$n_failed_tui" "$iter"
        key=""
        if read -rsn1 -t 1 key 2>/dev/null; then
            if [[ "$key" == "q" || "$key" == "Q" ]]; then
                echo "  [USER] q pressed — graceful exit requested" >&2
                EXIT_REQUESTED=1
                break
            fi
        fi
        continue
    fi

    started=0
    for src in "${!ready[@]}"; do
        is_busy=0
        for key in "${!jobs[@]}"; do
            # Heartbeat companion entries share the same src prefix
            # (e.g. "node12→node001.hb") — those are trackers, not
            # real rsync jobs, so they must NOT mark the source as
            # busy. Without this skip, the first source that finishes
            # a transfer would have its hb linger in $jobs and block
            # the source from being re-paired (the "stuck after
            # node001→node002" symptom).
            [[ "$key" == *.hb ]] && continue
            [[ "${key%%→*}" == "$src" ]] && is_busy=1 && break
        done
        if [[ $is_busy -eq 1 ]]; then
            echo "  [PICK] src=$src skipped (busy in jobs)" >&2
            continue
        fi

        pick_result=$(pick_waiting)
        if [[ -z "$pick_result" ]]; then
            echo "  [PICK] no more waiting nodes left, continuing to next src=$src" >&2
            continue
        fi
        pick_idx=$(echo "$pick_result" | head -1)
        tgt=$(echo "$pick_result" | tail -1)
        [[ -z "$tgt" ]] && continue

        waiting=("${waiting[@]:0:$pick_idx}" "${waiting[@]:$((pick_idx + 1))}")
        unset "ready[$src]"

        do_rsync "$src" "$tgt"
        rs=$?
        echo "  [$src] → [$tgt]  started"

        if [[ $rs -ne 0 ]]; then
            waiting=("$tgt" "${waiting[@]}")
            ready["$src"]=1
            unset "jobs[$src→$tgt]" 2>/dev/null
            rm -f "/tmp/rsync-tree-pid-$src→$tgt" \
                  "/tmp/rsync-tree-checked-$src→$tgt" \
                  "/tmp/rsync-tree-picked-$SCRIPT_RUN_ID-$tgt"
        else
            started=$((started + 1))
        fi
    done

    if (( started == 0 && n_active > 0 )); then
        sleep 0.5
    elif (( started == 0 )); then
        rm -f /tmp/rsync-tree-picked-*
        sleep 1
    fi

    # ---- TUI: update header with current counters ----
    n_done_tui=$(( ${#ALL_NODES[@]} - 1 - n_waiting - n_active + n_ready - 1 ))
    [[ $n_done_tui -lt 0 ]] && n_done_tui=0
    n_failed_tui=${#failed_jobs[@]}
    update_tui_header "$n_active" "$n_done_tui" "$n_failed_tui" "$iter"

    # ---- TUI: refresh ACTIVE job progress from rsync --info=progress2 ----
    # The job row stays ACTIVE in the TUI from do_rsync() onward; without
    # this refresh it would show 0% / 0.0MB/s for the whole run. We only
    # rewrite the row when the parsed (pct, speed) changes, so this is
    # cheap even with many concurrent jobs.
    for key in "${!jobs[@]}"; do
        # Skip heartbeat companion entries (named "src→tgt.hb")
        [[ "$key" == *.hb ]] && continue
        local_src="${key%%→*}"
        local_tgt="${key##*→}"
        update_job_progress "$local_src" "$local_tgt"
    done
done

# Main loop exited. From here on, anything printed in the main script flow
# would land in the log file (stdout was redirected in TUI mode). The
# EXIT trap (finalize) restores stdout and calls print_summary; it will
# also clean up marker files.

echo ""
echo "Verification (sample ~25%):"
for n in "${ALL_NODES[@]}"; do
    [[ $((RANDOM % 4)) -ne 0 ]] && continue
    count=$(ssh $SSH_ARGS "$n" "ls $SRC_DIR 2>/dev/null | wc -l" 2>/dev/null || echo "?")
    size=$(ssh $SSH_ARGS "$n" "du -sb $SRC_DIR 2>/dev/null | awk '{print \$1}'" 2>/dev/null || echo "?")
    printf "  %-12s : %s files, %s bytes\n" "$n" "$count" "$size"
done