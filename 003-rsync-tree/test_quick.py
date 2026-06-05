#!/usr/bin/env python3
"""Quick smoke tests for rsync-tree.py without dataclass/sys.modules quirks."""
import subprocess
import sys
import os

SCRIPT = os.path.join(os.path.dirname(__file__), "rsync-tree.py")

def test_expand_via_python():
    """Use python -c to import the module the normal way (sys.path + filename)."""
    # Workaround for hyphenated module name: copy file via stdlib importlib
    # by registering in sys.modules FIRST.
    code = r"""
import sys, importlib.util
spec = importlib.util.spec_from_file_location('rsync_tree_mod', 'rsync-tree.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['rsync_tree_mod'] = mod  # <-- THE FIX
spec.loader.exec_module(mod)

cases = [
    ('node[01-18]', 18, 'node18'),
    ('node0[01-18]', 18, 'node018'),
    ('compute[0-7]', 8, 'compute7'),
    ('rack[01-48]', 48, 'rack48'),
    ('n[1..8]', 8, 'n8'),
    ('server1,server2,server3', 3, 'server3'),
    ('myhost', 1, 'myhost'),
]
fail = 0
for pat, expected_n, expected_last in cases:
    got = mod.expand_nodes(pat)
    ok = (len(got) == expected_n) and (got[-1] == expected_last)
    status = 'OK' if ok else 'FAIL'
    if not ok: fail += 1
    print(f'{status}  {pat!r:30} -> n={len(got):2d} last={got[-1]!r}')
sys.exit(0 if fail == 0 else 1)
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.path.dirname(SCRIPT))
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr)
    return r.returncode == 0


def test_help():
    r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
    return r.returncode == 0 and "Event-driven parallel rsync tree" in r.stdout


def test_dry_run_tiny():
    """Dry-run with 2 nodes for 1.5s, should complete and exit 0."""
    r = subprocess.run(
        [sys.executable, SCRIPT, "--dry-run",
         "--nodes", "src,tgt1", "--source", "src",
         "--max-retries", "0"],
        capture_output=True, text=True, timeout=30,
    )
    print("STDOUT:", r.stdout)
    print("STDERR:", r.stderr)
    return r.returncode == 0


if __name__ == "__main__":
    print("=== test_help ===")
    print("PASS" if test_help() else "FAIL")
    print()
    print("=== test_expand_via_python ===")
    print("PASS" if test_expand_via_python() else "FAIL")
    print()
    print("=== test_dry_run_tiny ===")
    print("PASS" if test_dry_run_tiny() else "FAIL")
