#!/usr/bin/env bash
#=============================================================================
# rsync-tree-tui.sh — Optimized ANSI TUI wrapper around rsync-tree.sh
#
# Unlike tui.sh (which is sourced INSIDE rsync-tree.sh and intercepts
# scheduler state), this is an INDEPENDENT process:
#
#   user -> rsync-tree-tui.sh --source X --nodes Y --dir Z ...
#                  |
#                  +-> spawns ./rsync-tree.sh --plain ... in background
#                  |   (whose stdout/stderr is tee'd to a log file)
#                  |
#                  +-> own render loop reads that log file every ~250ms
#                      and redraws an ANSI TUI on the parent terminal
#
# Why wrapper instead of in-process renderer:
#   - Doesn't fork rsync-tree.sh — scheduler logic is untouched
#   - Survives rsync-tree.sh crashes — we still see the log + exit cleanly
#   - Can attach/detach: you can run --plain and tail the log yourself,
#     or wrap it in this TUI without changing scheduler code
#
# Key bindings (footer):
#   q   graceful quit (SIGTERM to scheduler, waits for its cleanup)
#   Q   hard quit (SIGKILL — only if scheduler is unresponsive)
#   r   retry failed pairs (writes a sentinel the scheduler can pick up;
#       currently no-op, see KNOWN-LIMITATIONS below)
#   +   bump concurrency (placeholder — see KNOWN-LIMITATIONS)
#   -   drop concurrency (placeholder)
#
# KNOWN-LIMITATIONS:
#   - + / - / r keys are no-ops in this version. The scheduler
#     (rsync-tree.sh) doesn't yet expose --max-concurrent, --pause,
#     or --retry-failed as runtime-mutable controls. To change
#     concurrency you'd have to add a flag file watcher in the
#     scheduler itself. The TUI shows them in the footer so the
#     operator knows what *would* be possible.
#   - Topology rendering here is approximate. We infer parent→child
#     edges from the "[src] → [tgt]" log lines, but don't have the
#     scheduler's authoritative parent map. The TUI still tells you
#     who's DONE / FAIL / RUN at a glance.
#=============================================================================
set -uo pipefail

# ---- Locate rsync-tree.sh (the scheduler we wrap) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHED="$SCRIPT_DIR/rsync-tree.sh"
if [[ ! -x "$SCHED" ]]; then
    echo "rsync-tree-tui.sh: scheduler not found at $SCHED" >&2
    exit 127
fi

# ---- Defaults ----
TUI_OUT="${TUI_OUT:-/dev/tty}"
LOG_FILE="${RSYNC_TREE_TUI_LOG:-/tmp/rsync-tree-tui-$$.log}"
STATE_DIR="${RSYNC_TREE_STATE_DIR:-$HOME/.rsync-tree-state-tui-$$}"
TICK_MS=${RSYNC_TREE_TUI_TICK_MS:-250}      # 4 fps; tweak via env

# ---- Sanity: ensure TUI_OUT is writable ----
if [[ ! -e "$TUI_OUT" ]] && ! exec 9>"$TUI_OUT" 2>/dev/null; then
    echo "rsync-tree-tui.sh: TUI_OUT=$TUI_OUT is not writable (no TTY?); use --plain" >&2
    exit 1
fi

# ---- Output directory ----
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
mkdir -p "$STATE_DIR" 2>/dev/null || true
: > "$LOG_FILE"

# ---- ANSI helpers (same vocabulary as tui.sh so colors match) ----
ESC=$'\033'; CSI="${ESC}["
tui_reset()        { printf '%s0m'  "$CSI"; }
tui_bold()         { printf '%s1m'  "$CSI"; }
tui_dim()          { printf '%s2m'  "$CSI"; }
tui_rev()          { printf '%s7m'  "$CSI"; }
tui_clear()        { printf '%s2J%sH' "$CSI" "$CSI"; }
tui_home()         { printf '%sH'   "$CSI"; }
tui_hide_cursor()  { printf '%s?25l' "$CSI"; }
tui_show_cursor()  { printf '%s?25h' "$CSI"; }
tui_alt_on()       { printf '%s?1049h' "$CSI"; }
tui_alt_off()      { printf '%s?1049l' "$CSI"; }
tui_clear_to_eos() { printf '%sJ'   "$CSI"; }
tui_goto()         { printf '%s%d;%dH' "$CSI" "$1" "$2"; }
tui_red()          { printf '%s31m' "$CSI"; }
tui_green()        { printf '%s32m' "$CSI"; }
tui_yellow()       { printf '%s33m' "$CSI"; }
tui_blue()         { printf '%s34m' "$CSI"; }
tui_cyan()         { printf '%s36m' "$CSI"; }
tui_grey()         { printf '%s90m' "$CSI"; }

# ---- Terminal size (fall back to 80x24) ----
TUI_COLS=$(tput cols 2>/dev/null || echo 80)
TUI_ROWS=$(tput lines 2>/dev/null || echo 24)
(( TUI_COLS < 80 )) && TUI_COLS=80
(( TUI_ROWS < 24 )) && TUI_ROWS=24

# ---- Schedule the scheduler ----
# All of $@ are passed through, but we FORCE --plain because the
# scheduler's in-process TUI would compete with ours.
#
# Tee so we get both a stream we can tail (the log file) and the
# scheduler's normal plain-mode console output (which goes to a
# tempfile we discard once the run is done — see STOP_PIPE).
STOP_PIPE="$STATE_DIR/stop.pipe"
rm -f "$STOP_PIPE"
mkfifo "$STOP_PIPE"

tui_alt_on  >"$TUI_OUT"
tui_hide_cursor >"$TUI_OUT"
tui_clear >"$TUI_OUT"
tui_home >"$TUI_OUT"

START_TS=$(date +%s)
SCHED_PID=

# Force --plain and add --source-from-stdin flag (we synthesize the
# scheduler's first echo so we have a Source: line even before it
# emits anything). We do NOT force --no-tui or anything the scheduler
# doesn't already accept — if user passes --dry-run etc. it goes through.
# Strip any pre-existing --tui / --plain from user args.
ARGS=()
for a in "$@"; do
    case "$a" in
        --tui)        ;;           # silently drop our embedded tui
        --no-tui)     ;;           # ditto
        --plain)      ;;           # we'll add our own
        *)            ARGS+=("$a");;
    esac
done
ARGS=(--plain "${ARGS[@]}")

# Launch scheduler in background, tee stdout+stderr to LOG_FILE.
# Tee's stdout is the FIFO (so the scheduler sees its normal plain
# output if anything reads from it; nobody does, but the FD has to
# go somewhere).
"$SCHED" "${ARGS[@]}" > >(tee "$LOG_FILE" >/dev/null) 2>&1 &
SCHED_PID=$!
disown 2>/dev/null || true

# ---- Cooperative shutdown flag ----
TUI_STOP_FILE="$STATE_DIR/tui.stop"
rm -f "$TUI_STOP_FILE"

tui_stop() {
    rm -f "$TUI_STOP_FILE"
    if [[ -n "${SCHED_PID:-}" ]] && kill -0 "$SCHED_PID" 2>/dev/null; then
        # Graceful first
        kill -TERM "$SCHED_PID" 2>/dev/null || true
        # Up to 3s for the scheduler's EXIT trap to fire
        for _ in 1 2 3 4 5 6; do
            kill -0 "$SCHED_PID" 2>/dev/null || break
            sleep 0.5
        done
        # Hard kill if still alive
        if kill -0 "$SCHED_PID" 2>/dev/null; then
            kill -KILL "$SCHED_PID" 2>/dev/null || true
        fi
        wait "$SCHED_PID" 2>/dev/null || true
    fi
    tui_show_cursor >"$TUI_OUT" 2>/dev/null
    tui_alt_off     >"$TUI_OUT" 2>/dev/null
    tui_reset       >"$TUI_OUT" 2>/dev/null
    rm -rf "$STATE_DIR" 2>/dev/null
}
trap 'tui_stop' EXIT INT TERM

# ---- Parser: read LOG_FILE -> populate $state_* arrays ----
# We don't try to be perfectly correct; we only need:
#   * which (src,tgt) pairs exist
#   * their status (DONE/FAIL/RUN/WAIT)
#   * current iter / counts
#   * elapsed
#
# Plain-mode scheduler emits these tokens:
#   "[src] → [tgt]  [DRY]"           → rsync starting (dry-run)
#   "[src] → [tgt]  started"
#   "[DD] [src] → [tgt] ..."         → DONE  (rsync log clean)
#   "[!!] [src] → [tgt] ..."         → FAIL
#   "[??] [src] → [tgt] no pidfile"  → meta error
#   "--- iter N: A active, W waiting, R free sources ---"
#   "[MAIN] jobs=N ready=M waiting=K"
#   "[CR]   job: src→tgt pid=XXXX"   → ACTIVE
#   "[CR]   job: src→tgt.hb pid=XXXX"→ heartbeat companion (we ignore)
#   "→ newly ready: src tgt"
#   "→ all jobs finished ..."        → exit
#   "==============================================" "SUMMARY" "All jobs completed"
#   "Failed jobs:"                   → at-least-one-failed banner
#
# Format of $state_pairs (associative): key="src→tgt", value="DONE|FAIL|RUN|WAIT|DRY"
declare -A state_pairs=()
state_iter=0
state_active=0
state_waiting=0
state_ready=0
state_done=0
state_failed=0
state_src=""
state_phase="init"          # init | running | done
state_final_summary=""

reparse_log() {
    # We re-parse the WHOLE log on every tick. With the volumes this
    # script handles (< 1000 log lines typically), that's fine — and
    # avoids any incremental-parse correctness headaches.
    [[ -f "$LOG_FILE" ]] || return 0
    state_pairs=()          # reset; we'll re-derive from log tail
    state_iter=0
    state_active=0
    state_waiting=0
    state_ready=0
    state_done=0
    state_failed=0
    state_phase="running"
    state_final_summary=""

    # Walk log backwards so the LAST status wins (newest event for a
    # pair is authoritative). Bash associative arrays don't have
    # insertion order, so we do this with line-reverse + last-wins.
    #
    # 'tac' from coreutils is universal; fallback to awk if missing.
    local lines_rev
    lines_rev=$(tac "$LOG_FILE" 2>/dev/null || awk '{a[NR]=$0} END {for(i=NR;i>=1;i--) print a[i]}' "$LOG_FILE")

    # First pass: extract (src,tgt) statuses from lines that mention
    # them — last occurrence wins because we read tac'd lines.
    while IFS= read -r line; do
        # Status markers like "  [DD] [src] → [tgt] ..." or
        # "  [!!] [src] → [tgt] ..."  — note leading whitespace
        # allowed (the scheduler indents these with 2 spaces).
        if [[ "$line" =~ ^[[:space:]]*\[([A-Z]+)\][[:space:]]+\[([^\]]+)\][[:space:]]+→[[:space:]]+\[([^\]]+)\] ]]; then
            local tag="${BASH_REMATCH[1]}"
            local s="${BASH_REMATCH[2]}"
            local t="${BASH_REMATCH[3]}"
            local pair_key="$s→$t"
            [[ -n "${state_pairs[$pair_key]+set}" ]] && continue
            case "$tag" in
                DD|OK)        state_pairs[$pair_key]="DONE"  ;;
                !!|ERR)       state_pairs[$pair_key]="FAIL"  ;;
                DRY)          state_pairs[$pair_key]="DRY"   ;;
                *)            state_pairs[$pair_key]="UNKNOWN_$tag" ;;
            esac
        elif [[ "$line" =~ ^[[:space:]]*\[([^\]]+)\][[:space:]]+→[[:space:]]+\[([^\]]+)\][[:space:]]+(started|\[DRY\]) ]]; then
            # "  [src] → [tgt]  started" / "  [src] → [tgt]  [DRY]"
            local s="${BASH_REMATCH[1]}"
            local t="${BASH_REMATCH[2]}"
            local pair_key="$s→$t"
            [[ -n "${state_pairs[$pair_key]+set}" ]] && continue
            state_pairs[$pair_key]="RUN"
        fi
    done <<< "$lines_rev"

    # Second pass: counters (read the LAST iter line, not tac'd, so we
    # pick up the most recent snapshot).
    local last_iter last_main
    last_iter=$(grep -E "^--- iter " "$LOG_FILE" 2>/dev/null | tail -n 1)
    last_main=$(grep -E "^\[MAIN\] jobs=" "$LOG_FILE" 2>/dev/null | tail -n 1)
    if [[ "$last_iter" =~ iter\ ([0-9]+):\ ([0-9]+)\ active,\ ([0-9]+)\ waiting,\ ([0-9]+)\ free ]]; then
        state_iter="${BASH_REMATCH[1]}"
        state_active="${BASH_REMATCH[2]}"
        state_waiting="${BASH_REMATCH[3]}"
        state_ready="${BASH_REMATCH[4]}"
    fi
    if [[ "$last_main" =~ jobs=([0-9]+)\ ready=([0-9]+)\ waiting=([0-9]+) ]]; then
        # prefer [MAIN] line's counts if iter line was missing
        : "${state_active:=${BASH_REMATCH[1]}}"
        : "${state_ready:=${BASH_REMATCH[2]}}"
        : "${state_waiting:=${BASH_REMATCH[3]}}"
    fi

    # Tally done / failed from $state_pairs (DONE, FAIL counts)
    state_done=0
    state_failed=0
    for k in "${!state_pairs[@]}"; do
        case "${state_pairs[$k]}" in
            DONE) ((state_done++)) ;;
            FAIL) ((state_failed++)) ;;
        esac
    done

    # Detect scheduler exit
    if grep -q "^All jobs completed successfully" "$LOG_FILE" 2>/dev/null; then
        state_phase="done"
        state_final_summary="All jobs completed successfully."
    elif grep -qE "^  Failed jobs:" "$LOG_FILE" 2>/dev/null; then
        state_phase="done"
        state_final_summary="Some jobs failed."
    fi

    # Source node (from the header banner)
    if [[ -z "$state_src" ]]; then
        state_src=$(grep -E "^  Source : " "$LOG_FILE" 2>/dev/null | head -n 1 | awk '{print $3}')
        [[ -z "$state_src" ]] && state_src="?"
    fi
}

fmt_elapsed() {
    local s=$1
    printf '%02d:%02d:%02d' $((s/3600)) $(((s%3600)/60)) $((s%60))
}

# ---- Render ----
render() {
    reparse_log
    local elapsed=$(( $(date +%s) - START_TS ))

    # Layout:
    #   row 1                 : header (rev'd)
    #   row 2 .. topology_h+1 : topology tree (left)
    #   row 2 .. bot-2        : jobs table  (right)
    #   row topology_h+2      : events header
    #   row bot-1             : footer
    local body_top=2
    local body_bot=$((TUI_ROWS - 2))
    local topology_h=$(( (body_bot - body_top + 1) * 55 / 100 ))
    [[ $topology_h -lt 6 ]] && topology_h=6
    local events_h=$(( body_bot - body_top + 1 - topology_h - 1 ))
    [[ $events_h -lt 4 ]] && events_h=4
    local left_w=$(( TUI_COLS * 40 / 100 ))
    [[ $left_w -lt 28 ]] && left_w=28
    local right_col=$(( left_w + 3 ))

    # ---- HEADER ----
    tui_home >"$TUI_OUT"
    tui_bold >"$TUI_OUT"; tui_rev >"$TUI_OUT"
    printf ' src=%s iter=%s | %s active / %s done / %s failed / %s waiting | elapsed=%s ' \
        "$state_src" "$state_iter" \
        "$state_active" "$state_done" "$state_failed" "$state_waiting" \
        "$(fmt_elapsed $elapsed)" >"$TUI_OUT"
    # Pad to end of row
    local pad=$(( TUI_COLS - $(printf ' src=%s iter=%s | %s active / %s done / %s failed / %s waiting | elapsed=%s ' \
        "$state_src" "$state_iter" "$state_active" "$state_done" "$state_failed" "$state_waiting" "$(fmt_elapsed $elapsed)" | wc -c) - 1 ))
    (( pad < 0 )) && pad=0
    printf '%*s' "$pad" "" >"$TUI_OUT"
    tui_reset >"$TUI_OUT"

    # ---- TOPOLOGY (left) ----
    # We render a flat list of unique nodes with their status, not a
    # true tree — the plain-mode scheduler doesn't emit parent→child
    # edges in a parseable form. Group by source for readability.
    local row=$body_top
    local max_row=$(( body_top + topology_h - 1 ))
    tui_goto "$row" 1 >"$TUI_OUT"
    tui_dim   >"$TUI_OUT"
    printf '  Topology (src→tgt pairs)' >"$TUI_OUT"
    tui_reset >"$TUI_OUT"
    ((row++))

    # Build sorted view of (src,tgt,status) tuples
    local sorted_pairs
    sorted_pairs=$(for k in "${!state_pairs[@]}"; do
        s="${k%%→*}"
        t="${k##*→}"
        st="${state_pairs[$k]}"
        printf '%s\t%s\t%s\n' "$s" "$t" "$st"
    done | sort)

    while IFS=$'\t' read -r s t st; do
        ((row > max_row)) && break
        tui_goto "$row" 1 >"$TUI_OUT"
        local tag color
        case "$st" in
            DONE) tag="DONE"; color=$(tui_green) ;;
            FAIL) tag="FAIL"; color=$(tui_red)   ;;
            RUN)  tag="RUN "; color=$(tui_cyan)  ;;
            DRY)  tag="DRY "; color=$(tui_yellow);;
            *)    tag="----"; color=$(tui_grey)  ;;
        esac
        printf '  %s%s%s %s → %s' "$(tui_dim)" "$s" "$(tui_reset)" \
            "$color" "$tag" >"$TUI_OUT"
        tui_reset >"$TUI_OUT"
        printf ' %s\n' "$t" >"$TUI_OUT"
        ((row++))
    done <<< "$sorted_pairs"
    # Fill remaining topology rows with blanks
    while ((row <= max_row)); do
        tui_goto "$row" 1 >"$TUI_OUT"
        printf '\033[K' >"$TUI_OUT"
        ((row++))
    done

    # ---- JOBS TABLE (right) ----
    local jr=$body_top
    local jmax=$body_bot
    tui_goto "$jr" "$right_col" >"$TUI_OUT"
    tui_dim >"$TUI_OUT"
    printf '  Live jobs (most recent first)' >"$TUI_OUT"
    tui_reset >"$TUI_OUT"
    ((jr++))

    # Tab-separated, ACTIVE first then DONE then FAIL
    local jobs_view
    jobs_view=$(for k in "${!state_pairs[@]}"; do
        s="${k%%→*}"; t="${k##*→}"; st="${state_pairs[$k]}"
        printf '%s\t%s\t%s\n' "$st" "$s" "$t"
    done | awk -F'\t' '
        $1=="RUN"  {print "ACTIVE\t" $2 "\t" $3}
        $1=="DONE" {print "DONE  \t" $2 "\t" $3}
        $1=="FAIL" {print "FAIL  \t" $2 "\t" $3}
        $1=="DRY"  {print "DRY   \t" $2 "\t" $3}
    ')
    while IFS=$'\t' read -r st s t; do
        ((jr > jmax)) && break
        tui_goto "$jr" "$right_col" >"$TUI_OUT"
        local color
        case "$st" in
            ACTIVE*) color=$(tui_cyan) ;;
            DONE*)   color=$(tui_green);;
            FAIL*)   color=$(tui_red)  ;;
            *)       color=$(tui_yellow);;
        esac
        printf '  %s%s%s %s → %s\n' "$color" "$st" "$(tui_reset)" "$s" "$t" >"$TUI_OUT"
        ((jr++))
    done <<< "$jobs_view"
    while ((jr <= jmax)); do
        tui_goto "$jr" "$right_col" >"$TUI_OUT"
        printf '\033[K' >"$TUI_OUT"
        ((jr++))
    done

    # ---- EVENTS (left, under topology) ----
    local erow=$(( body_top + topology_h + 1 ))
    tui_goto "$erow" 1 >"$TUI_OUT"
    tui_dim >"$TUI_OUT"
    printf '── Recent events ──' >"$TUI_OUT"
    tui_reset >"$TUI_OUT"
    ((erow++))

    # Last 12 lines of the log that look like event markers
    local evts
    evts=$(grep -E "^  [0-9]{2}:[0-9]{2}:[0-9]{2}|^\[!!\]|^\[DD\]|^\[CR\]|^\[PICK\]|^\[MAIN\]|newly ready|all jobs finished|all-fail|all-success" \
        "$LOG_FILE" 2>/dev/null | tail -n "$events_h")
    while IFS= read -r ln; do
        ((erow > body_bot)) && break
        tui_goto "$erow" 1 >"$TUI_OUT"
        # Color event log lines by sentiment
        if [[ "$ln" == *"[!!]"* ]] || [[ "$ln" == *"ERR"* ]]; then
            tui_red >"$TUI_OUT"
        elif [[ "$ln" == *"[DD]"* ]] || [[ "$ln" == *"OK"* ]] || [[ "$ln" == *"newly ready"* ]]; then
            tui_green >"$TUI_OUT"
        elif [[ "$ln" == *"[CR]"* ]] || [[ "$ln" == *"[PICK]"* ]]; then
            tui_dim >"$TUI_OUT"
        fi
        printf '  %s' "$ln" >"$TUI_OUT"
        tui_reset >"$TUI_OUT"
        printf '\033[K\n' >"$TUI_OUT"
        ((erow++))
    done <<< "$evts"
    while ((erow <= body_bot)); do
        tui_goto "$erow" 1 >"$TUI_OUT"
        printf '\033[K\n' >"$TUI_OUT"
        ((erow++))
    done

    # ---- FOOTER (bottom row) ----
    tui_goto $((TUI_ROWS - 1)) 1 >"$TUI_OUT"
    printf '\033[K' >"$TUI_OUT"
    local footer
    if [[ "$state_phase" == "done" ]]; then
        footer=" DONE — $state_final_summary  |  [q] quit  |  log=$LOG_FILE"
    else
        footer=" [q] quit  [+]+1  [-]-1  [r] retry-failed  |  log=$LOG_FILE"
    fi
    tui_bold >"$TUI_OUT"
    printf '%s' "$footer" >"$TUI_OUT"
    tui_reset >"$TUI_OUT"

    tui_clear_to_eos >"$TUI_OUT"
}

# ---- Render loop ----
# Non-blocking key read with -t 0.25 so we hit ~4 fps even when nothing
# happens. On 'q' we set TUI_STOP_FILE and the next tick exits cleanly
# (releasing the alt-screen, sending SIGTERM to the scheduler).
#
# We use `read -rsn1` so the keystroke isn't echoed.
TICK_INT_MS=$(( TICK_MS * 1000 ))   # for python-style hint; bash only takes seconds
key=""
while true; do
    # Bail if scheduler is dead and we've shown at least one final frame
    if ! kill -0 "$SCHED_PID" 2>/dev/null; then
        render
        # Give the user a moment to read the final frame, then exit
        sleep 0.5
        break
    fi
    render
    # Non-blocking key check; -t 0.25 limits tick cadence
    if read -rsn1 -t 0.25 key 2>/dev/null; then
        case "$key" in
            q|Q)
                # Don't break here — let the EXIT trap clean up the
                # alt-screen. Just signal and the loop re-checks
                # kill -0 above.
                rm -f "$TUI_STOP_FILE"      # not used; placeholder
                # Trigger graceful shutdown by sending SIGTERM ourselves.
                # The EXIT trap will run tui_stop which does the same
                # thing, so this is the standard exit path.
                break
                ;;
            +)
                # No-op for now (concurrency not yet runtime-tunable
                # in rsync-tree.sh). Print a one-shot notice so the
                # user knows the key was received.
                tui_goto $((TUI_ROWS - 2)) 1 >"$TUI_OUT"
                printf '\033[K' >"$TUI_OUT"
                tui_yellow >"$TUI_OUT"
                printf '  [+]: concurrency control not yet wired (TODO: add --max-concurrent to rsync-tree.sh)' >"$TUI_OUT"
                tui_reset >"$TUI_OUT"
                ;;
            -)
                tui_goto $((TUI_ROWS - 2)) 1 >"$TUI_OUT"
                printf '\033[K' >"$TUI_OUT"
                tui_yellow >"$TUI_OUT"
                printf '  [-]: concurrency control not yet wired (TODO: add --max-concurrent to rsync-tree.sh)' >"$TUI_OUT"
                tui_reset >"$TUI_OUT"
                ;;
            r)
                tui_goto $((TUI_ROWS - 2)) 1 >"$TUI_OUT"
                printf '\033[K' >"$TUI_OUT"
                tui_yellow >"$TUI_OUT"
                printf '  [r]: retry-failed not yet wired (TODO: scheduler watches $STATE_DIR/rsync-tree-retry)' >"$TUI_OUT"
                tui_reset >"$TUI_OUT"
                ;;
        esac
    fi
done

# Trigger the EXIT trap
exit 0