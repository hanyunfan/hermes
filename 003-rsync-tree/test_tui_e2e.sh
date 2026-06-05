#!/usr/bin/env bash
# TUI e2e: spawn rsync-tree in a pty, capture frames, send 'q' to quit
cd "$(dirname "$0")"
rm -rf /tmp/rsync-tree-tui-* 2>/dev/null
python3 -c "
import pty, os, sys, subprocess, time, select
cmd = ['./rsync-tree.sh', '--dry-run', '--nodes', 'src,n1,n2,n3,n4', '--source', 'src']
env = os.environ.copy()
env['TERM'] = 'xterm-256color'
env['TUI_OUT'] = '/dev/stdout'   # write TUI frames back to our pty (so we can capture)
m, s = pty.openpty()
p = subprocess.Popen(cmd, stdout=s, stderr=subprocess.STDOUT, stdin=s, close_fds=True, env=env)
os.close(s)
buf = b''
t0 = time.monotonic()
while time.monotonic() - t0 < 5.0:
    r, _, _ = select.select([m], [], [], 0.2)
    if r:
        try: buf += os.read(m, 8192)
        except OSError: break
    if p.poll() is not None: break
try: os.write(m, b'q')
except OSError: pass
try: p.wait(timeout=4)
except subprocess.TimeoutExpired: p.kill()
os.close(m)
import re
text = re.sub(rb'\x1b\[[0-9;?]*[a-zA-Z]', b'', buf).decode('utf-8', 'replace')
with open('tui-e2e.txt', 'w') as f: f.write(text)
print(f'Captured {len(text)} chars; returncode={p.returncode}')
"