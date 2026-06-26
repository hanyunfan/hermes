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

# ---- State directory (avoid /tmp — may be NFS/broken; $HOME is reliable) ----
STATE_DIR="${RSYNC_TREE_STATE_DIR:-$HOME/.rsync-tree-state}"
mkdir -p "$STATE_DIR" || { echo "FATAL: cannot mkdir $STATE_DIR" >&2; exit 2; }

SOURCE_NODE="node12"
SRC_DIR="/mnt/data"
SSH_ARGS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -o BatchMode=yes"
NODES_PATTERN='node[01-18]'
DRY_RUN=""

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
        *) echo "Usage: $0 [--dry-run] [--source node12] [--nodes 'node[01-18]'] [--dir /mnt/data]"; exit 1 ;;
    esac
done

NODE_LIST=$(expand_nodes "$NODES_PATTERN")
IFS=',' read -ra ALL_NODES <<< "$NODE_LIST"

echo "=============================================="
echo " rsync-tree.sh — Event-driven rsync tree"
echo "=============================================="
echo "  Source : $SOURCE_NODE"
echo "  Pattern: $NODES_PATTERN"
echo "  Nodes  : ${#ALL_NODES[@]} total  ($NODE_LIST)"
echo "  Dir    : $SRC_DIR"
echo "  Dry run: ${DRY_RUN:-no}"
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
    rm -f $STATE_DIR/rsync-tree-pid-* \
          $STATE_DIR/rsync-tree-checked-* \
          $STATE_DIR/rsync-tree-picked-* \
          $STATE_DIR/rsync-tree-done-* \
          $STATE_DIR/rsync-tree-wait.lock \
          $STATE_DIR/rsync-tree-abort \
          $STATE_DIR/rsync-tree-diag.txt \
          $STATE_DIR/rsync-diag-check.txt \
          $STATE_DIR/rsync-*.log
    echo "[cleanup] Done."
}
trap cleanup EXIT
SCRIPT_PID=$$

# Nuclear cleanup
rm -f $STATE_DIR/rsync-tree-pid-* $STATE_DIR/rsync-tree-checked-* $STATE_DIR/rsync-tree-picked-* $STATE_DIR/rsync-tree-done-* $STATE_DIR/rsync-tree-wait.lock \
      $STATE_DIR/rsync-tree-done-* $STATE_DIR/rsync-tree-wait.lock $STATE_DIR/rsync-tree-abort \
      $STATE_DIR/rsync-tree-diag.txt $STATE_DIR/rsync-diag-check.txt $STATE_DIR/rsync-*.log
rmdir $STATE_DIR/rsync-tree-wait.lock 2>/dev/null; true

for n in "${ALL_NODES[@]}"; do
    if [[ "$n" == "$SOURCE_NODE" ]]; then
        ready["$n"]=1
    else
        waiting+=("$n")
    fi
done

echo "Initial: 1 source, ${#waiting[@]} need data"
echo ""

LOGFILE="$STATE_DIR/rsync-tree.log"
> "$LOGFILE"

# ---- Helpers ----

pick_waiting() {
    local lock="$STATE_DIR/rsync-tree-wait.lock"
    while ! mkdir "$lock" 2>/dev/null; do sleep 0.05; done

    echo "  [PICK] waiting[@]=${#waiting[@]}  waiting=${waiting[*]}" >&2
    for ((i=0; i<${#waiting[@]}; i++)); do
        local node="${waiting[$i]}"
        local picked_file="$STATE_DIR/rsync-tree-picked-$SCRIPT_RUN_ID-$node"
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
    local log="$STATE_DIR/rsync-$src-$tgt.log"

    if [[ -n "$DRY_RUN" ]]; then
        echo "  [$src] → [$tgt]  [DRY]"
        echo "[$src] → [$tgt] ✓" >> "$LOGFILE"
        (
            sleep 0.01
            > "$STATE_DIR/rsync-tree-done-$src→$tgt"
        ) &
        jobs["$src→$tgt"]=$!
        return 0
    fi

    # Pre-check: verify source directory exists on src node
    if ! ssh $SSH_ARGS "$src" "test -d $SRC_DIR" 2>/dev/null; then
        echo "  [!!] [$src] → [$tgt] $SRC_DIR/ does not exist on $src" >&2
        fail_job "$src→$tgt" "SRC_DIR_MISSING"
        fail_node "$src" "SRC_DIR_MISSING"
        return 1
    fi

    # Run rsync ON the source node, pushing to target via ssh
    ssh $SSH_ARGS "$src" \
        "rsync -av --inplace $SRC_DIR/ ${tgt}:$SRC_DIR/" \
        &> "$log" &

    local pid=$!
    jobs["$src→$tgt"]=$pid
    echo "$pid" > "$STATE_DIR/rsync-tree-pid-$src→$tgt"
    return 0
}

# check_complete src tgt — returns 0 on success, 1 if still running/failed
# Does NOT exit — failures are recorded and the target is returned to waiting queue
check_complete() {
    local src=$1 tgt=$2
    local log="$STATE_DIR/rsync-$src-$tgt.log"
    local pidfile="$STATE_DIR/rsync-tree-pid-$src→$tgt"

    if [[ -n "$DRY_RUN" ]]; then
        if [[ -f "$STATE_DIR/rsync-tree-done-$src→$tgt" ]]; then
            echo "0"
            return 0
        fi
        return 1
    fi

    local checked="$STATE_DIR/rsync-tree-checked-$src→$tgt"

    # Already processed?
    if [[ -f "$checked" ]]; then
        local rsync_exit=$(cat "$checked")
        echo "  [DD] [$src] → [$tgt] already processed, exit=$rsync_exit" >&2
        if [[ $rsync_exit -ne 0 ]]; then
            echo "  [!!] [$src] → [$tgt] rsync failed (exit=$rsync_exit) — returning $tgt to queue, $src back to ready" >&2
            fail_job "$src→$tgt" "RSYNC_EXIT_$rsync_exit"
            unset "jobs[$src→$tgt]" 2>/dev/null
            rm -f "$pidfile"
            waiting=("$tgt" "${waiting[@]}")
            ready["$src"]=1
            return 1
        fi
    else
        if [[ ! -f "$pidfile" ]]; then
            echo "  [??] [$src] → [$tgt] no pidfile yet" >&2
            return 1
        fi

        local pid=$(cat "$pidfile")

        if kill -0 "$pid" 2>/dev/null; then
            echo "  [~~] [$src] → [$tgt] pid $pid still running" >&2
            return 1
        fi

        local rsync_exit=0
        wait "$pid" || rsync_exit=$?
        echo "  [DD] [$src] → [$tgt] pid $pid exited, status=$rsync_exit" >&2

        echo "$rsync_exit" > "$checked"
        rm -f "$pidfile"

        if [[ $rsync_exit -ne 0 ]]; then
            echo "  [!!] [$src] → [$tgt] rsync failed with exit=$rsync_exit — returning $tgt to queue, $src back to ready" >&2
            fail_job "$src→$tgt" "RSYNC_EXIT_$rsync_exit"
            unset "jobs[$src→$tgt]" 2>/dev/null
            rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt" "$STATE_DIR/rsync-tree-checked-$src→$tgt"
            waiting=("$tgt" "${waiting[@]}")
            ready["$src"]=1
            return 1
        fi
    fi

    # Size check
    local src_sz tgt_sz
    src_sz=$(ssh $SSH_ARGS "$src" "du -sb $SRC_DIR" 2>/dev/null | awk '{print $1}')
    if [[ -z "$src_sz" ]]; then
        echo "  [!!] [$src] → [$tgt] cannot get size from $src (SSH failed) — returning $tgt to queue, $src back to ready" >&2
        fail_job "$src→$tgt" "SSH_FAIL_SRC"
        unset "jobs[$src→$tgt]" 2>/dev/null
        rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt"
        waiting=("$tgt" "${waiting[@]}")
        ready["$src"]=1
        return 1
    fi
    tgt_sz=$(ssh $SSH_ARGS "$tgt" "du -sb $SRC_DIR" 2>/dev/null | awk '{print $1}')
    if [[ -z "$tgt_sz" ]]; then
        echo "  [!!] [$src] → [$tgt] cannot get size from $tgt (SSH failed) — returning $tgt to queue, $src back to ready" >&2
        fail_job "$src→$tgt" "SSH_FAIL_TGT"
        unset "jobs[$src→$tgt]" 2>/dev/null
        rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt"
        waiting=("$tgt" "${waiting[@]}")
        ready["$src"]=1
        return 1
    fi

    echo "  [DD] [$src] → [$tgt] size: src=$src_sz tgt=$tgt_sz" >&2

    if [[ "$src_sz" != "$tgt_sz" ]]; then
        echo "  [!!] [$src] → [$tgt] SIZE MISMATCH: src=$src_sz tgt=$tgt_sz — returning $tgt to queue, $src back to ready" >&2
        fail_job "$src→$tgt" "SIZE_MISMATCH_src=${src_sz}_tgt=${tgt_sz}"
        unset "jobs[$src→$tgt]" 2>/dev/null
        rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt"
        waiting=("$tgt" "${waiting[@]}")
        ready["$src"]=1
        return 1
    fi

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
        rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt" \
              "$STATE_DIR/rsync-tree-checked-$src→$tgt" \
              "$STATE_DIR/rsync-tree-done-$src→$tgt"

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

SCRIPT_RUN_ID="$(date +%s)"

# ---- Clean up stale locks/picked files from previous runs ----
rm -f $STATE_DIR/rsync-tree-pid-* $STATE_DIR/rsync-tree-checked-* $STATE_DIR/rsync-tree-picked-* $STATE_DIR/rsync-tree-done-* $STATE_DIR/rsync-tree-wait.lock 2>/dev/null; rmdir $STATE_DIR/rsync-tree-wait.lock 2>/dev/null; true

# ---- Main loop ----
iter=0
while true; do
    iter=$((iter + 1))

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
        sleep 1
        continue
    fi

    if (( n_waiting == 0 )); then
        echo "  (all assigned, waiting for actives...)"
        sleep 1
        continue
    fi

    started=0
    for src in "${!ready[@]}"; do
        is_busy=0
        for key in "${!jobs[@]}"; do
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
            rm -f "$STATE_DIR/rsync-tree-pid-$src→$tgt" \
                  "$STATE_DIR/rsync-tree-checked-$src→$tgt" \
                  "$STATE_DIR/rsync-tree-picked-$SCRIPT_RUN_ID-$tgt"
        else
            started=$((started + 1))
        fi
    done

    if (( started == 0 && n_active > 0 )); then
        sleep 0.5
    elif (( started == 0 )); then
        rm -f $STATE_DIR/rsync-tree-picked-*
        sleep 1
    fi
done

print_summary

echo ""
echo "=============================================="
echo " All ${#ALL_NODES[@]} nodes synced! ($iter iterations)"
echo " Log: $LOGFILE"
echo "=============================================="

echo ""
echo "Verification (sample ~25%):"
for n in "${ALL_NODES[@]}"; do
    [[ $((RANDOM % 4)) -ne 0 ]] && continue
    count=$(ssh $SSH_ARGS "$n" "ls $SRC_DIR 2>/dev/null | wc -l" 2>/dev/null || echo "?")
    size=$(ssh $SSH_ARGS "$n" "du -sb $SRC_DIR 2>/dev/null | awk '{print \$1}'" 2>/dev/null || echo "?")
    printf "  %-12s : %s files, %s bytes\n" "$n" "$count" "$size"
done