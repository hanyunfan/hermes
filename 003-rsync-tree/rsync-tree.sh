#!/bin/bash
#=============================================================================
# rsync-tree.sh — Thin wrapper around rsync-tree.py
#
# Preserves the original CLI surface (--source, --nodes, --dir, --dry-run)
# while routing execution to the Python implementation with Rich TUI support.
#
# New flag: --tui    (renders live TUI; requires `pip install rich`)
#
# Usage examples unchanged from the old all-bash version:
#   ./rsync-tree.sh --dry-run
#   ./rsync-tree.sh --nodes 'node[01-18]'
#   ./rsync-tree.sh --source node12 --nodes 'node0[01-18]'
#   ./rsync-tree.sh --tui --dry-run --nodes 'node[01-18]'
#=============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/rsync-tree.py"

# Pick the best Python available
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: python3 not found" >&2
    exit 1
fi

# Quick sanity: rich importable?
HAS_RICH=0
if "$PY" -c 'import rich' >/dev/null 2>&1; then
    HAS_RICH=1
fi

# If --tui requested and rich missing, install it (best-effort)
ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--tui" ]] && [[ $HAS_RICH -eq 0 ]]; then
        echo "[rsync-tree.sh] rich not installed; attempting pip install rich..." >&2
        "$PY" -m pip install --user rich >/dev/null 2>&1 || true
        if "$PY" -c 'import rich' >/dev/null 2>&1; then
            HAS_RICH=1
        else
            echo "[rsync-tree.sh] WARNING: pip install failed, falling back to plain mode" >&2
            continue   # drop --tui arg
        fi
    fi
    ARGS+=("$arg")
done

exec "$PY" "$PY_SCRIPT" "${ARGS[@]}"
