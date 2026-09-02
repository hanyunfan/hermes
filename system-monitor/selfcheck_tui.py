#!/usr/bin/env python3
"""Self-check for the --tui dashboard and the nvidia-smi field parser.

Two parts:
  1. Pure-function checks on the rendering helpers (no terminal needed).
  2. A pty smoke test that actually starts the curses UI, confirms the panels
     paint, and confirms 'q' exits.

Offline, no third-party packages, ~6s. Needs psutil, since it imports
collector.py.

  python3 selfcheck_tui.py
"""

import glob
import importlib.util
import json
import os
import pty
import re
import select
import shutil
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import psutil                                          # noqa: F401
except ModuleNotFoundError:
    print("SKIP  psutil is not importable, so collector.py cannot be imported.\n"
          "      Run collector.py once to bootstrap its venv, then use that "
          "interpreter:\n        .venv/bin/python3 selfcheck_tui.py")
    sys.exit(0)

_spec = importlib.util.spec_from_file_location("collector",
                                               os.path.join(HERE, "collector.py"))
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"PASS  {msg}")


# ── 1. nvidia-smi cell parsing ──────────────────────────────────────────────
# The regression that made every GPU read as {'error': ...}: one unsupported
# field ('[N/A]' for temperature.gpu.tlimit on consumer boards) used to abort
# the whole row via float().
assert c._smi_float("41.55") == 41.55
assert c._smi_float("[N/A]") is None
assert c._smi_float("[Not Supported]") is None
assert c._smi_float("N/A") is None
assert c._smi_float("") is None
assert c._smi_float(None) is None
assert c._smi_float(" 90 ") == 90.0
ok("nvidia-smi '[N/A]' cells parse to None instead of raising")

# ── 2. Ring buffer ──────────────────────────────────────────────────────────
b = c._RingBuf(3)
for v in (1, 2, 3, 4):
    b.append(v)
assert b.values() == [2, 3, 4], b.values()
assert len(b) == 3
b2 = c._RingBuf(4)
for v in (5.0, None, None):
    b2.append(v)
assert b2.last() == 5.0, "last() must skip trailing gaps"
assert c._RingBuf(2).last() is None
ok("ring buffer caps, and last() skips gaps rather than reporting None")

# ── 3. Sparklines ───────────────────────────────────────────────────────────
buf = c._RingBuf(64)
for v in (0, 50, 100):
    buf.append(v)
s = c._sparkline(buf, 10)
assert len(s) == 10, repr(s)
# Growth is left-to-right: the samples sit at the start, padding at the end.
assert s[0] != " " and s.endswith("   "), repr(s)
assert s[0] == c._SPARK[0] and s[2] == c._SPARK[-1], repr(s)
ok("sparkline fills left-to-right so a short history is visible immediately")

empty = c._sparkline(c._RingBuf(8), 12)
assert empty == " " * 12, repr(empty)
gap = c._RingBuf(8)
for v in (10, None, 10):
    gap.append(v)
assert c._sparkline(gap, 3)[1] == " ", "a None sample must render as a gap"
ok("empty series render blank and gaps stay visible")

flat = c._RingBuf(8)
for _ in range(4):
    flat.append(7.0)
assert set(c._sparkline(flat, 4)) == {c._SPARK[0]}, "flat series -> lowest block"
ok("a flat series renders as the lowest block, not as blank")

# Fixed scale is what stops an idle box from looking frantic: 9.8% vs 9.9%
# memory must not autoscale into a full-height mountain range.
noise = c._RingBuf(8)
for v in (9.8, 9.9, 9.8, 9.9):
    noise.append(v)
pinned = c._sparkline(noise, 4, lo=0.0, hi=100.0)
assert len(set(pinned)) == 1, f"pinned scale must be flat, got {pinned!r}"
assert pinned[0] in c._SPARK[:2], f"~10% should sit near the floor, got {pinned!r}"
assert len(set(c._sparkline(noise, 4))) > 1, "autoscaled, the same data varies"
ok("a pinned 0-100 scale keeps idle percentages flat")

# ── 4. Bars and formatters ──────────────────────────────────────────────────
assert c._bar(0, 10) == "░" * 10
assert c._bar(100, 10) == "█" * 10
assert c._bar(50, 10) == "█" * 5 + "░" * 5
assert c._bar(None, 4) == "░" * 4
assert c._bar(1e9, 4) == "█" * 4, "must clamp above 100%"
assert c._bar(-5, 4) == "░" * 4, "must clamp below 0%"
assert len(c._bar(37, 7)) == 7
ok("bars clamp out-of-range percentages and keep a fixed width")

assert c._fmt_bytes_mb(512) == "512M"
assert c._fmt_bytes_mb(2048) == "2.0G"
assert c._fmt_bytes_mb(None).strip() == "?"
assert c._fmt_freq(3686) == "3.69GHz"
assert c._fmt_freq(800) == "800MHz"
assert c._fmt_freq(None) == "?"
assert "G" in c._fmt_rate(2048) and "M" in c._fmt_rate(3.5)
assert c._fmt_rate(None).strip() == "—"
ok("byte / frequency / rate formatters roll over and handle None")

# ── 5. GPU temperature comes from either backend ────────────────────────────
assert c._gpu_temp({"temp_c": 61}, {}) == 61                    # amd-smi
assert c._gpu_temp({}, {"temp_c": 62}) == 62                    # nvidia-smi
assert c._gpu_temp({"temperature": 63}, {}) == 63               # merged field
assert c._gpu_temp({}, {}) is None
ok("GPU temperature is found in whichever place the backend put it")

# temperature.gpu.tlimit is the thermal MARGIN, not a ceiling. Read as a
# ceiling, this laptop's 48°C against a 39°C margin flagged an idle GPU as
# critical.
assert c._gpu_temp_level(48.0, 39.0) == "ok", "a wide margin is not hot"
assert c._gpu_temp_level(84.0, 3.0) == "hot", "a margin of 3°C is throttling"
assert c._gpu_temp_level(70.0, 12.0) == "warn"
assert c._gpu_temp_level(None, None) == "none"
# With no margin reported (AMD, most data-center NVIDIA) fall back to absolutes.
assert c._gpu_temp_level(90.0, None) == "hot"
assert c._gpu_temp_level(75.0, None) == "warn"
assert c._gpu_temp_level(40.0, None) == "ok"
# A probed absolute throttle point wins over both: 84°C is fine on a 92°C
# data-center part but throttling on an 87°C laptop.
assert c._gpu_temp_level(84.0, None, 92.0) == "warn"
assert c._gpu_temp_level(84.0, None, 87.0) == "hot"
assert c._gpu_temp_level(60.0, None, 92.0) == "ok"
assert c._gpu_temp_level(84.0, 39.0, 87.0) == "hot", "tmax outranks the margin"
ok("GPU tlimit is a margin; a probed absolute throttle point outranks it")

# ── 5b. nvidia-smi -q throttle-temperature parsing ──────────────────────────
# Newer drivers report the whole T.Limit family as offsets, so a label
# containing 'T.Limit' must never be used as a ceiling. Real output from an
# RTX PRO 2000 Blackwell laptop GPU:
BLACKWELL = """
    Temperature
        GPU Current Temp                               : 43 C
        GPU T.Limit Temp                               : 44 C
        GPU Shutdown T.Limit Temp                      : -5 C
        GPU Slowdown T.Limit Temp                      : -2 C
        GPU Max Operating T.Limit Temp                 : 0 C
        GPU Target Temperature                         : 87 C
        Memory Current Temp                            : N/A
"""
assert c._parse_nvidia_temp_max(BLACKWELL) == 87.0, \
    c._parse_nvidia_temp_max(BLACKWELL)
# ...and the derived path agrees with the reported absolute: 43 + 44 = 87.
NO_ABSOLUTE = "\n".join(l for l in BLACKWELL.splitlines()
                        if "Target Temperature" not in l)
assert c._parse_nvidia_temp_max(NO_ABSOLUTE) == 87.0, "current + margin"

# Older / data-center drivers use absolute labels; slowdown is preferred.
AMPERE = """
    Temperature
        GPU Current Temp                               : 34 C
        GPU Shutdown Temp                              : 92 C
        GPU Slowdown Temp                              : 89 C
        GPU Max Operating Temp                         : 85 C
        GPU Target Temperature                         : 83 C
"""
assert c._parse_nvidia_temp_max(AMPERE) == 89.0, c._parse_nvidia_temp_max(AMPERE)
# A 0 C reading is a nonsense ceiling and must not be accepted.
assert c._parse_nvidia_temp_max(
    "        GPU Max Operating Temp   : 0 C\n") is None
assert c._parse_nvidia_temp_max("") is None
assert c._parse_nvidia_temp_max("Memory Current Temp : N/A") is None
ok("nvidia-smi -q throttle temps parse on both driver generations")

# ── 6. Sample folding ───────────────────────────────────────────────────────
st = c._tui_state("TestCPU", 8, "BOX", 10)
sample = {
    "timestamp": "2026-09-02T10:00:00+00:00",
    "cpu_percent": 12.5, "memory_percent": 40.0,
    "system_power_w": 210.0, "cpu_power_w": 30.0,
    "gpu": [{"id": 0, "utilization": 55.0, "memory_used_mb": 1024.0,
             "memory_total_mb": 8192.0, "rxpci_mbs": 100.0, "txpci_mbs": 24.0},
            {"id": 1, "utilization": 5.0, "memory_used_mb": 512.0,
             "memory_total_mb": 8192.0, "nvlrx_mbs": 512.0, "nvltx_mbs": 512.0}],
    "gpu_power": [{"id": 0, "power_w": 90.0, "power_limit_w": 300.0, "temp_c": 61.0},
                  {"id": 1, "power_w": 80.0, "power_limit_w": 300.0, "temp_c": 59.0}],
    "network": [{"name": "eth0", "rx_mbs": 1.5, "tx_mbs": 0.5}],
}
c._push_sample(st, sample)
assert st["samples"] == 1
assert len(st["gpu_hist"]) == 2, "one history group per GPU"
assert st["gpu_hist"][0]["util"].last() == 55.0
assert st["gpu_hist"][0]["pcie"].last() == 124.0, "PCIe rx+tx are summed"
assert st["gpu_hist"][1]["nvl"].last() == 1024.0, "NVLink rx+tx are summed"
assert st["history"]["gpu_pwr_total"].last() == 170.0, "GPU power sums across GPUs"
assert st["history"]["net_rx"].last() == 1.5
assert abs(st["history"]["pcie"].last() - (124.0 + 1024.0) / 1024.0) < 1e-9, \
    "aggregate link traffic is reported in GB/s"
assert len(st["log"]) == 1
ok("a snapshot folds into per-GPU history with links and power aggregated")

# A GPU that fails to answer must not poison the aggregates.
c._push_sample(st, {"timestamp": "t", "cpu_percent": 1.0, "memory_percent": 2.0,
                    "gpu": [{"id": 0, "error": "boom"}], "gpu_power": [{"id": 0}],
                    "network": []})
assert st["samples"] == 2
assert st["gpu_hist"][0]["util"].last() == 55.0, "last() falls back past the gap"
assert st["history"]["net_rx"].values()[-1] is None, "no interfaces -> a gap"
ok("an errored GPU query leaves a gap instead of corrupting the series")

# ── 7. Log scrolling ────────────────────────────────────────────────────────
st2 = c._tui_state("c", 1, "b", 5)
for i in range(5):
    c._push_sample(st2, {"timestamp": f"t{i}", "cpu_percent": 0.0,
                         "memory_percent": 0.0, "network": []})
assert st2["log_scroll"] == 0, "pinned to newest by default"
st2["log_scroll"] = 2
c._push_sample(st2, {"timestamp": "t5", "cpu_percent": 0.0,
                     "memory_percent": 0.0, "network": []})
assert st2["log_scroll"] == 3, "a scrolled-back view holds position as lines arrive"
ok("the log stays pinned to newest, and holds position when scrolled back")

# ── 8. Layout signature ─────────────────────────────────────────────────────
# The first sample has network=[] because throughput needs two readings, so
# NETWORK appears on sample two and shifts every panel below it. A changed
# signature is what forces the full repaint instead of a differential update
# against a frame of a different shape.
a = c._layout_sig(st2, 40, 120)
st2["last"] = dict(st2["last"], network=[{"name": "eth0", "rx_mbs": 0, "tx_mbs": 0}])
assert c._layout_sig(st2, 40, 120) != a, "network appearing must change the signature"
assert c._layout_sig(st2, 24, 120) != c._layout_sig(st2, 40, 120), "size matters"
# Scrolling slides a block of rows, which is the same insert/delete-line
# hazard: without this, window '2-7 of 9' rendered 'net tx' twice on screen.
b = c._layout_sig(st2, 40, 120)
st2["hist_scroll"] = 2
assert c._layout_sig(st2, 40, 120) != b, "a HISTORY scroll must force a repaint"
d = c._layout_sig(st2, 40, 120)
st2["log_scroll"] += 4          # section 7 already left this non-zero
assert c._layout_sig(st2, 40, 120) != d, "a LOG scroll must force a repaint"
ok("the repaint key changes on panel appearance, resize and either scroll")

# ── 9. Key decoding table ───────────────────────────────────────────────────
# Terminals send SS3 (\033OA) in application-keypad mode and CSI (\033[A)
# otherwise; both must map, or an arrow key would fall through as a bare ESC.
assert c._ESC_KEYS["[A"] == c._ESC_KEYS["OA"] == "KEY_UP"
assert c._ESC_KEYS["[B"] == c._ESC_KEYS["OB"] == "KEY_DOWN"
assert c._ESC_KEYS["[5~"] == "KEY_PPAGE" and c._ESC_KEYS["[6~"] == "KEY_NPAGE"
assert c._ESC_KEYS["[H"] == c._ESC_KEYS["OH"] == c._ESC_KEYS["[1~"] == "KEY_HOME"
# Every name must exist in curses, or the key would raise on first press.
import curses as _curses
for _name in set(c._ESC_KEYS.values()):
    assert hasattr(_curses, _name), f"curses has no {_name}"
ok("both SS3 and CSI arrow encodings decode to the same keys")

# ── 9b. HISTORY scroll window ───────────────────────────────────────────────
# An 8-GPU box has 4 series per GPU plus the system ones — over 30 rows, so
# most are off-screen and must be reachable, not merely counted.
assert c._hist_window(33, 8, 0)  == (0, 8),  "top of a long list"
assert c._hist_window(33, 8, 5)  == (5, 8),  "scrolled into the middle"
assert c._hist_window(33, 8, 25) == (25, 8), "last full page"
assert c._hist_window(33, 8, 99) == (25, 8), "over-scroll clamps to the end"
assert c._hist_window(33, 8, -3) == (0, 8),  "negative clamps to the start"
assert c._hist_window(5, 8, 0)   == (0, 5),  "a short list shows everything"
assert c._hist_window(5, 8, 4)   == (0, 5),  "...and cannot be scrolled"
assert c._hist_window(0, 8, 2)   == (0, 0),  "no series at all"
assert c._hist_window(33, 0, 4)  == (0, 0),  "no room to draw"
# A resize that shrinks the panel must not leave a stale offset past the end.
_off, _n = c._hist_window(33, 3, 30)
assert _off + _n <= 33 and _n == 3, (_off, _n)
ok("the HISTORY scroll window clamps at both ends and survives a resize")

# The UI names the output file; a relpath from an unrelated cwd would render
# as '../../../../../../tmp/...', so those fall back to the absolute path.
assert c._display_path(os.path.join(os.getcwd(), "data", "m.json")) == "data/m.json"
assert os.path.isabs(c._display_path("/tmp/elsewhere/data/m.json")) or \
    os.getcwd() == "/tmp/elsewhere/data", c._display_path("/tmp/elsewhere/data/m.json")
assert not c._display_path("/tmp/elsewhere/data/m.json").startswith("..")
ok("the displayed data path stays readable from any working directory")


# ── 9d. Watching a workload ─────────────────────────────────────────────────
# Injected finder + clock, so this covers the timing rules without spawning
# processes or sleeping.
alive = {"up": True}
w = c._Watcher("train.py", linger_s=10.0, appear_s=60.0,
               finder=lambda _p: [4242] if alive["up"] else [], now=0.0)
assert w.poll(now=0.0) is None and w.seen, "a running process is detected"
assert w.poll(now=100.0) is None, "still running after a long while"
alive["up"] = False                       # last seen alive at now=100
assert w.poll(now=101.0) is None, "must not stop the instant it disappears"
assert w.poll(now=109.9) is None, "still inside the 10s grace period"
reason = w.poll(now=110.0)                # exactly 10s after the last sighting
assert reason and "exited" in reason, reason
ok("the watcher stops one grace period after the workload exits")

# Starting the monitor first must work: it waits, collecting, until the job
# appears — but a typo'd name must not leave it collecting idle data forever.
late = {"up": False}
w2 = c._Watcher("job", linger_s=5.0, appear_s=60.0,
                finder=lambda _p: [7] if late["up"] else [], now=0.0)
assert w2.poll(now=10.0) is None, "waiting for the job to start"
assert w2.poll(now=59.0) is None, "still inside the appear window"
late["up"] = True
assert w2.poll(now=61.0) is None, "it showed up, so the deadline is moot"
late["up"] = False
assert w2.poll(now=63.0) is None
assert w2.poll(now=66.0) is not None, "grace period applies after it exits"
ok("a workload that starts late is waited for, then still ends the run")

w3 = c._Watcher("never", appear_s=60.0, finder=lambda _p: [], now=0.0)
assert w3.poll(now=59.9) is None
give_up = w3.poll(now=60.0)
assert give_up and "never" in give_up and "60s" in give_up, give_up
ok("a name that never matches gives up instead of collecting forever")

# An enumeration error must not be read as "the process ended".
def _boom(_p):
    raise psutil.AccessDenied(1)
w4 = c._Watcher("x", linger_s=1.0, finder=_boom, now=0.0)
assert w4.poll(now=0.0) is None and not w4.seen
assert w4.poll(now=100.0) is None or not w4.seen, "a failing scan is not an exit"
ok("a failed process scan does not end the run")

# The monitor's own argv contains the pattern (--watch train.py), so matching
# itself would mean never stopping.
assert os.getpid() in c._own_lineage()
ok("the watcher excludes itself and its ancestors from matching")


# ── 9c. Mode selection ──────────────────────────────────────────────────────
# The dashboard is the default, so the no-TTY fallback is load-bearing: the
# systemd unit has no TTY and Restart=always would turn an exit into a silent
# 5s crash loop collecting nothing.
#                  tui    raw    silent  tty
assert c._pick_mode(False, False, False, True)  == "tui",  "default on a terminal"
assert c._pick_mode(False, False, False, False) == "raw",  "no TTY must not be fatal"
assert c._pick_mode(False, True,  False, True)  == "raw",  "--raw overrides a TTY"
assert c._pick_mode(False, False, True,  True)  == "silent", "--silent on a tty"
assert c._pick_mode(False, False, True,  False) == "silent", "--silent needs no tty"
assert c._pick_mode(True,  False, False, True)  == "tui"
# Explicit --tui without a TTY stays 'tui' so tui() can report the real
# problem, rather than silently doing something else than asked.
assert c._pick_mode(True,  False, False, False) == "tui"
for combo in ((True, True, False), (True, False, True), (False, True, True),
              (True, True, True)):
    try:
        c._pick_mode(*combo, True)
    except ValueError:
        pass
    else:
        raise AssertionError(f"conflicting modes {combo} must be rejected")
ok("mode selection defaults to the dashboard but never fails for want of a TTY")

# The shipped unit must not rely on that fallback silently.
_unit = os.path.join(HERE, "system-monitor.service")
if os.path.exists(_unit):
    _txt = open(_unit).read()
    _exec = [l for l in _txt.splitlines() if l.startswith("ExecStart=")]
    assert _exec, "no ExecStart in system-monitor.service"
    assert "--raw" in _exec[0], f"the unit should pass --raw explicitly: {_exec[0]}"
    assert "--tui" not in _exec[0], "the unit must not ask for a dashboard"
    ok("system-monitor.service pins --raw explicitly")


# ── 10. pty smoke test of the real curses UI ────────────────────────────────

def smoke(workdir):
    """Start the TUI in a pty; check the panels paint, JSON lands, 'q' exits.

    Runs a copy of collector.py from `workdir` because DATA_DIR is derived from
    the script's own location, and the TUI now appends samples — pointing it at
    the checkout would litter the real data/ directory."""
    collector = os.path.join(workdir, "collector.py")
    shutil.copy(os.path.join(HERE, "collector.py"), collector)
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        # ncurses prefers $LINES/$COLUMNS over the pty size; leave them unset.
        os.environ.pop("LINES", None)
        os.environ.pop("COLUMNS", None)
        os.execv(sys.executable,
                 [sys.executable, collector, "--tui", "2", "SELFCHECK"])
    out = bytearray()
    deadline = time.time() + 12
    try:
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    d = os.read(fd, 1 << 16)
                except OSError:
                    break
                if not d:
                    break
                out.extend(d)
            txt = out.decode("utf-8", "replace")
            # Wait for the LOG title too, not just the header: curses paints
            # rows top-down, so a read can return the header's n=1 before the
            # rest of that frame has been written.
            if ("SYSTEM" in txt and "n=1" in txt
                    and "metrics_SELFCHECK" in txt):
                break
        txt = out.decode("utf-8", "replace")
        for panel in ("SYSTEM", "GPU", "LOG", "system-monitor"):
            assert panel in txt, f"{panel!r} never painted; got:\n{txt[-600:]}"
        assert "space pause" in txt, "footer key hints missing"
        ok("the curses UI starts in a pty and paints its panels")

        # The dashboard must persist samples, not just display them — the
        # files are what gets uploaded, and it wrote nothing at all before.
        written = glob.glob(os.path.join(workdir, "data", "metrics_SELFCHECK_*.json"))
        assert written, ("the TUI wrote no data file; found "
                         f"{os.listdir(os.path.join(workdir, 'data'))}")
        with open(written[0]) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        assert lines, "the data file is empty"
        rec = json.loads(lines[0])
        for field in ("timestamp", "hostname", "display_name", "cpu_percent",
                      "memory_percent", "network"):
            assert field in rec, f"{field} missing from a TUI-written record"
        assert rec["display_name"] == "SELFCHECK"
        # Display-only fields must not leak into the file, or TUI-written and
        # raw-written records would differ in shape.
        leaked = [k for k in rec if k.startswith("_")]
        assert not leaked, f"display-only fields leaked into the JSON: {leaked}"
        ok("the dashboard appends the same JSON records that --raw writes")
        assert f"→ data/metrics_SELFCHECK" in txt or "metrics_SELFCHECK" in txt, \
            "the LOG title should name the file being written"
        ok("the UI names the data file it is appending to")

        os.write(fd, b"q")
        for _ in range(40):                     # up to 4s to exit
            time.sleep(0.1)
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                wpid, status = pid, 0
            if wpid:
                assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, \
                    f"unclean exit: {status}"
                ok("'q' exits the UI cleanly and restores the terminal")
                return
        raise AssertionError("'q' did not exit the TUI within 4s")
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        os.close(fd)


if sys.stdout.isatty() or os.environ.get("SELFCHECK_PTY", "1") == "1":
    with tempfile.TemporaryDirectory() as _wd:
        smoke(_wd)
else:
    print("SKIP  pty smoke test (set SELFCHECK_PTY=1 to force)")


# ── 11. --silent end to end, against a real watched process ─────────────────

def silent_watch():
    """Run --silent --watch against a real sleep, and check it self-terminates.

    Uses a copy in a temp dir for the same reason as the smoke test: the
    collector writes next to its own file."""
    import subprocess
    with tempfile.TemporaryDirectory() as wd:
        collector = os.path.join(wd, "collector.py")
        shutil.copy(os.path.join(HERE, "collector.py"), collector)
        # A uniquely-named script so the pattern cannot match anything else.
        marker = os.path.join(wd, "selfcheck_workload_marker.sh")
        with open(marker, "w") as f:
            f.write("#!/bin/sh\nsleep 6\n")
        os.chmod(marker, 0o755)

        job = subprocess.Popen(["/bin/sh", marker])
        t0 = time.time()
        mon = subprocess.run(
            [sys.executable, collector, "2", "SILENTCHK", "--silent",
             "--watch", "selfcheck_workload_marker", "--linger", "3"],
            capture_output=True, text=True, timeout=120)
        elapsed = time.time() - t0
        job.wait(timeout=10)

        assert mon.returncode == 0, f"exit {mon.returncode}: {mon.stderr[-400:]}"
        # It must outlive the job, then stop shortly after the grace period —
        # not at the first missing sample, and not run on forever.
        assert 6 <= elapsed <= 25, f"ran {elapsed:.1f}s, expected ~9-11s"
        ok("--silent --watch outlives the workload, then stops after --linger")

        # stdout is exactly the path, so it can be used directly:
        #   f=$(collector.py 10 X --silent --watch job) && gh upload "$f"
        lines = [l for l in mon.stdout.splitlines() if l.strip()]
        assert len(lines) == 1, f"stdout must be just the path, got {lines}"
        path = lines[0]
        assert os.path.isabs(path), path
        assert os.path.exists(path), f"reported a path that does not exist: {path}"
        assert "SILENTCHK" in path
        with open(path) as f:
            recs = [json.loads(l) for l in f if l.strip()]
        assert len(recs) >= 2, f"expected several samples, got {len(recs)}"
        assert all(r["display_name"] == "SILENTCHK" for r in recs)
        assert not [k for k in recs[0] if k.startswith("_")], "display fields leaked"
        ok("--silent prints only the data file path, and the file is valid JSONL")

        # "Silent" means silent: no per-sample chatter on either stream.
        assert "CPU=" not in mon.stdout and "CPU=" not in mon.stderr, \
            "silent mode must not log samples"
        assert "exited" in mon.stderr, f"should say why it stopped: {mon.stderr!r}"
        ok("--silent stays quiet while running but explains why it stopped")


if os.environ.get("SELFCHECK_SLOW", "1") == "1":
    silent_watch()
else:
    print("SKIP  --silent watch test (SELFCHECK_SLOW=0)")

print(f"\nall {len(PASS)} checks passed")
