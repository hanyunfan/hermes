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
