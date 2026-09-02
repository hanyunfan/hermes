#!/usr/bin/env python3
"""
Self-check for collector.py's psutil bootstrap (the try/except at the top).

Runs offline and in ~2s: it never creates a real venv or installs anything.
psutil is hidden from the child via a PYTHONPATH stub that raises
ModuleNotFoundError on import, so these checks exercise the bootstrap even on
a host where psutil is already installed.

  python3 selfcheck_bootstrap.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "collector.py")


def run(stub, env_extra, args=("10", "SELFCHECK"), collector=COLLECTOR, cwd=None):
    """Run collector.py with psutil shadowed out; return (rc, combined output)."""
    env = {**os.environ, "PYTHONPATH": stub, **env_extra}
    p = subprocess.run([sys.executable, collector, *args], env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stub = os.path.join(tmp, "stub")
        os.makedirs(os.path.join(stub, "psutil"))
        with open(os.path.join(stub, "psutil", "__init__.py"), "w") as f:
            f.write("raise ModuleNotFoundError(\"No module named 'psutil'\")\n")

        # 1. The re-exec guard must stop the second attempt rather than loop
        # forever. Without it, systemd's Restart=always turns a missing psutil
        # into an unbounded exec loop.
        rc, out = run(stub, {"_SYSMON_BOOTSTRAPPED": "1",
                             "SYSMON_VENV": "/nonexistent/venv"})
        assert rc != 0, "guard should exit non-zero"
        assert "still missing after bootstrap" in out, out
        assert "/nonexistent/venv" in out, "guard should name the venv to remove: " + out
        print("PASS  the re-exec guard exits instead of looping")

        # 2. An unusable venv location must fail with an actionable message
        # (and must not silently fall through to importing psutil).
        rc, out = run(stub, {"SYSMON_VENV": "/proc/nope/venv"})
        assert rc != 0, "unwritable venv location should exit non-zero"
        assert "could not create venv" in out, out
        assert "python3-venv" in out, "should hint at the Debian package: " + out
        print("PASS  an unusable venv path fails with an actionable message")

        # 3. SYSMON_VENV must be honoured, so a caller can relocate the venv
        # off a read-only or noexec checkout.
        assert "/proc/nope/venv" in out, "SYSMON_VENV should override the default path"
        print("PASS  SYSMON_VENV overrides the default .venv location")

        # 4. With SYSMON_VENV unset the default is a .venv beside the *script*,
        # not in the cwd. Checked against a copy in a read-only dir so the
        # default path is exercised without building a venv in the checkout.
        if os.geteuid() != 0:
            ro = os.path.join(tmp, "ro")
            os.makedirs(ro)
            shutil.copy(COLLECTOR, ro)
            os.chmod(ro, 0o500)                      # r-x: venv creation must fail
            try:
                rc, out = run(stub, {}, collector=os.path.join(ro, "collector.py"),
                              cwd="/")               # cwd deliberately elsewhere
                assert rc != 0, out
                assert os.path.join(ro, ".venv") in out, \
                    "default venv should sit beside the script, got: " + out
                print("PASS  the default venv path is derived from the script directory")
            finally:
                os.chmod(ro, 0o700)                  # let TemporaryDirectory clean up

    print("\nall checks passed")


if __name__ == "__main__":
    main()
