# rsync-tree

Event-driven parallel rsync tree for `/mnt/data` across node001–node018.

## Problem

~500 GB needs to go from a single source node (e.g. `node012`) to 17 other nodes, over a 100 MB/s link. A naive sequential copy takes ~1.4 hours minimum. We want to saturate each node's eth at 100 MB/s from the start.

## Algorithm: Event-Driven Binary Tree

Each node transitions: **waiting → active → ready (as new source)**.

The main loop constantly checks for completed jobs. As soon as any node finishes receiving data, it immediately starts sending to the next unassigned node — no waiting for a "round" or "wave" to finish.

```
node012 → node001   (T min later node001 is ready)
node012 → node002,  node001 → node003     (2 parallel, T min)
node012 → node004,  node001 → node005,
node002 → node006,  node003 → node007     (4 parallel, T min)
...                                          (8 parallel, T min)
...                                          (all active, T min)
Total: log2(17) × T ≈ 5 × T ≈ 208 min
Each rsync is always at full 100 MB/s — no eth splitting.
```

## Usage

```bash
# Dry run (simulates, doesn't actually sync)
./rsync-tree.sh --dry-run

# Real run — default: source=node12, pattern='node[01-18]'
./rsync-tree.sh

# Specify source and node pattern
./rsync-tree.sh --source node12 --nodes 'node0[01-18]'

# Custom directory
./rsync-tree.sh --dir /data/shared

# Pre-flight check: verify SSH + $SRC_DIR on every node before starting
./rsync-tree.sh --diagnose --nodes 'node[01-18]'
# → ✗ node07  SSH unreachable (BatchMode refused, no key, or wrong host)
# → ✓ node12  SSH ok, /mnt/data/ exists, 14 files, 482G
# Exits 2 if any node fails, with a per-node breakdown.

# Plain mode (skip TUI; logs to stdout line-by-line, useful for cron)
./rsync-tree.sh --plain --dry-run --nodes 'node[01-18]'
```

### Node Pattern Examples

```bash
# node001 .. node018 (zero-padded to 2 digits — "01" has leading zero)
--nodes 'node[01-18]'

# node001 .. node018 (zero-padded to 3 digits — "001" has leading zeros)
--nodes 'node0[01-18]'

# compute0 .. compute7
--nodes 'compute[0-7]'

# rack01 .. rack48 (2-digit padding from "01")
--nodes 'rack[01-48]'

# n1 .. n8 (plain numbers, no zero-padding)
--nodes 'n[1..8]'

# Explicit comma-separated list
--nodes 'server1,server2,server3,server4'

# Single node (source must be in the list)
--nodes 'myhost'
```

## Requirements

- SSH passwordless access to all target nodes
- `rsync` installed on source and all targets
- `sudo rsync` on targets (for preserving permissions) — or remove `--rsync-path` flag from the script
- Sufficient disk space on all targets
- A real TTY for the default TUI mode; use `--plain` for cron / non-interactive runs

## TUI Mode (default)

By default `rsync-tree.sh` renders a live ANSI-based TUI on the terminal using
the alternate screen buffer. The renderer is a separate `tui.sh` script
sourced by the main script — no Python or other dependencies required.

```
┌──────────────────────────────────────────────────────────────────────┐
│ [DRY-RUN] src=node12 nodes=18 | iter=42 | 8 active / 6 done / ...   │  ← header
├────────────── Topology ──────────────┬────────── Jobs ──────────────┤
│ Source: node12                       │ RUN  node12→node03  41% 78MB/s│
│ ├─→ RUN  node03                      │ RUN  node12→node07  79% 102MB │
│ │   ├─→ RUN  node02                  │ RUN  node01→node02  33% 45MB  │
│ │   └─→ DONE node09                  │ ...                             │
│ ├─→ RUN  node07                      │                                  │
│ │   ├─→ RUN  node05                  ├─────────── Events ──────────────┤
│ │   └─→ DONE node10                  │ 12:34:01 OK    node01 done      │
│ └─→ ...                             │ 12:33:55 ERR   node14 exit 12   │
├──────────────────────────────────────┴──────────────────────────────────┤
│ [q] quit  [p] pause  [+]+1  [-]-1  [r] retry   elapsed: 01:23:45     │
└──────────────────────────────────────────────────────────────────────┘
```

- **Header** — overall run state: source, total nodes, iteration count,
  active/done/failed counts, elapsed time.
- **Topology** — live binary tree showing fan-out from the source. Each node
  is colored by its current job status (RUN/DONE/FAIL/WAIT).
- **Jobs** — per-rsync progress percent, throughput, status. Sorted
  active-first, then waiting, done, failed.
- **Events** — last 6 log lines with timestamps and severity coloring.
- **Footer** — key hints and elapsed time.

The TUI auto-detects when stdout is not a TTY (e.g. piped to a file) and
falls back to plain mode. The main loop's chatter is redirected to the
log file (`/tmp/rsync-tree.log`) so the screen is dedicated to the TUI.

### Plain mode (`--plain`)

For cron jobs, non-TTY SSH sessions, or piping to a log file, use `--plain`.
In this mode the main script writes one line of progress per iteration
directly to stdout and the TUI renderer is not started.

```bash
# Plain mode (line-based progress, no TUI)
./rsync-tree.sh --plain --dry-run --nodes 'node[01-18]' 2>&1 | tee run.log
```

### Standalone TUI wrapper (`rsync-tree-tui.sh`)

If you want the prettiest ANSI display but **without** modifying the
scheduler, use the standalone wrapper. It spawns `rsync-tree.sh --plain`
in the background and renders its log output into a live TUI on your
terminal — no in-process state sharing required.

```bash
./rsync-tree-tui.sh --source src --nodes 'src,n1,n2,n3' --dir /mnt/data
```

What it gives you over plain mode:

- Live header with `iter=N`, `X active / Y done / Z failed / W waiting`, elapsed
- Per-pair status (RUN / DONE / FAIL) on the topology panel
- Live-jobs panel on the right
- Color-coded recent-events tail at the bottom

Key bindings:

- `q` — graceful quit (SIGTERM to scheduler, waits for its cleanup)
- `Q` — hard quit (SIGKILL — only if scheduler is unresponsive)
- `+` / `-` — placeholder for runtime concurrency control (TODO)
- `r` — placeholder for retry-failed control (TODO)

Compared to the in-process TUI (`rsync-tree.sh` default), this wrapper
has one limitation: the topology tree is a flat list of (src,tgt) pairs
inferred from log lines, not the authoritative parent→child map that
`tui.sh` (sourced in-process) has. The flat view still shows every
pair and its status correctly.

### Stuck on "starting"? Run `--diagnose`

If the scheduler prints one `… starting` event and then nothing happens —
no `[OK] done`, no `[ERR]` — that's a stuck ssh/rsync, not a TUI bug.
Run `--diagnose` first to localize the failure to a specific node:

```bash
./rsync-tree.sh --diagnose --nodes 'node[01-18]'
```

It checks every node for SSH reachability (BatchMode), `$SRC_DIR`
existence, and a successful `du -sb` size query. Exits 2 with a per-node
breakdown if anything is wrong.

If `--diagnose` says all nodes are healthy but a real run still hangs,
look at the heartbeat log lines in the TUI events panel — they fire
every 3 seconds while a job is `ACTIVE` and include the last line of
the rsync log, so you can tell whether the ssh session is hung, the
TCP socket got dropped, or rsync is just slow on a huge file.

## Architecture (v2.0)

- `rsync-tree.sh` — main scheduler. v1 algorithm preserved; v2 adds:
  - `--plain` flag to disable the TUI
  - `tui_log_job` / `tui_log_event` / `tui_set_header` hooks that
    write state files (`jobs.tsv`, `events.log`, `header`) consumed
    by the TUI renderer
  - `finalize` EXIT trap that stops the TUI, restores stdout from
    the log-file redirect, prints the final summary, then cleans up
  - `update_job_progress` — every main-loop iter, parses the latest
    rsync `--info=progress2` line from each active job's log and
    pushes the (pct, speed) into the TUI row. Skips the rewrite when
    the parsed values haven't changed, so it's cheap. Without this
    ACTIVE jobs would stay at 0% / 0.0 MB/s for the whole run.
  - `check_complete` rewrites the row to `DONE 100%` (or `FAIL`) on
    process exit, instead of leaving the row stuck on `ACTIVE`.
- `tui.sh` — pure-bash ANSI TUI renderer. Sourced by `rsync-tree.sh`.
  Reads state from `/tmp/rsync-tree-tui-$$/` and writes frames to
  `/dev/tty` (or `$TUI_OUT` if set). Implements:
  - `tui_start` — enters alt-screen, hides cursor, spawns render loop
  - `tui_render` — full-frame redraw (header + topology + jobs + events + footer)
  - `tui_stop` — kills render loop, restores cursor and main screen

## How It Works

1. Source node is marked **ready**; all others are **waiting**
2. Each iteration: pair every free ready source with one waiting node and start rsync
3. Each completed node moves from **active** → **ready**
4. Repeat until waiting list is empty and all active jobs finish
5. Result: parallelism grows organically as nodes complete — never a round boundary

## Timing

With 100 MB/s link and 500 GB to distribute:

| Scenario | Total Time |
|----------|-----------|
| Sequential (1→1→1) | ~667 min |
| Naive 8-way flood (12.5 MB/s each) | ~83 min before wave 2 |
| **Event-driven binary tree** | **~208 min** |
