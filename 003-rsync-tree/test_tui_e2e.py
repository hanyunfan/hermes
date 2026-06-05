#!/usr/bin/env python3
"""End-to-end TUI test: run --tui for 5 seconds, capture frame from Console.record()."""
import importlib.util
import sys
import os
import subprocess

spec = importlib.util.spec_from_file_location("rsync_tree_mod", "rsync-tree.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["rsync_tree_mod"] = mod
spec.loader.exec_module(mod)

# Spawn a real subprocess running --tui for a few seconds with a fake node list,
# with stdout captured to a pty so Rich sees a TTY. Skip if pty module missing.
import pty
import select
import time

cmd = [sys.executable, "rsync-tree.py", "--tui", "--dry-run",
       "--nodes", "src,n1,n2,n3,n4,n5", "--source", "src",
       "--max-retries", "0"]

# Open a pty
master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(cmd, stdout=slave_fd, stderr=subprocess.STDOUT,
                        stdin=slave_fd, close_fds=True)
os.close(slave_fd)

# Read for ~5s, save output
output = b""
start = time.monotonic()
while time.monotonic() - start < 5.5:
    r, _, _ = select.select([master_fd], [], [], 0.2)
    if r:
        try:
            chunk = os.read(master_fd, 4096)
            if chunk:
                output += chunk
        except OSError:
            break
    if proc.poll() is not None:
        break

# Send 'q' to quit gracefully, then wait
try:
    os.write(master_fd, b"q")
except OSError:
    pass
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()

os.close(master_fd)

# Strip ANSI for readability
import re
ansi = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]")
clean = ansi.sub(b"", output).decode("utf-8", errors="replace")

out_path = os.path.join(os.path.dirname(__file__), "tui-e2e.txt")
with open(out_path, "w") as f:
    f.write(clean)
print(f"Captured {len(clean)} chars to {out_path}")
print(f"Return code: {proc.returncode}")
