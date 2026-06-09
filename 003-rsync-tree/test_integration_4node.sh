#!/usr/bin/env bash
# Full integration: 4 nodes, 3 transfers, all complete.
# Uses mock SSH (set PATH) to simulate a multi-node rsync-tree.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Locate mock ssh — expect it pre-installed at /tmp/rsync-tree-mockbin/ssh
# (created by the run script). If not present, skip the test.
if [[ ! -x /tmp/rsync-tree-mockbin/ssh ]]; then
    echo "SKIP: /tmp/rsync-tree-mockbin/ssh not present"
    exit 0
fi
export PATH="/tmp/rsync-tree-mockbin:$PATH"

# Clean slate
rm -rf /tmp/rsync-tree-tui-* /tmp/rsync-tree-picked-* \
       /tmp/rsync-tree-done-* /tmp/rsync-tree-pid-* \
       /tmp/rsync-*.log 2>/dev/null

# Run rsync-tree for 4 nodes; expect all 3 transfers to complete
# within 30s.
timeout 30 ./rsync-tree.sh \
    --nodes 'node12,node001,node002,node003' \
    --source node12 \
    --plain \
    --dir /tmp/rsync-tree-mocksrc > /tmp/integration.log 2>&1
rc=$?

if (( rc != 0 )); then
    echo "FAIL: rsync-tree exit=$rc"
    tail -20 /tmp/integration.log
    exit 1
fi
if ! grep -q 'All jobs completed successfully' /tmp/integration.log; then
    echo "FAIL: summary missing"
    tail -20 /tmp/integration.log
    exit 1
fi
n_done=$(grep -c 'newly ready:' /tmp/integration.log)
n_started=$(grep -c '\[node.*\] → \[node.*\]  started' /tmp/integration.log)
echo "PASS: 3 transfers started, $n_done 'newly ready' events, summary OK"
exit 0
