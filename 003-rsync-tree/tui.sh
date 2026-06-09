#!/usr/bin/env bash
#=============================================================================
# tui.sh — ANSI-based TUI renderer for rsync-tree
#
# Reads state from $STATE_DIR (set by main rsync-tree.sh):
#   $STATE_DIR/jobs.tsv    — "src\ttgt\tstatus\tpct\tspeed\tretries"
#   $STATE_DIR/events.log  — append-only event log
#   $STATE_DIR/header      — single-line header state
#
# Sourced by rsync-tree.sh. Defines tui_start / tui_stop / tui_log_job /
# tui_log_event / tui_set_header. Designed to be optional — if tui_start
# returns non-zero (no TTY), the main script falls back to plain mode.
#=============================================================================

set -u

# --- Terminal capability --------------------------------------------------
# We only fail-soft in tui_start (which needs a real TTY). The renderer
# functions are exported unconditionally so main rsync-tree.sh can populate
# state and dump frames to a file.
TUI_COLS=$(tput cols 2>/dev/null || echo 80)
TUI_ROWS=$(tput lines 2>/dev/null || echo 24)
[[ $TUI_COLS -lt 60 ]] && TUI_COLS=80
[[ $TUI_ROWS -lt 20 ]] && TUI_ROWS=24

# Where TUI output goes. By default /dev/tty so it works even if the parent's
# stdout has been redirected to a log file. Set TUI_OUT=:stdout to override
# (useful for tests).
TUI_OUT="${TUI_OUT:-/dev/tty}"

STATE_DIR="${STATE_DIR:-/tmp/rsync-tree-tui-$$}"
JOBS_FILE="$STATE_DIR/jobs.tsv"
EVENTS_FILE="$STATE_DIR/events.log"
HEADER_FILE="$STATE_DIR/header"

# --- ANSI helpers ---------------------------------------------------------
ESC=$'\033'
CSI="${ESC}["

tui_reset()        { printf "%s0m" "$CSI"; }
tui_bold()         { printf "%s1m" "$CSI"; }
tui_dim()          { printf "%s2m" "$CSI"; }
tui_rev()          { printf "%s7m" "$CSI"; }
tui_clear()        { printf "%s2J%sH" "$CSI" "$CSI"; }
tui_home()         { printf "%sH" "$CSI"; }
tui_goto()         { printf "%s%d;%dH" "$CSI" "$1" "$2"; }
tui_hide_cursor()  { printf "%s?25l" "$CSI"; }
tui_show_cursor()  { printf "%s?25h" "$CSI"; }
tui_alt_on()       { printf "%s?1049h" "$CSI"; }
tui_alt_off()      { printf "%s?1049l" "$CSI"; }
tui_clear_to_eos() { printf "%sJ" "$CSI"; }
tui_red()          { printf "%s31m" "$CSI"; }
tui_green()        { printf "%s32m" "$CSI"; }
tui_yellow()       { printf "%s33m" "$CSI"; }
tui_blue()         { printf "%s34m" "$CSI"; }
tui_cyan()         { printf "%s36m" "$CSI"; }
tui_grey()         { printf "%s90m" "$CSI"; }

# --- Topology -------------------------------------------------------------
# Walks the tree based on parent->child edges in jobs.tsv. Pure bash + awk.
# For each child prints: <prefix><connector><STATUS> <node> [pct%]

tui_children_of() {
    local parent=$1
    [[ -f "$JOBS_FILE" ]] || return 0
    awk -F'\t' -v p="$parent" '$1==p && $2!="" {print $2}' "$JOBS_FILE" 2>/dev/null
}

tui_get_status() {
    local node=$1
    [[ -f "$JOBS_FILE" ]] || { echo ""; return; }
    awk -F'\t' -v n="$node" '$2==n {print $3; exit}' "$JOBS_FILE" 2>/dev/null
}

tui_get_pct() {
    local node=$1
    [[ -f "$JOBS_FILE" ]] || { echo "0"; return; }
    awk -F'\t' -v n="$node" '$2==n {print $4; exit}' "$JOBS_FILE" 2>/dev/null
}

tui_print_node() {
    local node=$1 connector=$2 prefix=$3
    local status pct
    status=$(tui_get_status "$node")
    pct=$(tui_get_pct "$node")
    [[ -z "$status" ]] && status="WAIT"
    case "$status" in
        DONE)   tui_green;  status="DONE " ;;
        FAIL*)  tui_red;    status="FAIL " ;;
        ACTIVE) tui_cyan;   status="RUN  " ;;
        *)      tui_yellow; status="WAIT " ;;
    esac
    printf "%s%s" "$prefix" "$connector"
    printf "%s" "$status"
    tui_reset
    printf " %s" "$node"
    if [[ "$status" == "RUN  " ]] && [[ "${pct:-0}" != "0" ]]; then
        printf "  %s%.0f%%%s" "$(tui_dim)" "$pct" "$(tui_reset)"
    fi
    printf "\n"
}

tui_walk() {
    local node=$1 prefix=$2 is_last=$3
    local children total n=0 child connector new_prefix
    children=$(tui_children_of "$node")
    [[ -z "$children" ]] && return 0
    total=$(echo "$children" | wc -l)
    new_prefix="${prefix}│   "
    [[ $is_last -eq 1 ]] && new_prefix="${prefix}    "
    for child in $children; do
        ((n++))
        connector="├─→ "
        [[ $n -eq $total ]] && connector="└─→ "
        tui_print_node_at "$child" "$connector" "$new_prefix" "$((n == total ? 1 : 0))"
        tui_walk "$child" "$new_prefix" "$((n == total ? 1 : 0))"
    done
}

tui_render_topology() {
    local width=$1
    local src="${SOURCE_NODE:-source}"
    # TUI_LINE: which absolute row to print on next (set by tui_render)
    tui_dim
    tui_goto "${TUI_LINE}" 1
    printf "  Source: %s" "$src"
    tui_reset
    printf "\n"
    TUI_LINE=$((TUI_LINE + 1))
    local children total n=0 child connector
    children=$(tui_children_of "$src")
    [[ -z "$children" ]] && return 0
    total=$(echo "$children" | wc -l)
    for child in $children; do
        ((n++))
        connector="├─→ "
        [[ $n -eq $total ]] && connector="└─→ "
        tui_print_node_at "$child" "$connector" "  " "$((n == total ? 1 : 0))"
        tui_walk "$child" "  " "$((n == total ? 1 : 0))"
    done
}

# Like tui_print_node but uses TUI_LINE to position each line absolutely
tui_print_node_at() {
    local node=$1 connector=$2 prefix=$3 is_last=$4
    local status pct
    status=$(tui_get_status "$node")
    pct=$(tui_get_pct "$node")
    [[ -z "$status" ]] && status="WAIT"
    tui_goto "${TUI_LINE}" 1
    case "$status" in
        DONE)   tui_green;  status="DONE " ;;
        FAIL*)  tui_red;    status="FAIL " ;;
        ACTIVE) tui_cyan;   status="RUN  " ;;
        *)      tui_yellow; status="WAIT " ;;
    esac
    printf "%s%s" "$prefix" "$connector"
    printf "%s" "$status"
    tui_reset
    printf " %s" "$node"
    if [[ "$status" == "RUN  " ]] && [[ "${pct:-0}" != "0" ]]; then
        printf "  %s%.0f%%%s" "$(tui_dim)" "$pct" "$(tui_reset)"
    fi
    printf "\n"
    TUI_LINE=$((TUI_LINE + 1))
}

# --- Jobs table -----------------------------------------------------------
# $1 = column, $2 = starting row, $3 = height
tui_render_jobs() {
    local col=$1 start_row=$2 height=$3
    local -i row=$start_row
    local -i max_row=$((start_row + height - 1))
    [[ -f "$JOBS_FILE" ]] || {
        [[ $row -le $max_row ]] && { tui_goto $row $col; printf "  %s(no jobs)%s" "$(tui_dim)" "$(tui_reset)"; }
        return
    }
    # Read all jobs into a here-string, then iterate in the *current* shell
    # (avoiding subshell `while read | pipe` which loses row updates).
    local jobs_text
    jobs_text=$(
        awk -F'\t' '$3=="ACTIVE"' "$JOBS_FILE" 2>/dev/null
        awk -F'\t' '$3=="WAIT"'   "$JOBS_FILE" 2>/dev/null
        awk -F'\t' '$3=="DONE"'   "$JOBS_FILE" 2>/dev/null
        awk -F'\t' '$3 ~ /^FAIL/' "$JOBS_FILE" 2>/dev/null
    )
    jobs_text=$(echo "$jobs_text" | head -n "$height")
    while IFS=$'\t' read -r src tgt status pct speed retries; do
        [[ -z "$src" ]] && continue
        [[ $row -gt $max_row ]] && return
        local tag color
        case "$status" in
            DONE)   tag="DONE"; color=$(tui_green) ;;
            FAIL*)  tag="FAIL"; color=$(tui_red) ;;
            ACTIVE) tag="RUN "; color=$(tui_cyan) ;;
            *)      tag="WAIT"; color=$(tui_yellow) ;;
        esac
        # Right-column jobs table — intentionally tagless. The status
        # (RUN/DONE/FAIL) and pct are already shown in the topology
        # tree on the left, so duplicating them here is noise. Keep
        # the table for live progress speed and to surface jobs that
        # don't appear in the topology (e.g. retries of failed pairs).
        tui_goto $row $col
        printf "  %s%s→%s %s%5.1f%%%s %s%6.1f MB/s%s\n" \
            "$(tui_dim)" "$src" "$tgt" \
            "$(tui_bold)$(tui_cyan)" "${pct:-0}" "$(tui_reset)" \
            "$(tui_green)" "${speed:-0}" "$(tui_reset)"
        row=$((row + 1))
    done <<< "$jobs_text"
}

# --- Events log -----------------------------------------------------------
# $1 = column, $2 = starting row, $3 = max lines
tui_render_events() {
    local col=$1 start_row=$2 n=$3
    local -i row=$start_row
    local -i max_row=$((start_row + n - 1))
    [[ -f "$EVENTS_FILE" ]] || {
        [[ $row -le $max_row ]] && { tui_goto $row $col; printf "  %s(no events)%s" "$(tui_dim)" "$(tui_reset)"; }
        return
    }
    local lines
    lines=$(tail -n "$n" "$EVENTS_FILE" 2>/dev/null)
    if [[ -z "$lines" ]]; then
        [[ $row -le $max_row ]] && { tui_goto $row $col; printf "  %s(no events yet)%s" "$(tui_dim)" "$(tui_reset)"; }
        return
    fi
    while IFS= read -r line; do
        [[ $row -gt $max_row ]] && return
        tui_goto $row $col
        printf "  %s\n" "$line"
        row=$((row + 1))
    done <<< "$lines"
}

# --- Header / footer ------------------------------------------------------
tui_render_header() {
    local line=""
    [[ -f "$HEADER_FILE" ]] && line=$(cat "$HEADER_FILE" 2>/dev/null)
    [[ -z "$line" ]] && line="(waiting for scheduler...)"
    printf "%s%s %s %s\n" "$(tui_bold)$(tui_rev)" "$line" "$(tui_reset)"
}

tui_render_footer() {
    local elapsed="$1"
    printf "%s[q]%s quit  %s[p]%s pause  %s[+]%s+1  %s[-]%s-1  %s[r]%s retry  elapsed: %s\n" \
        "$(tui_bold)$(tui_cyan)" "$(tui_reset)" \
        "$(tui_bold)$(tui_cyan)" "$(tui_reset)" \
        "$(tui_bold)$(tui_cyan)" "$(tui_reset)" \
        "$(tui_bold)$(tui_cyan)" "$(tui_reset)" \
        "$(tui_bold)$(tui_cyan)" "$(tui_reset)" \
        "$elapsed"
}

# --- Main render ----------------------------------------------------------
tui_render() {
    local body_top=2
    local body_bot=$((TUI_ROWS - 2))
    local left_w=$((TUI_COLS * 35 / 100))
    [[ $left_w -lt 24 ]] && left_w=24
    local right_col=$((left_w + 3))

    tui_home
    tui_render_header

    local topology_h=$(( (body_bot - body_top + 1) * 55 / 100 ))
    local events_h=$((body_bot - body_top + 1 - topology_h - 1))
    [[ $topology_h -lt 3 ]] && topology_h=3
    [[ $events_h -lt 2 ]] && events_h=2

    # Topology on left (rows body_top..body_top+topology_h-1)
    tui_render_topology_block $body_top $topology_h

    # Jobs on right (rows body_top..body_bot)
    tui_render_jobs $right_col $body_top $((body_bot - body_top + 1))

    # Events header
    tui_goto $((body_top + topology_h + 1)) 1
    tui_dim
    printf "── Events ──"
    tui_reset
    # Events content
    tui_render_events 1 $((body_top + topology_h + 2)) $events_h

    # Footer
    local elapsed="00:00:00"
    [[ -f "$HEADER_FILE" ]] && elapsed=$(awk -F'|' '{for(i=1;i<=NF;i++) if($i ~ /elapsed=/) print substr($i, 10)}' "$HEADER_FILE" 2>/dev/null)
    [[ -z "$elapsed" ]] && elapsed="00:00:00"

    tui_goto $((TUI_ROWS - 1)) 1
    tui_render_footer "$elapsed"

    tui_clear_to_eos
}

# Topology printer: walks tree and emits at explicit rows
# $1 = start_row, $2 = max_height
tui_render_topology_block() {
    local start_row=$1 max_h=$2
    local -i row=$start_row
    local -i max_row=$((start_row + max_h - 1))
    local src="${SOURCE_NODE:-source}"
    [[ $row -gt $max_row ]] && return
    tui_goto $row 1
    tui_dim
    printf "  Source: %s" "$src"
    tui_reset
    printf "\n"
    row=$((row + 1))
    [[ $row -gt $max_row ]] && return
    local children total n=0 child connector
    children=$(tui_children_of "$src")
    [[ -z "$children" ]] && return
    total=$(echo "$children" | wc -l)
    for child in $children; do
        [[ $row -gt $max_row ]] && return
        ((n++))
        connector="├─→ "
        [[ $n -eq $total ]] && connector="└─→ "
        tui_print_node_at_row "$child" "$connector" "  " "$((n == total ? 1 : 0))" row max_row
        tui_walk_at "$child" "  " "$((n == total ? 1 : 0))" row max_row
    done
}

# Print a single tree line at $row, then increment the caller's row variable
# $1 node, $2 connector, $3 prefix, $4 is_last, $5 row_var, $6 max_row
tui_print_node_at_row() {
    local node=$1 connector=$2 prefix=$3 is_last=$4 row_var=$5 maxr=$6
    local status pct
    status=$(tui_get_status "$node")
    pct=$(tui_get_pct "$node")
    [[ -z "$status" ]] && status="WAIT"
    [[ $row -gt $maxr ]] && return
    tui_goto $row 1
    case "$status" in
        DONE)   tui_green;  status="DONE " ;;
        FAIL*)  tui_red;    status="FAIL " ;;
        ACTIVE) tui_cyan;   status="RUN  " ;;
        *)      tui_yellow; status="WAIT " ;;
    esac
    printf "%s%s" "$prefix" "$connector"
    printf "%s" "$status"
    tui_reset
    printf " %s" "$node"
    if [[ "$status" == "RUN  " ]] && [[ "${pct:-0}" != "0" ]]; then
        printf "  %s%.0f%%%s" "$(tui_dim)" "$pct" "$(tui_reset)"
    fi
    printf "\n"
    row=$((row + 1))
    printf -v "$row_var" "%d" "$row"
}

tui_walk_at() {
    local node=$1 prefix=$2 is_last=$3 row_var=$4 maxr=$5
    local children total n=0 child connector new_prefix
    children=$(tui_children_of "$node")
    [[ -z "$children" ]] && return
    total=$(echo "$children" | wc -l)
    new_prefix="${prefix}│   "
    [[ $is_last -eq 1 ]] && new_prefix="${prefix}    "
    for child in $children; do
        [[ $row -gt $maxr ]] && return
        ((n++))
        connector="├─→ "
        [[ $n -eq $total ]] && connector="└─→ "
        tui_print_node_at_row "$child" "$connector" "$new_prefix" "$((n == total ? 1 : 0))" "$row_var" "$maxr"
        tui_walk_at "$child" "$new_prefix" "$((n == total ? 1 : 0))" "$row_var" "$maxr"
    done
}

# --- Lifecycle ------------------------------------------------------------
TUI_PID=""

tui_start() {
    # If the user wants TUI_OUT != :stdout (e.g. they set TUI_OUT=/dev/tty),
    # we need a TTY. If TUI_OUT is :stdout (the test default) we still need
    # stdout to be a TTY for the alt-screen codes to make sense.
    if [[ ! -t 1 ]] && [[ "$TUI_OUT" == ":stdout" || "$TUI_OUT" == "/dev/stdout" ]]; then
        echo "tui: stdout is not a TTY (TERM=${TERM:-unset}); use --plain" >&2
        return 1
    fi
    if [[ "$TUI_OUT" == "/dev/tty" ]] && [[ ! -r /dev/tty ]]; then
        echo "tui: cannot open /dev/tty; use --plain" >&2
        return 1
    fi
    mkdir -p "$STATE_DIR"
    : > "$JOBS_FILE"
    : > "$EVENTS_FILE"
    : > "$HEADER_FILE"

    # Initialize terminal: alt screen + hide cursor (writes to TUI_OUT)
    printf '%s?1049h' "$CSI" > "$TUI_OUT"
    printf '%s?25l'  "$CSI" > "$TUI_OUT"
    printf '%s2J%sH' "$CSI" "$CSI" > "$TUI_OUT"

    TUI_ACTIVE=1
    # Stash the parent shell's PID so the renderer (a subshell) can
    # signal the main loop with SIGUSR1 when 'q' is pressed.
    TUI_PARENT_PID=$$
    (
        # Redirect the render loop's stdout to TUI_OUT so it survives
        # even if the parent script later redirects its own stdout to a log.
        exec >"$TUI_OUT" 2>"$TUI_OUT"
        # Stash OUR pid (the renderer) so the main script can skip
        # reading stdin (we own it from here on in TUI mode).
        # Read stdin in the same subshell as the renderer — the main
        # script's read is in its main loop, but on slow main-iter
        # cycles the user can press q and have it sit in the kernel
        # buffer until the next iter. Having the renderer also watch
        # stdin (with a short timeout so it doesn't block tui_render)
        # gives faster, more reliable q detection.
        while true; do
            tui_render
            # Non-blocking key check: bash 5.x needs -t 0.1, not -t 0
            local_key=""
            if read -rsn1 -t 0.1 local_key 2>/dev/null; then
                if [[ "$local_key" == "q" || "$local_key" == "Q" ]]; then
                    EXIT_REQUESTED=1
                    # Tell main script to wake up. If we just set the
                    # flag it may not see it for up to 1s (main loop
                    # cadence); SIGUSR1 wakes it immediately.
                    kill -USR1 "$TUI_PARENT_PID" 2>/dev/null || true
                fi
            fi
        done
    ) &
    TUI_PID=$!
    return 0
}

tui_stop() {
    if [[ -n "$TUI_PID" ]]; then
        kill "$TUI_PID" 2>/dev/null
        wait "$TUI_PID" 2>/dev/null
    fi
    printf '%s?25h' "$CSI" > "$TUI_OUT"
    printf '%s?1049l' "$CSI" > "$TUI_OUT"
    printf '%s0m' "$CSI" > "$TUI_OUT"
}

trap 'tui_stop' EXIT INT TERM

# --- Helpers used by the main rsync-tree.sh scheduler --------------------
# These three functions let the main script write TUI state without caring
# whether the TUI is actually running.

# tui_log_job src tgt status pct speed retries  — replace/insert job row
tui_log_job() {
    local src=$1 tgt=$2 status=$3 pct=${4:-0} speed=${5:-0} retries=${6:-0}
    [[ -z "${TUI_ACTIVE:-}" ]] && return 0
    local key="${src}→${tgt}"
    # Use a simple TSV file with key field, replaced via awk to avoid races
    local tmp="${JOBS_FILE}.tmp.$$"
    # Drop any existing row whose src AND tgt both match. We compare $1 and
    # $2 separately because the key "src→tgt" itself is not a field — the
    # arrow is just an internal sentinel.
    awk -F'\t' -v s="$src" -v t="$tgt" \
        '!($1==s && $2==t) {print}' "$JOBS_FILE" 2>/dev/null > "$tmp" || true
    printf '%s\t%s\t%s\t%g\t%g\t%d\n' \
        "$src" "$tgt" "$status" "$pct" "$speed" "$retries" >> "$tmp"
    mv "$tmp" "$JOBS_FILE"
}

# tui_log_job_remove src tgt  — remove a job row
tui_log_job_remove() {
    [[ -z "${TUI_ACTIVE:-}" ]] && return 0
    local tmp="${JOBS_FILE}.tmp.$$"
    awk -F'\t' -v s="$1" -v t="$2" \
        '!($1==s && $2==t) {print}' "$JOBS_FILE" 2>/dev/null > "$tmp" || true
    mv "$tmp" "$JOBS_FILE"
}

# tui_log_event level msg  — append a timestamped line to events.log
tui_log_event() {
    local level=$1 msg=$2
    [[ -z "${TUI_ACTIVE:-}" ]] && return 0
    local ts
    ts=$(date '+%H:%M:%S')
    printf '%s %-5s %s\n' "$ts" "$level" "$msg" >> "$EVENTS_FILE"
}

# tui_set_header "line"  — overwrite the single-line header
tui_set_header() {
    [[ -z "${TUI_ACTIVE:-}" ]] && return 0
    printf '%s\n' "$*" > "$HEADER_FILE"
}
