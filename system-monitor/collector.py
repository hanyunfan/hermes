#!/usr/bin/env python3
"""
System metrics collector: CPU, GPU (up to 8), memory, GPU power, network.
Writes JSON Lines to data/, and shows a curses dashboard by default (--raw
for line-per-sample logging; both write the same files).

Supports NVIDIA (nvidia-smi) and AMD (amd-smi CLI) GPUs.
No extra Python packages required.
"""

import contextlib
import json
import os
import re
import shutil
import collections
import queue
import signal
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    import psutil
except ModuleNotFoundError:
    # ponytail: bootstrap psutil into a venv beside this script, then re-exec
    # into it. Goes straight to a venv instead of trying `pip install --user`
    # first, because PEP 668 distros (Ubuntu 24.04+, Debian 12+) refuse that
    # outright and a second code path isn't worth the few seconds it'd save.
    # Ceiling: assumes the script dir (or $SYSMON_VENV) is writable and pip can
    # reach an index. Upgrade path: pre-build the venv, or point SYSMON_VENV at
    # a shared prefix to skip per-host installs.
    if os.environ.get("_SYSMON_BOOTSTRAPPED"):
        sys.exit(f"psutil still missing after bootstrap. Remove "
                 f"{os.environ.get('SYSMON_VENV')} and retry, or install it by hand.")
    _venv = os.environ.get("SYSMON_VENV") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".venv")
    _py = os.path.join(_venv, "bin", "python3")
    if not os.path.exists(_py):
        print(f"psutil not found — creating venv at {_venv}", file=sys.stderr)
        try:
            subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", _venv],
                           check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            sys.exit(f"could not create venv at {_venv} ({e}). "
                     f"On Debian/Ubuntu: sudo apt install python3-venv")
    # pip is a no-op once satisfied, so this doubles as self-healing for a
    # venv that exists but is missing psutil (interrupted first run).
    try:
        subprocess.run([_py, "-m", "pip", "install", "-q", "psutil"], check=True)
    except (subprocess.CalledProcessError, OSError) as e:
        sys.exit(f"pip install psutil failed ({e}). No network? "
                 f"Install it by hand: {_py} -m pip install psutil")
    print(f"psutil installed — re-running under {_py}", file=sys.stderr)
    os.execve(_py, [_py, os.path.abspath(__file__)] + sys.argv[1:],
              {**os.environ, "_SYSMON_BOOTSTRAPPED": "1", "SYSMON_VENV": _venv})

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

HOSTNAME = socket.gethostname()

# ─── CPU info ─────────────────────────────────────────────────────────────────

CPU_COUNT = psutil.cpu_count(logical=False)
CPU_TYPE  = None

def _probe_cpu():
    """
    Detect CPU model name from /proc/cpuinfo.
    """
    global CPU_TYPE
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('model name'):
                    CPU_TYPE = line.split(':', 1)[1].strip()
                    return
                if line.startswith('Hardware'):
                    CPU_TYPE = line.split(':', 1)[1].strip()
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(['cat', '/proc/cpuinfo'], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith('model name'):
                CPU_TYPE = line.split(':', 1)[1].strip()
                return
    except Exception:
        pass

_probe_cpu()

# ─── CPU debug (opt-in) ───────────────────────────────────────────────────────
# When enabled via --cpu-debug, the collector samples per-core temperature
# (via psutil.sensors_temperatures) and per-core frequency
# (via psutil.cpu_freq(percpu=True)) once per cycle and writes the two arrays
# to the JSON. Frontend hides the two new charts unless cpu_debug === true.
#
# Cardinality:
#   cpu_core_temp_c   — indexed by PHYSICAL core id (sensors expose physical
#                       cores only; some AMD Zen chips only expose Tctl/Tdie
#                       and return []).
#   cpu_core_freq_mhz — indexed by LOGICAL core id (cpuN/cpufreq in sysfs is
#                       per logical CPU). On an HT-enabled chip the two
#                       arrays have different lengths — this is intentional.
#
# Safe to call when CPU_DEBUG is False: the getters return [] in <1ms.

def get_cpu_thermal():
    """
    Comprehensive thermal sensor dump, keyed by chip name.

    Returns a dict like:
      {"k10temp": [{"label": "Tdie", "current": 62.0, "high": None, "critical": None},
                    {"label": "Tccd0", "current": 58.0, ...},
                    ...],
       "coretemp": [{"label": "Core 0", ...}, ...]}

    Empty dict if psutil fails or no sensors are exposed.

    This is the canonical "what does this kernel expose" view — the
    frontend uses it to label chart lines dynamically so it works on
    both Intel (coretemp: Core N) and AMD Zen 4+ (k10temp: Tdie/TccdN)
    without code changes.
    """
    try:
        s = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return {}
    out = {}
    for chip, entries in (s or {}).items():
        serialised = []
        for t in entries:
            serialised.append({
                "label":    t.label or "",
                "current":  float(t.current) if t.current is not None else None,
                "high":     float(t.high) if t.high is not None else None,
                "critical": float(t.critical) if t.critical is not None else None,
            })
        if serialised:
            out[chip] = serialised
    return out


def get_cpu_package_temp(therm):
    """
    Pick the best "single number" package temperature from a therm dump:
    prefer Tdie (true silicon junction on AMD Zen 3+) > Tctl (AMD) >
    Package id 0 (Intel coretemp) > None.

    Returns float (°C) or None.
    """
    if not therm:
        return None
    preferred = []
    for chip, entries in therm.items():
        for t in entries:
            label = t.get("label") or ""
            cur = t.get("current")
            if cur is None:
                continue
            if label == "Tdie":
                return cur
            if label == "Tctl":
                preferred.append(cur)
            elif label.startswith("Package"):
                preferred.append(cur)
    return preferred[0] if preferred else None


def get_cpu_therm_temp_c(therm):
    """
    Per-thermal-sensor temperature series, indexed by *sensor order*
    in the dump.

    The array order matches cpu_therm_raw's iteration order
    (chip alphabetical, sensor entry order), so the frontend can use
    raw's labels 1:1 with this array's indices.

    Includes Tdie / Tctl / Package id N as well as per-core sensors.
    On multi-socket systems (e.g. AMD EPYC dual-socket), the kernel
    reports two Tctl entries (one per physical CPU package); both
    appear here as separate array slots so the dashboard can plot
    them as separate lines. The frontend disambiguates labels.

    Returns [] if no sensors. Tdie/Tctl/Package are NOT excluded —
    dropping them would silently lose socket temperature data on
    machines that only expose Tctl (e.g. some EPYC 9005 series).
    """
    if not therm:
        return []
    out = []
    for chip, entries in therm.items():
        for t in entries:
            label = t.get("label") or ""
            cur = t.get("current")
            # Skip non-CPU-thermal chips (NVMe, NIC, etc.) to keep the
            # chart focused. Core N / TccdN / Tdie / Tctl / Package *
            # all pass through.
            if not (label.startswith("Core ") or label.startswith("Tccd") or
                    label == "Tdie" or label == "Tctl" or label.startswith("Package")):
                continue
            out.append(cur if cur is not None else None)
    return out


def get_cpu_core_freq():
    """Return list[float] indexed by logical core id, [] on failure.

    Length matches psutil.cpu_count(logical=True). Reads
    /sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq via psutil.
    """
    try:
        f = psutil.cpu_freq(percpu=True)
    except Exception:
        return []
    if not f:
        return []
    return [round(c.current, 1) for c in f]

# ─── GPU globals ───────────────────────────────────────────────────────────────

GPU_AVAILABLE = True
GPU_COUNT = 0
GPU_TYPE  = None
GPU_VENDOR = None   # "nvidia" or "amd"

_amd_monitor_cache = None   # cached _amd_query_all() result
_amd_last_query = 0.0       # monotonic timestamp of last query


# ─── GPU probe: detect vendor then load appropriate backend ───────────────────

def _probe_gpu():
    """
    Detect GPU vendor via lspci, then dispatch to the correct backend.
    """
    print("[probe] _probe_gpu() starting")
    global GPU_COUNT, GPU_TYPE, GPU_VENDOR

    # Fast path: dedicated command — one line per AMD GPU
    try:
        result = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True, text=True, timeout=5
        )
        amd_lines = [ln for ln in result.stdout.splitlines()
                     if "ATI" in ln and "accelerators" in ln]
        if amd_lines:
            GPU_VENDOR = "amd"
            print(f"[probe] lspci detected {len(amd_lines)} AMD GPUs via ATI+accelerators")
        else:
            for line in result.stdout.splitlines():
                if any(kw in line for kw in ("VGA", "3D controller", "Processing accelerators")):
                    if any(kw in line for kw in ("NVIDIA", "GeForce", "Quadro", "RTX", "A100", "H100")):
                        GPU_VENDOR = "nvidia"
                        print(f"[probe] lspci detected nvidia: {line.strip()}")
                        break
    except Exception as e:
        print(f"[probe] lspci failed: {e}")

    # Fallback when lspci didn't find any GPU
    if GPU_VENDOR is None:
        print("[probe] lspci found no GPU, trying nvidia-smi / amd-smi fallback")
        try:
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, check=True, timeout=5
            )
            GPU_VENDOR = "nvidia"
            print("[probe] nvidia-smi succeeded")
        except Exception as e:
            print(f"[probe] nvidia-smi failed: {e}")
            try:
                r = subprocess.run(
                    ["amd-smi", "static", "--gpu", "0"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0 and "AMD" in r.stdout:
                    GPU_VENDOR = "amd"
                    print("[probe] amd-smi vendor check succeeded")
                else:
                    print(f"[probe] amd-smi vendor check failed: {r.stdout[:200]}")
            except Exception as e2:
                print(f"[probe] amd-smi failed: {e2}")
                GPU_AVAILABLE = False
                GPU_COUNT = 0
                GPU_TYPE = None
                print("No supported GPU detected, GPU metrics disabled.")
                return

    if GPU_VENDOR == "nvidia":
        _probe_nvidia()
    elif GPU_VENDOR == "amd":
        _probe_amd()


# ─── NVIDIA backend ───────────────────────────────────────────────────────────

# Absolute throttle temperature per GPU (°C), probed once — these are board
# constants, so re-reading them every cycle would cost a subprocess for nothing.
GPU_TEMP_MAX = []

_TEMP_MAX_FIELDS = ("GPU Slowdown Temp", "GPU Shutdown Temp",
                    "GPU Max Operating Temp", "GPU Target Temperature")


def _parse_nvidia_temp_max(qout):
    """Absolute throttle temperature (°C) from `nvidia-smi -q` text, or None.

    Two driver generations spell this differently and the difference is not
    cosmetic:

      older / data-center     GPU Shutdown Temp     : 92 C     ← absolute
      newer (Blackwell, ...)  GPU Shutdown T.Limit Temp : -5 C ← an OFFSET

    The T.Limit family reports margins, not temperatures, so a label
    containing 'T.Limit' can never be used as a ceiling — that mistake is what
    put a 39 °C reference line under a 48 °C reading. Absolute fields are
    preferred in throttle-relevance order; failing that, the absolute maximum
    is reconstructed as current + T.Limit margin, which on this laptop gives
    43 + 44 = 87 °C and matches its reported GPU Target Temperature exactly.

    Returns None when nothing usable is present (the caller substitutes a
    conservative default)."""
    vals, cur, tlimit = {}, None, None
    for line in qout.splitlines():
        if ":" not in line:
            continue
        label, _, raw = line.partition(":")
        label, raw = label.strip(), raw.strip()
        if not raw.endswith(" C"):
            continue
        try:
            deg = float(raw[:-2].strip())
        except ValueError:
            continue
        if "T.Limit" in label:
            if label == "GPU T.Limit Temp":
                tlimit = deg
            continue                       # offsets are unusable as ceilings
        if label == "GPU Current Temp":
            cur = deg
        elif label in _TEMP_MAX_FIELDS:
            vals[label] = deg
    for field in _TEMP_MAX_FIELDS:
        if vals.get(field):                # 0 C would be a nonsense ceiling
            return vals[field]
    if cur is not None and tlimit is not None:
        return cur + tlimit
    return None


def _nvidia_probe_temp_max(gpu_id):
    try:
        r = subprocess.run(["nvidia-smi", "-q", "-i", str(gpu_id)],
                           capture_output=True, text=True, timeout=10)
        return _parse_nvidia_temp_max(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


def _probe_nvidia():
    global GPU_COUNT, GPU_TYPE, GPU_TEMP_MAX
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True, timeout=5
        )
        raw = result.stdout.strip().split("\n")[0].strip()
        GPU_TYPE = raw[7:].strip().replace(" ", "_") if raw.startswith("NVIDIA ") else raw.replace(" ", "_")
        GPU_COUNT = min(8, len([n for n in result.stdout.strip().split("\n") if n.strip()]))
        GPU_TEMP_MAX = [_nvidia_probe_temp_max(i) for i in range(GPU_COUNT)]
        print(f"[probe] GPU throttle temps: {GPU_TEMP_MAX}")
    except Exception:
        global GPU_AVAILABLE
        GPU_AVAILABLE = False
        GPU_COUNT = 0
        print("nvidia-smi not available, GPU metrics disabled.")


# ─── AMD backend ─────────────────────────────────────────────────────────────

def _probe_amd():
    """
    Probe AMD GPUs using amd-smi CLI.
    GPU count from `amd-smi list`. GPU name from `amd-smi static -a`.
    """
    print("[probe] _probe_amd() called")
    global GPU_COUNT, GPU_TYPE
    global GPU_VENDOR   # override lspci result (lspci may show "3D controller" without "AMD")
    try:
        result = subprocess.run(
            ["amd-smi", "list"],
            capture_output=True, text=True, timeout=10
        )
        print(f"[probe] amd-smi list rc={result.returncode}")
        print(f"[probe] amd-smi list stdout: {repr(result.stdout[:300])}")
        print(f"[probe] amd-smi list stderr: {repr(result.stderr[:100])}")
        gpu_lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        GPU_COUNT = min(8, len(gpu_lines))
        GPU_VENDOR = "amd"   # confirmed by amd-smi
        print(f"[probe] amd-smi list found {GPU_COUNT} GPUs")

        if GPU_COUNT == 0:
            raise RuntimeError("amd-smi list returned no GPU entries")

        # Get GPU name from `amd-smi static -a -g 0`
        result = subprocess.run(
            ["amd-smi", "static", "--gpu", "0"],
            capture_output=True, text=True, timeout=10
        )
        name = None
        for line in result.stdout.splitlines():
            if "PRODUCT_NAME" in line:
                parts = line.strip().split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    name = parts[1].strip()
                    break
        if not name:
            name = "AMD_GPU"
        GPU_TYPE = name.replace(" ", "_")

        print(f"AMD GPU detected: {GPU_COUNT}x {GPU_TYPE} via amd-smi")
        print(f"[probe] GPU_COUNT={GPU_COUNT}, GPU_TYPE={GPU_TYPE}, GPU_VENDOR={GPU_VENDOR}")
    except Exception as e:
        global GPU_AVAILABLE
        GPU_AVAILABLE = False
        GPU_COUNT = 0
        GPU_TYPE = None
        print(f"amd-smi not available, AMD GPU metrics disabled: {e}")


# ─── AMD: single-shot monitor ──────────────────────────────────────────────────

def _amd_query_all():
    """
    Single `amd-smi monitor -p -t -u -m -w 1 -i 1` call for all GPUs.
    Caches result for up to 2 seconds to avoid redundant subprocess calls
    when called multiple times per collect() cycle.
    """
    global _amd_monitor_cache, _amd_last_query

    now = time.monotonic()
    if _amd_monitor_cache is not None and (now - _amd_last_query) < 2.0:
        return _amd_monitor_cache

    try:
        result = subprocess.run(
            ["amd-smi", "monitor", "-p", "-t", "-u", "-m", "-v", "-r",
             "-w", "1", "-i", "1"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return {}
        stdout = result.stdout
    except Exception:
        return {}

    gpus = {}
    lines = stdout.strip().splitlines()

    # Skip header and blank lines; data lines start with a timestamp digit
    data_lines = [ln for ln in lines if ln and ln[0].isdigit()]
    if not data_lines:
        return {}

    # Parse each data row
    for line in data_lines:
        cols = line.split()
        if len(cols) < 28:
            continue
        try:
            gpu_id = int(cols[1])
            power_w = float(cols[3])
            power_limit_w = float(cols[5])
            temp_c = float(cols[7])
            mem_temp_c = float(cols[9])
            utilization = float(cols[13])
            memory_percent = float(cols[15])
            memory_used_mb = float(cols[19])
            memory_total_mb = float(cols[23])
            pcie_bandwidth_mbs = float(cols[27])

            gpus[gpu_id] = {
                "id": gpu_id,
                "power_w": power_w,
                "power_limit_w": power_limit_w,
                "temp_c": temp_c,
                "mem_temp_c": mem_temp_c,
                "utilization": utilization,
                "memory_percent": memory_percent,
                "memory_used_mb": memory_used_mb,
                "memory_total_mb": memory_total_mb,
                "pcie_bandwidth_mbs": pcie_bandwidth_mbs,
            }
        except (ValueError, IndexError):
            continue

    _amd_monitor_cache = gpus
    _amd_last_query = now
    return gpus


# ─── GPU power ────────────────────────────────────────────────────────────────

def get_gpu_power():
    """Returns [{id, power_w, power_limit_w}] or None."""
    if not GPU_AVAILABLE or GPU_COUNT == 0:
        return None
    if GPU_VENDOR == "nvidia":
        return _nvidia_get_gpu_power()
    elif GPU_VENDOR == "amd":
        return _amd_get_gpu_power()
    return None


def _nvidia_get_gpu_power():
    gpus = []
    for i in range(GPU_COUNT):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--id=" + str(i),
                 "--query-gpu=power.draw,power.limit,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=5
            )
            power_draw, power_limit, temp_c = result.stdout.strip().split(", ")
            gpus.append({
                "id": i,
                "power_w": float(power_draw),
                "power_limit_w": float(power_limit),
                "temperature": float(temp_c)
            })
        except Exception:
            gpus.append({"id": i})
    return gpus


def _amd_get_gpu_power():
    """Returns all GPU power data from cached _amd_query_all()."""
    data = _amd_query_all()
    return [data.get(i, {"id": i}) for i in range(GPU_COUNT)]


# ─── GPU PCIe + NVLink throughput ─────────────────────────────────────────────

_GPU_IO_DEBUG = os.environ.get("COLLECTOR_DEBUG", "0") == "1"


def get_gpu_io(enabled=True):
    """
    NVIDIA: parse nvidia-smi dmon for PCIe + NVLink.
    AMD: parse amd-smi metric -P for PCIe bandwidth (aggregate Mb/s).
    """
    if not enabled or not GPU_AVAILABLE or GPU_COUNT == 0:
        return None
    if GPU_VENDOR == "nvidia":
        return _nvidia_get_gpu_io()
    elif GPU_VENDOR == "amd":
        return _amd_get_gpu_io()
    return None


def _nvidia_get_gpu_io():
    try:
        result = subprocess.run(
            ["nvidia-smi", "dmon", "-s", "t", "--gpm-metrics", "60,61", "-c", "4", "-o", "T"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            sys.stderr.write(f"[get_gpu_io] dmon exit code {result.returncode}\n")
            return None
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[get_gpu_io] dmon timed out\n")
        return None
    except Exception as e:
        sys.stderr.write(f"[get_gpu_io] exception: {e}\n")
        return None

    col_map = {}
    gpus_io = {}

    for line in result.stdout.strip().splitlines():
        parts = line.strip().split()
        if not parts:
            continue

        if parts[0].startswith("#"):
            metric_names = {"rxpci", "txpci", "nvlrx", "nvltx", "pcirx", "pcitx"}
            header_cols = [c.lower() for c in parts]
            if metric_names & set(header_cols):
                for idx, col in enumerate(parts[1:]):
                    if col.lower() in metric_names:
                        col_map[col.lower()] = idx
                if _GPU_IO_DEBUG:
                    sys.stderr.write(f"[get_gpu_io] col_map={col_map}\n")
            continue

        if not parts[0].isdigit():
            if len(parts) > 1 and parts[1].isdigit():
                gpu_id = int(parts[1])
                data_cols = parts[1:]
            else:
                continue
        else:
            gpu_id = int(parts[0])
            data_cols = parts[1:]

        def val(key):
            idx = col_map.get(key)
            if idx is None or idx >= len(data_cols) or data_cols[idx] == "-":
                return None
            try:
                return float(data_cols[idx])
            except ValueError:
                return None

        rxpci = val("rxpci")
        txpci = val("txpci")
        _nvlrx = val("nvlrx")
        _nvltx = val("nvltx")
        nvlrx_raw = _nvlrx if _nvlrx is not None else val("pcirx")
        nvltx_raw = _nvltx if _nvltx is not None else val("pcitx")
        nvlrx = round(nvlrx_raw * 1.048576, 3) if nvlrx_raw is not None else None
        nvltx = round(nvltx_raw * 1.048576, 3) if nvltx_raw is not None else None

        gpus_io[gpu_id] = {
            "id": gpu_id,
            "rxpci_mbs": rxpci,
            "txpci_mbs": txpci,
            "nvlrx_mbs": nvlrx,
            "nvltx_mbs": nvltx,
        }

    return [gpus_io.get(i, {"id": i}) for i in range(GPU_COUNT)]


def _amd_get_gpu_io():
    """Returns PCIe/NVLink data from cached _amd_query_all()."""
    data = _amd_query_all()
    return [data.get(i, {"id": i}) for i in range(GPU_COUNT)]


# ─── Network throughput ───────────────────────────────────────────────────────

_NET_PREV = {}   # iface -> (rx_bytes, tx_bytes, timestamp)
_RAPL_PREV = None
_NET_LOCK = threading.Lock()


def _read_net_stats():
    stats = {}
    try:
        for iface in os.listdir("/sys/class/net"):
            if iface in ("lo", "docker0"):
                continue
            try:
                rx = int(open(f"/sys/class/net/{iface}/statistics/rx_bytes").read())
                tx = int(open(f"/sys/class/net/{iface}/statistics/tx_bytes").read())
                stats[iface] = {"rx_bytes": rx, "tx_bytes": tx}
            except (IOError, OSError, ValueError):
                pass
    except OSError:
        pass
    return stats


def _get_net_throughput_mbs():
    now = time.monotonic()
    current = _read_net_stats()
    result = []
    with _NET_LOCK:
        for iface, cur in current.items():
            prev = _NET_PREV.get(iface)
            if prev is not None:
                prev_rx, prev_tx, prev_ts = prev
                dt = now - prev_ts
                if dt > 0:
                    rx_rate = (cur["rx_bytes"] - prev_rx) / dt / (1024 ** 2)
                    tx_rate = (cur["tx_bytes"] - prev_tx) / dt / (1024 ** 2)
                    if rx_rate >= 0 and tx_rate >= 0:
                        result.append({
                            "name": iface,
                            "rx_mbs": round(rx_rate, 3),
                            "tx_mbs": round(tx_rate, 3)
                        })
            _NET_PREV[iface] = (cur["rx_bytes"], cur["tx_bytes"], now)

    def sort_key(x):
        n = x["name"]
        if n.startswith("ib"):
            return (0, n)
        elif n.startswith(("eth", "en", "em")):
            return (1, n)
        else:
            return (2, n)

    result.sort(key=sort_key)
    return result


# ─── GPU stats query helpers ──────────────────────────────────────────────────

def _query_gpu_util_mem(gpu_id):
    if GPU_VENDOR == "nvidia":
        return _nvidia_query_gpu_util_mem(gpu_id)
    elif GPU_VENDOR == "amd":
        return _amd_query_gpu_util_mem(gpu_id)
    return (gpu_id, {"id": gpu_id, "error": "unknown vendor"})


def _query_gpu_power(gpu_id):
    if GPU_VENDOR == "nvidia":
        return _nvidia_query_gpu_power(gpu_id)
    elif GPU_VENDOR == "amd":
        return _amd_query_gpu_power(gpu_id)
    return (gpu_id, {"id": gpu_id, "error": "unknown vendor"})


# ─── NVIDIA helpers ───────────────────────────────────────────────────────────

def _smi_float(s):
    """Parse one nvidia-smi CSV cell to float, or None.

    nvidia-smi prints '[N/A]' (and sometimes '[Not Supported]') for fields the
    board does not expose — temperature.gpu.tlimit is absent on most laptop and
    consumer parts. Letting float() raise on that discarded the whole record,
    so a GPU that reports power and temperature perfectly well showed up as
    {'error': ...} with no readings at all."""
    s = (s or "").strip()
    if not s or s.startswith("[") or s.lower() in ("n/a", "na", "unknown"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _nvidia_query_gpu_util_mem(gpu_id):
    try:
        result = subprocess.run(
            ["nvidia-smi", "--id=" + str(gpu_id),
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=8
        )
        util, mem_used, mem_total = result.stdout.strip().split(", ")
        return (gpu_id, {
            "id": gpu_id,
            "utilization": _smi_float(util),
            "memory_used_mb": _smi_float(mem_used),
            "memory_total_mb": _smi_float(mem_total)
        })
    except Exception as e:
        return (gpu_id, {"id": gpu_id, "error": str(e)})


def _nvidia_query_gpu_power(gpu_id):
    try:
        result = subprocess.run(
            ["nvidia-smi", "--id=" + str(gpu_id),
             "--query-gpu=power.draw,power.limit,temperature.gpu,temperature.gpu.tlimit",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=8
        )
        power_draw, power_limit, temp_c, temp_limit = result.stdout.strip().split(", ")
        return (gpu_id, {
            "id": gpu_id,
            "power_w": _smi_float(power_draw),
            "power_limit_w": _smi_float(power_limit),
            "temp_c": _smi_float(temp_c),
            "temp_limit": _smi_float(temp_limit)
        })
    except Exception as e:
        return (gpu_id, {"id": gpu_id, "error": str(e)})


# ─── AMD helpers ───────────────────────────────────────────────────────────────

def _amd_query_gpu_util_mem(gpu_id):
    """Returns cached util/mem data for one GPU from _amd_query_all()."""
    data = _amd_query_all()
    entry = data.get(gpu_id, {"id": gpu_id})
    # Pick only the util+mem fields
    return (gpu_id, {
        "id": gpu_id,
        "utilization": entry.get("utilization"),
        "memory_percent": entry.get("memory_percent"),
        "memory_used_mb": entry.get("memory_used_mb"),
        "memory_total_mb": entry.get("memory_total_mb"),
    })


def _amd_query_gpu_power(gpu_id):
    """Returns cached power/temp data for one GPU from _amd_query_all()."""
    data = _amd_query_all()
    entry = data.get(gpu_id, {"id": gpu_id})
    return (gpu_id, {
        "id": gpu_id,
        "power_w": entry.get("power_w"),
        "power_limit_w": entry.get("power_limit_w"),
        "temp_c": entry.get("temp_c"),
        "mem_temp_c": entry.get("mem_temp_c"),
    })


# ─── Unified GPU stats collector ─────────────────────────────────────────────

def get_gpu_stats(enable_nvlink=True):
    if not GPU_AVAILABLE or GPU_COUNT == 0:
        return None, None, None

    with ThreadPoolExecutor(max_workers=GPU_COUNT) as ex:
        util_mem_futures = [ex.submit(_query_gpu_util_mem, i) for i in range(GPU_COUNT)]
        util_mem_results = [f.result() for f in util_mem_futures]

    gpu_io = get_gpu_io(enabled=enable_nvlink)

    with ThreadPoolExecutor(max_workers=GPU_COUNT) as ex:
        power_futures = [ex.submit(_query_gpu_power, i) for i in range(GPU_COUNT)]
        power_results = [f.result() for f in power_futures]

    gpus = [None] * GPU_COUNT
    for gpu_id, entry in util_mem_results:
        gpus[gpu_id] = entry

    if gpu_io:
        io_map = {g["id"]: g for g in gpu_io}
        for i in range(GPU_COUNT):
            io_entry = io_map.get(i, {})
            for k, v in io_entry.items():
                if k != "id" and gpus[i] is not None:
                    gpus[i][k] = v

    power_map = {r[0]: r[1] for r in power_results}
    gpu_power = [power_map.get(i, {"id": i}) for i in range(GPU_COUNT)]

    # Merge temperature from power query into gpus dict
    for i in range(GPU_COUNT):
        if gpus[i] is not None:
            pw = power_map.get(i, {})
            if "temperature" in pw:
                gpus[i]["temperature"] = pw["temperature"]

    return gpus, gpu_power, gpu_io


# ─── System power ─────────────────────────────────────────────────────────────

def get_system_power():
    try:
        result = subprocess.run(
            ["ipmitool", "dcmi", "power", "reading"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Instantaneous" in line:
                    val = line.split(":")[-1].strip().split()[0]
                    return float(val)
    except Exception:
        pass
    return None


# ─── CPU power (RAPL) ─────────────────────────────────────────────────────────

def get_cpu_power():
    global _RAPL_PREV
    try:
        check = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True, timeout=2
        )
        if check.returncode != 0:
            return None
        energy_path = "/sys/class/powercap/intel-rapl:0/energy_uj"
        result = subprocess.run(
            ["sudo", "cat", energy_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            joules = float(result.stdout.strip()) / 1_000_000
            now = time.monotonic()
            prev = _RAPL_PREV
            if prev is not None:
                prev_joules, prev_ts = prev
                dt = now - prev_ts
                if dt > 0:
                    watts = (joules - prev_joules) / dt
                    if watts >= 0:
                        _RAPL_PREV = (joules, now)
                        return round(watts, 1)
            _RAPL_PREV = (joules, now)
    except Exception:
        pass
    return None


# ─── Module-level state ───────────────────────────────────────────────────────

_RAPL_PREV = None
display_name = None   # set by daemon()


# ─── Main collect ─────────────────────────────────────────────────────────────

def collect(enable_nvlink=True, cpu_debug=False):
    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    net = _get_net_throughput_mbs()
    sys_power = get_system_power()
    cpu_power = get_cpu_power()
    gpu_stats, gpu_power, _ = get_gpu_stats(enable_nvlink=enable_nvlink)

    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": HOSTNAME,
        "display_name": display_name,
        "cpu_count": CPU_COUNT,
        "cpu_type": CPU_TYPE,
        "gpu_count": GPU_COUNT,
        "gpu_type": GPU_TYPE,
        "gpu_vendor": GPU_VENDOR,
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "memory_used_mb": mem.used / (1024 ** 2),
        "memory_total_mb": mem.total / (1024 ** 2),
        "network": net,
        "system_power_w": sys_power,
        "cpu_power_w": cpu_power,
        "gpu_power": gpu_power,
        # Absolute throttle temperature per GPU (°C), or null where the vendor
        # does not report one (AMD, and NVIDIA boards exposing only T.Limit
        # offsets with no current reading). Static, probed at startup.
        "gpu_temp_max_c": GPU_TEMP_MAX or None,
        "gpu": gpu_stats
    }
    # CPU debug fields are written ONLY when the flag is on, so the JSON
    # shape is byte-identical to the pre-feature output otherwise.
    if cpu_debug:
        stats["cpu_debug"]          = True
        stats["cpu_core_freq_mhz"]  = get_cpu_core_freq()
        # Thermal data: comprehensive dump + structured package/per-sensor.
        # cpu_therm_temp_c replaces the old "Core N"-only cpu_core_temp_c.
        # It works on both Intel coretemp (per physical core) and AMD Zen 4+
        # k10temp (per CCD — the closest thing to per-core on Zen 4).
        therm = get_cpu_thermal()
        stats["cpu_therm_raw"]         = therm
        stats["cpu_package_temp_c"]    = get_cpu_package_temp(therm)
        stats["cpu_therm_temp_c"]      = get_cpu_therm_temp_c(therm)
    return stats


# ─── Watching a workload process ────────────────────────────────────────────

def _own_lineage():
    """This process and its ancestors.

    Needed because the monitor's own argv contains the pattern
    (`--watch train.py`), and so does the shell line that launched it. Without
    excluding them the watcher matches itself and never stops."""
    pids = {os.getpid()}
    try:
        p = psutil.Process()
        while True:
            p = p.parent()
            if p is None or p.pid in pids:
                break
            pids.add(p.pid)
    except Exception:
        pass
    return pids


def _find_processes(pattern):
    """PIDs whose process name or command line contains `pattern`.

    Matches the command line as well as the name because a workload is usually
    `python train.py` or `./run_mlperf.sh`, whose process name is just
    'python3' or 'bash'. Case-insensitive; excludes this process and its
    ancestors."""
    pat = pattern.lower()
    skip = _own_lineage()
    found = []
    for p in psutil.process_iter(attrs=["pid", "name", "cmdline"], ad_value=None):
        pid = p.info.get("pid")
        if pid in skip:
            continue
        name = (p.info.get("name") or "").lower()
        cmd = " ".join(p.info.get("cmdline") or []).lower()
        if pat in name or pat in cmd:
            found.append(pid)
    return found


class _Watcher:
    """Stops collection when a named workload finishes.

    Both start orders work. If the process is not up yet, sampling continues
    while we wait for it — bounded by `appear_s`, so a typo'd name cannot leave
    a silent collector accumulating idle samples forever. Once it has been
    seen, collection continues for `linger_s` after it disappears, which
    captures the cooldown tail without filling the file with idle rows.

    `finder` and the `now` argument are injectable so this is testable without
    spawning processes or sleeping."""

    def __init__(self, pattern, linger_s=10.0, appear_s=60.0,
                 finder=_find_processes, now=None):
        self.pattern  = pattern
        self.linger_s = linger_s
        self.appear_s = appear_s
        self._finder  = finder
        self.started  = now if now is not None else time.monotonic()
        self.seen     = False        # has the process ever been running?
        self.last_up  = None         # last time it was seen alive
        self.pids     = []

    def poll(self, now=None):
        """Returns None to keep collecting, or a reason string to stop."""
        now = now if now is not None else time.monotonic()
        try:
            self.pids = self._finder(self.pattern)
        except Exception:
            self.pids = []           # a transient enumeration error is not a stop
        if self.pids:
            self.seen = True
            self.last_up = now
            return None
        if not self.seen:
            if now - self.started >= self.appear_s:
                return (f"no process matching {self.pattern!r} started within "
                        f"{self.appear_s:.0f}s")
            return None
        if now - self.last_up >= self.linger_s:
            return (f"{self.pattern!r} exited, and the {self.linger_s:.0f}s "
                    f"grace period elapsed")
        return None


# ─── Daemon ─────────────────────────────────────────────────────────────────

def _data_path(period, hostname=None):
    """Path of today's data file. Shared by raw and TUI mode so the two can
    never disagree about where samples land, and so the TUI can display it."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    # Use display_name if set (distinguishes machines with same hostname but different GPU types)
    name = display_name if display_name else (hostname or HOSTNAME)
    return os.path.join(DATA_DIR, f"{period}_{name}_{ts}.json")


def append_to_file(data, period):
    with open(_data_path(period, data.get("hostname")), "a") as f:
        f.write(json.dumps(data) + "\n")


def _sleep_until(deadline, watcher, stop, slice_s=0.5):
    """Sleep until `deadline`, polling the watcher and the stop flag.

    Sliced rather than one long sleep so that a finished workload and Ctrl-C
    are both noticed within half a second instead of up to `interval` late —
    at `--interval 60` a single sleep would make the 10s grace period
    meaningless."""
    while not stop["why"]:
        if watcher is not None:
            reason = watcher.poll()
            if reason:
                stop["why"] = reason
                return
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(slice_s, left))


def _install_stop_handlers(stop):
    """Turn SIGINT/SIGTERM into a flag, so a run always gets to report where
    its data went instead of dying mid-write."""
    def _handler(signum, _frame):
        stop["why"] = f"received {signal.Signals(signum).name}"
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass            # not the main thread, or the platform disallows it


def silent(interval=10, _display_name=None, cpu_debug=False, watch=None,
           linger_s=10.0):
    """Collect with no output at all, then print where the data went.

    Intended for `--silent &` alongside a benchmark: nothing on the terminal
    while it runs, one line at the end naming the file to upload. Errors still
    go to stderr — silence is for normal operation, not for data loss."""
    global display_name
    display_name = _display_name
    enable_nvlink = (interval >= 10)
    stop = {"why": None}
    _install_stop_handlers(stop)
    watcher = _Watcher(watch, linger_s=linger_s) if watch else None

    started = time.monotonic()
    wrote = errors = 0
    first_err = None
    while not stop["why"]:
        tick = time.monotonic()
        try:
            stats = collect(enable_nvlink=enable_nvlink, cpu_debug=cpu_debug)
            append_to_file(stats, "metrics")
            wrote += 1
        except Exception as e:
            errors += 1
            if first_err is None:
                first_err = f"{type(e).__name__}: {e}"
                print(f"collector: {first_err}", file=sys.stderr)
        _sleep_until(tick + interval, watcher, stop)

    path = _data_path("metrics")
    mins = (time.monotonic() - started) / 60.0
    if wrote:
        # stdout carries the path and nothing else; everything explanatory
        # goes to stderr so the caller can capture one without the other.
        print(f"{os.path.abspath(path)}")
        gpu = f"{GPU_COUNT}x {GPU_TYPE}" if GPU_COUNT else "no GPU"
        print(f"  {wrote} samples over {mins:.1f} min ({gpu}) — {stop['why']}",
              file=sys.stderr)
    else:
        print("collector: no samples were written — "
              f"{stop['why']}", file=sys.stderr)
        sys.exit(1)
    if errors:
        print(f"  {errors} sample(s) failed, first: {first_err}", file=sys.stderr)


def daemon(interval=10, _display_name=None, cpu_debug=False, watch=None,
           linger_s=10.0):
    global display_name
    display_name = _display_name
    type_label = f" {GPU_TYPE}" if GPU_TYPE else ""
    gpu_label = f"{GPU_COUNT}x{type_label} GPU" if GPU_COUNT else "no GPU"
    vendor_label = f"({GPU_VENDOR.upper()})" if GPU_VENDOR else ""
    enable_nvlink = (interval >= 10)
    if _display_name:
        print(f"  Display name: [{_display_name}]  (hostname: [{HOSTNAME}])")
    if interval < 10:
        print("\n" + "=" * 60)
        print("\033[91m  WARNING: NVLink/PCIe monitoring will NOT start\033[0m")
        print(f"           This feature requires interval >= 10s (current: {interval}s)")
        print("=" * 60 + "\n")
    if cpu_debug:
        print("CPU debug mode ENABLED — per-core temp + freq will be recorded each cycle")
    print(f"Collector starting on [{HOSTNAME}], interval={interval}s, NVLink={'enabled' if enable_nvlink else 'disabled'}, GPU={gpu_label} {vendor_label}")
    stop = {"why": None}
    watcher = None
    if watch:
        _install_stop_handlers(stop)
        watcher = _Watcher(watch, linger_s=linger_s)
        print(f"Watching for a process matching [{watch}] — collection ends "
              f"{linger_s:.0f}s after it exits")
    while not stop["why"]:
        try:
            stats = collect(enable_nvlink=enable_nvlink, cpu_debug=cpu_debug)
            append_to_file(stats, "metrics")
            pwr_str = ""
            if stats.get("system_power_w") is not None:
                pwr_str += f" SYS={stats['system_power_w']:.0f}W"
            if stats.get("cpu_power_w") is not None:
                pwr_str += f" CPU={stats['cpu_power_w']:.0f}W"
            if stats.get("gpu_power"):
                pwr_str += " " + "/".join(
                    f"GPU{g['id']}={g.get('power_w', '?')}W" for g in stats["gpu_power"]
                )
            net_str = ""
            if stats.get("network"):
                net_str = " " + "/".join(
                    f"{n['name']}={n['rx_mbs']:.1f}/{n['tx_mbs']:.1f}MB/s" for n in stats["network"]
                )
            gpu_str = ""
            if stats.get("gpu"):
                for g in stats["gpu"]:
                    nv = ""
                    if g.get("nvlrx_mbs") is not None:
                        nv = f" NV={g['nvlrx_mbs']:.1f}/{g['nvltx_mbs']:.1f}MB/s"
                    elif g.get("rxpci_mbs") is not None:
                        nv = f" PCIe={g['rxpci_mbs']:.1f}/{g['txpci_mbs']:.1f}MB/s"
                    elif g.get("pcie_bandwidth_mbs") is not None:
                        nv = f" PCIe={g['pcie_bandwidth_mbs']:.1f}MB/s"
                    gpu_str += f" GPU{g['id']}={g.get('utilization','?')}%{nv}"

            # CPU debug summary (compact one-liner appended to the same log line)
            debug_str = ""
            if cpu_debug:
                pkg = stats.get("cpu_package_temp_c")
                therms = stats.get("cpu_therm_temp_c") or []
                raw = stats.get("cpu_therm_raw") or {}
                # Per-sensor line with human-readable labels
                therm_parts = []
                for chip, entries in raw.items():
                    for t in entries:
                        cur = t.get("current")
                        if cur is None:
                            continue
                        therm_parts.append(f"{chip}.{t.get('label') or '?'}={cur:.0f}")
                if pkg is not None:
                    debug_str += f" Tpkg={pkg:.0f}"
                if therm_parts:
                    debug_str += " T=[" + ",".join(therm_parts) + "]"
                freqs = stats.get("cpu_core_freq_mhz") or []
                if freqs:
                    debug_str += " Fcore=[" + ",".join(
                        f"{f:.0f}" for f in freqs
                    ) + "]"

            print(f"[{stats['timestamp']}] CPU={stats['cpu_percent']}% "
                  f"MEM={stats['memory_percent']}%{pwr_str}{gpu_str}{net_str}{debug_str}")
        except Exception as e:
            print(f"Error: {e}")
        if watcher is None:
            time.sleep(interval)
        else:
            _sleep_until(time.monotonic() + interval, watcher, stop)
    print(f"Stopping: {stop['why']}")
    print(os.path.abspath(_data_path("metrics")))


# ─── TUI mode (--tui) ───────────────────────────────────────────────────────
# An nvitop-inspired curses dashboard. Screen areas, top to bottom:
#
#   header     host / display name / clock / sampler state / next-sample countdown
#   SYSTEM     CPU + MEM bars, frequency, package temp, and the power rails
#   GPU        one row per GPU: util + memory bars, temps, power, links
#   CPU CORES  only with --cpu-debug: per-sensor temps + per-core frequency
#   HISTORY    sparklines over the ring buffers, one row per series
#   NETWORK    per-interface RX/TX
#   LOG        one line per sample, scrollable
#   footer     key bindings, or a help overlay on '?'
#
# Threading: _Sampler owns collect(), which blocks between 0.5s (cpu_percent)
# and ~10s (nvidia-smi dmon), and hands snapshots over a Queue. The curses
# loop only polls getch() every _TICK_MS and redraws. That split is what
# makes keys respond mid-interval rather than once per sample.
#
# curses rather than hand-rolled ANSI because it owns cbreak/noecho, timed
# getch, resize and colour — exactly the machinery the previous version got
# wrong: it never left canonical mode, so every key needed a newline, and its
# sleep loop only advanced when a key arrived, so it sampled exactly once.

try:
    import curses
except ImportError:      # non-POSIX: daemon mode still imports fine
    curses = None

_TICK_MS  = 100          # getch() timeout — upper bound on key latency
_HIST_CAP = 240          # ring buffer depth (40min at 10s, 8min at 2s)
_SPARK    = "▁▂▃▄▅▆▇█"


class _RingBuf:
    """Fixed-capacity series of floats. None is kept as a real gap."""
    __slots__ = ("cap", "_d")

    def __init__(self, cap=_HIST_CAP):
        self.cap = cap
        self._d = collections.deque(maxlen=cap)

    def append(self, v): self._d.append(v)
    def values(self):    return list(self._d)
    def __len__(self):   return len(self._d)

    def last(self):
        """Newest non-None value, or None. Skipping gaps keeps the readout
        stable when one query errors on an otherwise healthy machine."""
        for v in reversed(self._d):
            if v is not None:
                return v
        return None


def _sparkline(buf, width, lo=None, hi=None):
    """Sparkline of the last `width` samples, oldest → newest.

    `lo`/`hi` pin the scale; either may be None to autoscale that end. Pinning
    matters: autoscaling both ends of a percentage series magnifies its own
    noise, so an idle box drifting between 9.8% and 9.9% memory renders as a
    full-height mountain range. Percentages therefore get a fixed 0-100 and
    rates get a fixed floor of 0.

    A flat series renders as the lowest block rather than blank, so "idle" and
    "no data" stay distinguishable. Gaps (None) render as spaces.

    Padding goes on the right, so a short history grows left-to-right instead
    of clinging to the right edge — at a 10s interval a 110-wide row otherwise
    takes 18 minutes to look like anything but a blank line."""
    if not isinstance(buf, _RingBuf) or width <= 0:
        return " " * max(0, width)
    vals = buf.values()[-width:]
    finite = [v for v in vals if v is not None]
    if not finite:
        return " " * width
    lo = min(finite) if lo is None else lo
    hi = max(finite) if hi is None else hi
    if hi - lo < 1e-9:
        hi = lo + 1.0
    out = []
    for v in vals:
        if v is None:
            out.append(" ")
            continue
        idx = int((v - lo) / (hi - lo) * (len(_SPARK) - 1) + 0.5)
        out.append(_SPARK[max(0, min(len(_SPARK) - 1, idx))])
    return "".join(out) + " " * (width - len(out))


def _display_path(path):
    """Shortest unambiguous form of a path for the UI.

    Relative when it is genuinely below the cwd, absolute otherwise: a relpath
    computed from an unrelated directory yields '../../../../../../tmp/...',
    which is worse than the absolute path at answering "where is my file"."""
    try:
        rel = os.path.relpath(path)
    except ValueError:              # different drive on Windows
        return path
    return rel if not rel.startswith("..") else os.path.abspath(path)


def _hist_window(total, budget, scroll):
    """Clamp a scroll offset to a list. Returns (offset, visible_count).

    Clamping lives here rather than in the key handler because only the draw
    knows how many rows survived the terminal's height, and the offset must
    stay valid when a resize shrinks the window or a series appears."""
    if budget <= 0 or total <= 0:
        return (0, 0)
    off = max(0, min(scroll, max(0, total - budget)))
    return (off, min(budget, total - off))


def _bar(pct, width):
    """Fixed-width bar. Caller picks the colour via _level_attr()."""
    if width <= 0:
        return ""
    pct = 0.0 if pct is None else max(0.0, min(100.0, pct))
    filled = int(pct * width / 100.0 + 0.5)
    return "█" * filled + "░" * (width - filled)


def _gpu_temp(g, pw_entry):
    """GPU temperature in °C, or None.

    The backends disagree on placement: amd-smi merges temp_c into the gpu[]
    entry while nvidia-smi only reports it in the matching gpu_power[] entry,
    so check both rather than branching on vendor."""
    t = g.get("temp_c")
    if t is None:
        t = g.get("temperature")
    return t if t is not None else pw_entry.get("temp_c")


def _fmt_bytes_mb(mb):
    if mb is None: return "  ? "
    if mb >= 1024: return f"{mb / 1024:.1f}G"
    return f"{mb:.0f}M"


def _fmt_freq(mhz):
    if mhz is None: return "?"
    if mhz >= 1000: return f"{mhz / 1000:.2f}GHz"
    return f"{mhz:.0f}MHz"


def _gpu_temp_level(temp, tlimit, tmax=None):
    """Severity of a GPU temperature: 'none', 'ok', 'warn' or 'hot'.

    Three sources, best first:

    1. `tmax` — the absolute throttle point probed from `nvidia-smi -q`
       (gpu_temp_max_c). Judged as headroom against the board's real limit,
       which is the only source that is meaningful across a 92°C data-center
       part and an 87°C laptop alike.
    2. `tlimit` — temperature.gpu.tlimit, which is the *margin* to the limit,
       not a ceiling. Smaller means hotter, so these comparisons run the
       opposite way round. Reading it as a ceiling is what marked an idle GPU
       critical at 48°C against a 39°C margin.
    3. Fixed absolutes, for AMD and anything else reporting neither."""
    if temp is None:
        return "none"
    if tmax:
        if temp >= tmax - 3:  return "hot"
        if temp >= tmax - 12: return "warn"
        return "ok"
    if tlimit is not None:
        if tlimit <= 5:  return "hot"
        if tlimit <= 15: return "warn"
        return "ok"
    if temp >= 85: return "hot"
    if temp >= 70: return "warn"
    return "ok"


def _fmt_rate(mbs):
    """MB/s with a GB/s rollover, padded to a stable width."""
    if mbs is None: return "   —   "
    if abs(mbs) >= 1024: return f"{mbs / 1024:6.2f}G"
    return f"{mbs:6.1f}M"


# ── Sampler thread ──────────────────────────────────────────────────────────

class _Sampler(threading.Thread):
    """Runs collect() off the UI thread and publishes snapshots on a Queue.

    Pausing stops recording but leaves the thread alive; 'r' fires the wake
    Event to collect immediately instead of waiting out the interval."""

    def __init__(self, interval, cpu_debug, enable_nvlink, watcher=None):
        super().__init__(daemon=True)
        self.interval      = interval
        self.cpu_debug     = cpu_debug
        self.enable_nvlink = enable_nvlink
        self.watcher       = watcher
        self.q      = queue.Queue()
        self._wake  = threading.Event()
        self._stop  = threading.Event()
        self._pause = threading.Event()
        self.next_at = time.monotonic()
        self.busy    = False     # a collect() is in flight right now
        self.last_s  = None      # duration of the last collect(), seconds
        self.wrote   = 0         # samples appended to the data file

    def pause(self, on):
        self._pause.set() if on else self._pause.clear()
        if not on:
            self._wake.set()          # resume samples immediately

    @property
    def paused(self):
        return self._pause.is_set()

    def refresh_now(self):
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def run(self):
        while not self._stop.is_set():
            if not self._pause.is_set():
                t0 = time.monotonic()
                self.busy = True
                try:
                    stats = collect(enable_nvlink=self.enable_nvlink,
                                    cpu_debug=self.cpu_debug)
                    # Persist BEFORE the display-only fields are attached, so
                    # the file is byte-identical in shape to raw mode. The
                    # dashboard consumes these files, so a failed write is data
                    # loss and has to reach the user rather than be swallowed.
                    try:
                        append_to_file(stats, "metrics")
                        self.wrote += 1
                    except Exception as e:
                        self.q.put(("error", f"WRITE FAILED {type(e).__name__}: {e}"))
                    # Overall CPU clock is not part of collect()'s JSON
                    # contract, so attach it here for the header row only.
                    try:
                        cf = psutil.cpu_freq()
                        stats["_cpu_freq_mhz"] = cf.current if cf else None
                    except Exception:
                        stats["_cpu_freq_mhz"] = None
                    stats["_collect_s"] = time.monotonic() - t0
                    self.q.put(("sample", stats))
                except Exception as e:
                    self.q.put(("error", f"{type(e).__name__}: {e}"))
                finally:
                    self.busy = False
                    self.last_s = time.monotonic() - t0
            self.next_at = time.monotonic() + self.interval
            # Poll the watched workload on the same slices as the sleep, so a
            # finished job closes the dashboard promptly even at --interval 60.
            deadline = self.next_at
            while not self._stop.is_set():
                if self.watcher is not None:
                    reason = self.watcher.poll()
                    if reason:
                        self.q.put(("done", reason))
                        return
                left = deadline - time.monotonic()
                if left <= 0 or self._wake.wait(min(0.5, left)):
                    break
            self._wake.clear()


# ── State ───────────────────────────────────────────────────────────────────

def _tui_state(cpu_type, cpu_count, display_name, interval):
    hist_keys = ("cpu_pct", "mem_pct", "cpu_temp", "cpu_freq", "cpu_pwr",
                 "sys_pwr", "gpu_pwr_total", "net_rx", "net_tx", "pcie")
    return {
        "cpu_type":   cpu_type,
        "cpu_count":  cpu_count,
        "display_name": display_name,
        "interval":   interval,
        "history":    {k: _RingBuf() for k in hist_keys},
        "gpu_hist":   [],          # list of dicts of _RingBuf, one per GPU
        "log":        collections.deque(maxlen=1000),
        "log_scroll": 0,           # 0 = pinned to newest
        "hist_scroll": 0,          # first visible HISTORY series
        "paused":     False,
        "help":       False,
        "error":      None,
        "samples":    0,
        "have_cpu_debug": False,
        "last":       {},
    }


def _push_sample(st, stats):
    """Fold one snapshot into the ring buffers and the log."""
    st["last"] = stats
    st["samples"] += 1
    h = st["history"]
    h["cpu_pct"].append(stats.get("cpu_percent"))
    h["mem_pct"].append(stats.get("memory_percent"))
    h["cpu_pwr"].append(stats.get("cpu_power_w"))
    h["sys_pwr"].append(stats.get("system_power_w"))
    h["cpu_freq"].append(stats.get("_cpu_freq_mhz"))
    h["cpu_temp"].append(stats.get("cpu_package_temp_c"))

    gpus = stats.get("gpu") or []
    gpwr = stats.get("gpu_power") or []
    while len(st["gpu_hist"]) < max(len(gpus), len(gpwr)):
        st["gpu_hist"].append({k: _RingBuf() for k in
                               ("util", "mem", "pwr", "temp", "pcie", "nvl")})

    pwr_total = 0.0
    have_pwr = False
    link_total = 0.0
    have_link = False
    for i in range(len(st["gpu_hist"])):
        g  = gpus[i] if i < len(gpus) else {}
        pw = gpwr[i] if i < len(gpwr) else {}
        gh = st["gpu_hist"][i]
        gh["util"].append(g.get("utilization"))
        used = g.get("memory_used_mb")
        if used is None:
            used = pw.get("memory_used_mb")
        gh["mem"].append(used)
        p = pw.get("power_w")
        gh["pwr"].append(p)
        if p is not None:
            pwr_total += p
            have_pwr = True
        gh["temp"].append(_gpu_temp(g, pw))
        pcie = None
        if g.get("rxpci_mbs") is not None or g.get("txpci_mbs") is not None:
            pcie = (g.get("rxpci_mbs") or 0) + (g.get("txpci_mbs") or 0)
        elif pw.get("pcie_bandwidth_mbs") is not None:
            pcie = pw["pcie_bandwidth_mbs"]
        gh["pcie"].append(pcie)
        nvl = None
        if g.get("nvlrx_mbs") is not None or g.get("nvltx_mbs") is not None:
            nvl = (g.get("nvlrx_mbs") or 0) + (g.get("nvltx_mbs") or 0)
        gh["nvl"].append(nvl)
        for v in (pcie, nvl):
            if v is not None:
                link_total += v
                have_link = True

    h["gpu_pwr_total"].append(pwr_total if have_pwr else None)
    h["pcie"].append(link_total / 1024.0 if have_link else None)   # GB/s

    nets = stats.get("network") or []
    h["net_rx"].append(sum(n.get("rx_mbs", 0) or 0 for n in nets) if nets else None)
    h["net_tx"].append(sum(n.get("tx_mbs", 0) or 0 for n in nets) if nets else None)

    if stats.get("cpu_debug"):
        st["have_cpu_debug"] = True

    st["log"].append(stats)
    # Pinned to newest (scroll 0) stays pinned; a scrolled-back view holds
    # its position as new lines arrive.
    if st["log_scroll"] > 0:
        st["log_scroll"] = min(st["log_scroll"] + 1, len(st["log"]))


# ── Drawing helpers ─────────────────────────────────────────────────────────

def _colors():
    """Colour attributes, degrading to plain attributes on mono terminals."""
    C = {k: 0 for k in ("dim", "bold", "cyan", "green", "yellow", "red",
                        "magenta", "blue", "rev", "title")}
    C["bold"] = curses.A_BOLD
    C["rev"]  = curses.A_REVERSE
    if not curses.has_colors():
        C["dim"] = curses.A_DIM
        C["title"] = curses.A_BOLD
        return C
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    for i, fg in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN,
                            curses.COLOR_YELLOW, curses.COLOR_RED,
                            curses.COLOR_MAGENTA, curses.COLOR_BLUE,
                            curses.COLOR_WHITE), start=1):
        curses.init_pair(i, fg, bg)
    C["cyan"]    = curses.color_pair(1)
    C["green"]   = curses.color_pair(2)
    C["yellow"]  = curses.color_pair(3)
    C["red"]     = curses.color_pair(4)
    C["magenta"] = curses.color_pair(5)
    C["blue"]    = curses.color_pair(6)
    C["dim"]     = curses.color_pair(7) | curses.A_DIM
    C["title"]   = curses.color_pair(1) | curses.A_BOLD
    return C


def _level_attr(pct, C):
    """htop thresholds: green < 60 <= yellow < 85 <= red."""
    if pct is None: return C["dim"]
    if pct >= 85:   return C["red"]
    if pct >= 60:   return C["yellow"]
    return C["green"]


def _put(scr, y, x, text, attr=0):
    """Clipped write. Swallows the unavoidable error on the last cell."""
    h, w = scr.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w or not text:
        return
    text = text[:w - x]
    try:
        scr.addstr(y, x, text, attr)
    except curses.error:
        pass


def _section(scr, y, w, title, C):
    """A titled rule: `── TITLE ─────────`. Returns the next free row."""
    label = f"─ {title} "
    _put(scr, y, 0, "─" + label + "─" * max(0, w - len(label) - 2), C["title"])
    return y + 1


def _kv(parts, sep="   "):
    return sep.join(p for p in parts if p)


# ── Panels ──────────────────────────────────────────────────────────────────

def _draw_header(scr, st, C, y, w, sampler):
    name = st.get("display_name") or HOSTNAME
    left = f" system-monitor  {HOSTNAME}"
    if name != HOSTNAME:
        left += f" [{name}]"
    if st.get("watch"):
        left += f"  watching {st['watch']}"
    if st["paused"]:
        status, sattr = "❚❚ PAUSED", C["yellow"]
    elif st["error"]:
        status, sattr = "! ERROR", C["red"]
    elif sampler and sampler.busy:
        # collect() can take 7s+ when nvidia-smi dmon is sampling links, and
        # 'r' cannot interrupt one already in flight. Saying so beats looking
        # frozen or ignoring the keypress.
        status, sattr = "◌ sampling", C["cyan"]
    else:
        status, sattr = "● live", C["green"]
    if sampler and sampler.busy:
        countdown = "  now"
    else:
        wait = max(0, sampler.next_at - time.monotonic()) if sampler else 0
        countdown = f"{wait:4.1f}s"
    clock = datetime.now(timezone.utc).strftime("%H:%M:%S") + "Z"
    took  = f"  took {sampler.last_s:.1f}s" if (sampler and sampler.last_s) else ""
    iv, n = st["interval"], st["samples"]
    # Richest-to-poorest right-hand side. At 80 columns the full version does
    # not fit, and a fixed layout drew the status on top of the hostname.
    for right in (f"{clock}  every {iv}s  next {countdown}{took}  n={n} ",
                  f"{clock}  every {iv}s  next {countdown}  n={n} ",
                  f"{clock}  next {countdown}  n={n} ",
                  f"{clock}  n={n} ",
                  f"{clock} "):
        if len(right) + len(status) + 22 <= w:
            break
    _put(scr, y, 0, " " * w, C["rev"])
    sx = w - len(right) - len(status) - 2
    if sx < 2:                       # no room for the status pill at all
        sx, status = w, ""
    _put(scr, y, 0, left[:max(0, sx - 1)], C["rev"] | C["bold"])
    if status:
        _put(scr, y, sx, status, C["rev"] | sattr)
    _put(scr, y, max(0, w - len(right)), right, C["rev"])
    return y + 1


def _draw_system(scr, st, C, y, w):
    last = st["last"]
    y = _section(scr, y, w, "SYSTEM", C)
    bar_w = max(10, min(30, w - 58))
    lbl_w = 22

    cpu_name = (st.get("cpu_type") or "?")
    for junk in ("Intel(R) ", "Core(TM) ", "(R)", "(TM)", " CPU", " Processor"):
        cpu_name = cpu_name.replace(junk, "")
    cores = f"{st.get('cpu_count') or '?'}C"
    lcores = psutil.cpu_count(logical=True)
    if lcores:
        cores += f"/{lcores}T"

    pct = last.get("cpu_percent")
    _put(scr, y, 1, "CPU", C["cyan"] | C["bold"])
    _put(scr, y, 5, f"{cpu_name[:lbl_w]:<{lbl_w}}", C["dim"])
    x = 5 + lbl_w + 1
    _put(scr, y, x, _bar(pct, bar_w), _level_attr(pct, C))
    x += bar_w + 1
    _put(scr, y, x, f"{(pct or 0):5.1f}%", _level_attr(pct, C))
    x += 7
    extra = [cores, _fmt_freq(last.get("_cpu_freq_mhz"))]
    if last.get("cpu_package_temp_c") is not None:
        extra.append(f"{last['cpu_package_temp_c']:.0f}°C")
    _put(scr, y, x, _kv(extra), C["dim"])
    y += 1

    mpct = last.get("memory_percent")
    used, tot = last.get("memory_used_mb"), last.get("memory_total_mb")
    _put(scr, y, 1, "MEM", C["cyan"] | C["bold"])
    _put(scr, y, 5, " " * lbl_w)
    x = 5 + lbl_w + 1
    _put(scr, y, x, _bar(mpct, bar_w), _level_attr(mpct, C))
    x += bar_w + 1
    _put(scr, y, x, f"{(mpct or 0):5.1f}%", _level_attr(mpct, C))
    x += 7
    _put(scr, y, x, f"{_fmt_bytes_mb(used)} / {_fmt_bytes_mb(tot)}", C["dim"])
    y += 1

    # Power rails. Each is independently unavailable (BMC absent, no sudo for
    # RAPL, no GPU), so label what is missing instead of dropping the row --
    # a blank row here is what made the old TUI look broken on laptops.
    sysw, cpuw = last.get("system_power_w"), last.get("cpu_power_w")
    gpuw = st["history"]["gpu_pwr_total"].last()
    _put(scr, y, 1, "PWR", C["cyan"] | C["bold"])
    x = 5
    for label, val, unit, hint in (
            ("system", sysw, "W", "no ipmitool/BMC"),
            ("cpu",    cpuw, "W", "needs sudo RAPL"),
            ("gpu",    gpuw, "W", "no GPU")):
        if val is None:
            _put(scr, y, x, f"{label} —  ({hint})", C["dim"])
            x += len(label) + len(hint) + 8
        else:
            _put(scr, y, x, f"{label} ", C["dim"])
            _put(scr, y, x + len(label) + 1, f"{val:.0f}{unit}", C["magenta"] | C["bold"])
            x += len(label) + 9
    return y + 1


def _draw_gpu(scr, st, C, y, w):
    last = st["last"]
    gpus = last.get("gpu") or []
    gpwr = last.get("gpu_power") or []
    n = max(len(gpus), len(gpwr))
    vendor = (last.get("gpu_vendor") or "").upper()
    # Throttle point goes in the title rather than a per-row column: it is a
    # board constant, identical across the GPUs in a box, and a per-row suffix
    # would push the NVLINK column off an 80-column terminal.
    tmaxs = [t for t in (last.get("gpu_temp_max_c") or []) if t]
    thr = f"  throttle {min(tmaxs):.0f}°C" if tmaxs else ""
    y = _section(scr, y, w, f"GPU  {n}x {last.get('gpu_type') or '—'}"
                            f"{'  (' + vendor + ')' if vendor else ''}{thr}", C)
    if not n:
        _put(scr, y, 2, "no GPU detected — nvidia-smi and amd-smi both unavailable",
             C["dim"])
        return y + 1

    # One source of truth for column x-offsets, so the header cannot drift
    # out of alignment with the rows beneath it.
    ubar = max(6, min(14, (w - 78) // 2))
    mbar = ubar
    col = {"id": 1, "util": 4}
    col["utilpct"] = col["util"] + ubar + 1
    col["mem"]     = col["utilpct"] + 6
    col["memtxt"]  = col["mem"] + mbar + 1
    col["temp"]    = col["memtxt"] + 14
    col["power"]   = col["temp"] + 8
    col["pcie"]    = col["power"] + 13
    col["nvl"]     = col["pcie"] + 11
    col["extra"]   = col["nvl"] + 11
    for label, key in (("ID", "id"), ("UTIL", "util"), ("MEMORY", "mem"),
                       ("TEMP", "temp"), ("POWER", "power"),
                       ("PCIE R+T", "pcie"), ("NVLINK", "nvl")):
        _put(scr, y, col[key], label, C["dim"] | C["bold"])
    y += 1

    for i in range(n):
        g  = gpus[i] if i < len(gpus) else {}
        pw = gpwr[i] if i < len(gpwr) else {}
        gh = st["gpu_hist"][i] if i < len(st["gpu_hist"]) else None
        err = g.get("error") or pw.get("error")
        _put(scr, y, 1, f"{i}", C["cyan"] | C["bold"])
        if err:
            _put(scr, y, 4, f"query failed: {err}"[:w - 5], C["red"])
            y += 1
            continue
        util = g.get("utilization")
        _put(scr, y, col["util"], _bar(util, ubar), _level_attr(util, C))
        _put(scr, y, col["utilpct"], f"{util:4.0f}%" if util is not None else "   — ",
             _level_attr(util, C))

        used, tot = g.get("memory_used_mb"), g.get("memory_total_mb")
        if used is None: used = pw.get("memory_used_mb")
        if tot is None:  tot  = pw.get("memory_total_mb")
        mpct = (used / tot * 100.0) if (used is not None and tot) else g.get("memory_percent")
        _put(scr, y, col["mem"], _bar(mpct, mbar), _level_attr(mpct, C))
        _put(scr, y, col["memtxt"], f"{_fmt_bytes_mb(used):>5}/{_fmt_bytes_mb(tot):<5}",
             C["dim"])

        temp = _gpu_temp(g, pw)
        tmaxs = st["last"].get("gpu_temp_max_c") or []
        tmax = tmaxs[i] if i < len(tmaxs) else None
        tattr = {"none": C["dim"], "ok": C["green"],
                 "warn": C["yellow"], "hot": C["red"]}[
            _gpu_temp_level(temp, pw.get("temp_limit"), tmax)]
        _put(scr, y, col["temp"], f"{temp:4.0f}°C" if temp is not None else "   —  ", tattr)

        p, lim = pw.get("power_w"), pw.get("power_limit_w")
        if p is None:
            _put(scr, y, col["power"], "    —   ", C["dim"])
        else:
            ppct = (p / lim * 100.0) if lim else None
            _put(scr, y, col["power"], f"{p:4.0f}", _level_attr(ppct, C))
            _put(scr, y, col["power"] + 4, f"/{lim:.0f}W" if lim else "W", C["dim"])

        for key in ("pcie", "nvl"):
            v = gh[key].last() if gh else None
            _put(scr, y, col[key if key == "pcie" else "nvl"],
                 f"{_fmt_rate(v)}B/s" if v is not None else "    —  ",
                 C["blue"] if v else C["dim"])
        # Memory-junction temp is AMD-only; append it rather than giving it a
        # column that would sit empty on every NVIDIA box.
        if pw.get("mem_temp_c") is not None:
            _put(scr, y, col["extra"], f"mem {pw['mem_temp_c']:.0f}°C", C["dim"])
        y += 1
    return y


def _draw_cpu_debug(scr, st, C, y, w):
    last = st["last"]
    therms = [t for t in (last.get("cpu_therm_temp_c") or []) if t is not None]
    freqs  = [f for f in (last.get("cpu_core_freq_mhz") or []) if f]
    if not therms and not freqs:
        return y
    y = _section(scr, y, w, "CPU CORES  (--cpu-debug)", C)
    if therms:
        hot = max(therms)
        _put(scr, y, 1, f"temp   {len(therms)} sensors", C["dim"])
        _put(scr, y, 24, f"min {min(therms):5.1f}   avg "
                         f"{sum(therms) / len(therms):5.1f}   max ", C["dim"])
        _put(scr, y, 24 + 36, f"{hot:5.1f}°C",
             C["red"] if hot >= 85 else C["yellow"] if hot >= 70 else C["green"])
        y += 1
    if freqs:
        _put(scr, y, 1, f"clock  {len(freqs)} cores", C["dim"])
        _put(scr, y, 24, f"min {min(freqs):5.0f}   avg "
                         f"{sum(freqs) / len(freqs):5.0f}   max "
                         f"{max(freqs):5.0f} MHz", C["dim"])
        y += 1
    return y


def _draw_history(scr, st, C, y, w, budget):
    """Sparkline rows, scrollable with ↑/↓. `budget` includes the title.

    A box with 8 GPUs has 4 series each plus the system ones — well over 30
    rows, so on any normal terminal most of them are off-screen and need to be
    reachable rather than merely counted."""
    if budget < 2:
        return y
    title_y = y
    y += 1
    budget -= 1
    # Keep the time-axis row when there is space for it; it applies to every
    # series, so it stays pinned at the bottom rather than scrolling away.
    axis = budget >= 3
    series_budget = budget - (1 if axis else 0)
    # Value column sits between the label and the sparkline: reading the
    # current number off the far right edge, a hundred columns from its label,
    # is what made the old layout feel unreadable.
    lbl_w, val_w = 11, 8
    spark_w = max(8, w - lbl_w - val_w - 4)

    # (label, buffer, formatter, colour, scale) where scale is (lo, hi) and
    # None means autoscale that end.
    PCT, FROM_0 = (0.0, 100.0), (0.0, None)
    rows = [("CPU %",   st["history"]["cpu_pct"],  lambda v: f"{v:6.1f}%", C["green"], PCT),
            ("MEM %",   st["history"]["mem_pct"],  lambda v: f"{v:6.1f}%", C["green"], PCT)]
    for i, gh in enumerate(st["gpu_hist"]):
        rows.append((f"GPU{i} util", gh["util"], lambda v: f"{v:6.0f}%", C["cyan"], PCT))
        rows.append((f"GPU{i} mem",  gh["mem"],  lambda v: f"{_fmt_bytes_mb(v):>7}", C["cyan"], FROM_0))
        rows.append((f"GPU{i} temp", gh["temp"], lambda v: f"{v:5.0f}°C", C["yellow"], (20.0, 100.0)))
        rows.append((f"GPU{i} pwr",  gh["pwr"],  lambda v: f"{v:6.0f}W", C["magenta"], FROM_0))
    rows += [("net rx",  st["history"]["net_rx"], lambda v: f"{v:6.1f}M", C["blue"], FROM_0),
             ("net tx",  st["history"]["net_tx"], lambda v: f"{v:6.1f}M", C["blue"], FROM_0),
             ("pcie+nvl", st["history"]["pcie"],  lambda v: f"{v:5.2f}G", C["blue"], FROM_0),
             ("cpu temp", st["history"]["cpu_temp"], lambda v: f"{v:5.0f}°C", C["yellow"], (20.0, 100.0)),
             ("cpu clk", st["history"]["cpu_freq"], lambda v: f"{v:5.0f}M", C["green"], FROM_0),
             ("cpu pwr", st["history"]["cpu_pwr"], lambda v: f"{v:6.0f}W", C["magenta"], FROM_0),
             ("sys pwr", st["history"]["sys_pwr"], lambda v: f"{v:6.0f}W", C["magenta"], FROM_0)]

    # Drop series that have never produced a reading, so a laptop without a
    # BMC does not show three permanently blank rows.
    rows = [r for r in rows if r[1].last() is not None]
    off, count = _hist_window(len(rows), series_budget, st["hist_scroll"])
    st["hist_scroll"] = off              # write the clamped value back
    for label, buf, fmt, attr, scale in rows[off:off + count]:
        v = buf.last()
        _put(scr, y, 1, f"{label:<{lbl_w - 1}}", C["dim"])
        _put(scr, y, lbl_w, f"{fmt(v) if v is not None else '     —':>{val_w}}",
             attr | C["bold"])
        _put(scr, y, lbl_w + val_w + 1,
             _sparkline(buf, spark_w, lo=scale[0], hi=scale[1]), attr)
        y += 1

    # Title carries the scroll position, so hidden series are discoverable
    # rather than just tallied.
    title = "HISTORY"
    if count < len(rows):
        title += f"  {off + 1}-{off + count} of {len(rows)}  ↑↓"
        if off:
            title += "  ▲"
        if off + count < len(rows):
            title += "  ▼"
    _section(scr, title_y, w, title, C)

    if axis and rows:
        # Time axis: how much wall-clock the filled part of a row covers. Uses
        # cpu_pct because it is appended every sample, unlike the series that
        # happen to be scrolled into view.
        n = min(len(st["history"]["cpu_pct"]), spark_w)
        span = max(0, n - 1) * st["interval"]
        label = (f"{span // 60}m{span % 60:02d}s" if span >= 60 else f"{span}s")
        _put(scr, y, 1, "window", C["dim"])
        _put(scr, y, lbl_w, f"{label:>{val_w}}", C["dim"])
        _put(scr, y, lbl_w + val_w + 1,
             "└" + "─" * max(0, min(n, spark_w) - 2) + "┘", C["dim"])
        y += 1
    return y


def _draw_network(scr, st, C, y, w, budget):
    nets = st["last"].get("network") or []
    if not nets or budget < 2:
        return y
    y = _section(scr, y, w, "NETWORK", C)
    for n in nets[:budget - 1]:
        _put(scr, y, 1, f"{n.get('name', '?')[:12]:<12}", C["cyan"])
        _put(scr, y, 14, f"rx {_fmt_rate(n.get('rx_mbs'))}B/s", C["blue"])
        _put(scr, y, 14 + 20, f"tx {_fmt_rate(n.get('tx_mbs'))}B/s", C["blue"])
        y += 1
    return y


def _draw_log(scr, st, C, y, w, budget):
    if budget < 2:
        return y
    scroll = st["log_scroll"]
    title = "LOG"
    # Name the file being appended to. The TUI used to display only, and "where
    # is my JSON?" is the obvious question when it is the file you upload.
    if st.get("outfile"):
        title += f"  → {st['outfile']}  ({st.get('wrote', 0)} written)"
    if scroll:
        title += f"  ↑{scroll} back  (g = newest)"
    y = _section(scr, y, w, title, C)
    budget -= 1
    log = list(st["log"])
    if not log:
        _put(scr, y, 2, "waiting for the first sample…", C["dim"])
        return y + 1
    end = len(log) - scroll
    start = max(0, end - budget)
    for s in log[start:max(start, end)]:
        ts = (s.get("timestamp") or "")[11:19]
        bits = [f"cpu {(s.get('cpu_percent') or 0):5.1f}%",
                f"mem {(s.get('memory_percent') or 0):5.1f}%"]
        gpus = s.get("gpu") or []
        gpwr = s.get("gpu_power") or []
        if gpus:
            u = gpus[0].get("utilization")
            bits.append(f"gpu0 {u:4.0f}%" if u is not None else "gpu0    —")
            t = _gpu_temp(gpus[0], gpwr[0] if gpwr else {})
            if t is not None:
                bits.append(f"{t:3.0f}°C")
        if gpwr and gpwr[0].get("power_w") is not None:
            bits.append(f"{gpwr[0]['power_w']:5.1f}W")
        if s.get("system_power_w") is not None:
            bits.append(f"sys {s['system_power_w']:.0f}W")
        d = s.get("_collect_s")
        if d is not None:
            bits.append(f"({d:.1f}s)")
        _put(scr, y, 1, ts, C["dim"])
        _put(scr, y, 10, "  ".join(bits)[:max(0, w - 11)], C["dim"])
        y += 1
    return y


_HELP = [
    ("q",           "quit"),
    ("space",       "pause / resume sampling"),
    ("r",           "sample now, without waiting out the interval"),
    ("↑ ↓  k j",    "scroll the HISTORY series"),
    ("Home",        "back to the first HISTORY series"),
    ("PgUp PgDn",   "scroll the LOG one page"),
    ("g",           "reset both: newest log, first series"),
    ("?  h",        "toggle this help"),
]


def _draw_help(scr, C):
    h, w = scr.getmaxyx()
    bh, bw = len(_HELP) + 4, 52
    top, left = max(0, (h - bh) // 2), max(0, (w - bw) // 2)
    for i in range(bh):
        _put(scr, top + i, left, " " * bw, C["rev"])
    _put(scr, top + 1, left + 2, "keys", C["rev"] | C["bold"])
    for i, (k, desc) in enumerate(_HELP):
        _put(scr, top + 2 + i, left + 2, f"{k:<12}", C["rev"] | C["bold"])
        _put(scr, top + 2 + i, left + 15, desc, C["rev"])
    _put(scr, top + bh - 1, left + 2, "any key closes", C["rev"] | C["dim"])


def _draw_footer(scr, st, C, y, w, sampler):
    keys = ("q quit   space pause   r refresh   ↑↓ history   PgUp/PgDn log   "
            "g reset   ? help")
    _put(scr, y, 0, " " * w, C["rev"])
    _put(scr, y, 1, keys[:max(0, w - 2)], C["rev"])
    if st["error"]:
        msg = f" {st['error']} "[:max(0, w - 2)]
        _put(scr, y, max(1, w - len(msg) - 1), msg, C["rev"] | C["red"])


def _layout_sig(st, h, w):
    """Repaint key: everything that moves rows wholesale, ignoring values.

    Two things do that. Panels appear and disappear as data arrives — the very
    first sample has network=[] because throughput needs two readings, so
    NETWORK pops in on sample two and shifts everything below it down three
    rows. And scrolling either pane slides a block by a line.

    Both are exactly the case ncurses optimises with insert/delete-line, and a
    differential update across a shifted frame is what left duplicated HISTORY
    rows on screen (window '2-7 of 9' rendering 'net tx' twice). A changed key
    forces a clean repaint, which costs one full frame per keypress."""
    return (h, w, len(st["gpu_hist"]), len(st["last"].get("network") or []),
            bool(st["last"].get("cpu_therm_temp_c") or st["last"].get("cpu_core_freq_mhz")),
            st["help"], st["hist_scroll"], st["log_scroll"])


def _tui_draw(scr, st, C, sampler):
    h, w = scr.getmaxyx()
    sig = _layout_sig(st, h, w)
    if sig != st.get("_sig"):
        st["_sig"] = sig
        scr.clearok(True)
    scr.erase()
    if h < 8 or w < 50:
        _put(scr, 0, 0, f"terminal too small ({w}x{h}); need 50x8", C["yellow"])
        scr.noutrefresh()
        curses.doupdate()
        return
    y = _draw_header(scr, st, C, 0, w, sampler)
    y = _draw_system(scr, st, C, y, w)
    y = _draw_gpu(scr, st, C, y, w)
    y = _draw_cpu_debug(scr, st, C, y, w)
    y = _draw_network(scr, st, C, y, w, budget=h - 1 - y - 4)
    # Whatever is left splits between HISTORY and LOG, history first but
    # never starving the log of its 3 rows.
    free = max(0, h - 1 - y)
    log_rows = min(max(3, free // 3), free)
    y = _draw_history(scr, st, C, y, w, budget=free - log_rows)
    _draw_log(scr, st, C, y, w, budget=h - 1 - y)
    _draw_footer(scr, st, C, h - 1, w, sampler)
    if st["help"]:
        _draw_help(scr, C)
    scr.noutrefresh()
    curses.doupdate()


# ── Main loop ───────────────────────────────────────────────────────────────

# CSI/SS3 tails for the keys we care about, for terminals whose arrows curses
# does not translate (see _read_key).
_ESC_KEYS = {"[A": "KEY_UP",    "OA": "KEY_UP",
             "[B": "KEY_DOWN",  "OB": "KEY_DOWN",
             "[5~": "KEY_PPAGE", "[6~": "KEY_NPAGE",
             "[H": "KEY_HOME",  "OH": "KEY_HOME", "[1~": "KEY_HOME"}


def _read_key(scr):
    """getch() with escape-sequence fallback. Returns a key code or -1.

    keypad(True) makes curses translate the terminfo arrow sequences, but a
    terminal that sends CSI arrows (\\033[A) while curses expects SS3 (\\033OA)
    delivers a bare ESC followed by the tail. Draining it here matters because
    the obvious reading of a lone ESC — quit — would make a stray arrow key
    kill the dashboard."""
    ch = scr.getch()
    if ch != 27:
        return ch
    scr.nodelay(True)
    try:
        seq = ""
        for _ in range(4):
            c = scr.getch()
            if c == -1:
                break
            seq += chr(c)
            if seq in _ESC_KEYS:
                return getattr(curses, _ESC_KEYS[seq])
    finally:
        scr.nodelay(False)
        scr.timeout(_TICK_MS)
    return -1       # lone ESC or an unknown sequence: ignore it


def _tui_main(scr, interval, display_name, cpu_debug, watcher=None):
    curses.curs_set(0)
    scr.nodelay(False)
    scr.timeout(_TICK_MS)      # getch() returns -1 after _TICK_MS
    scr.keypad(True)
    C = _colors()

    st = _tui_state(CPU_TYPE, CPU_COUNT, display_name, interval)
    st["watch"] = watcher.pattern if watcher else None
    # dmon needs ~4s of sampling to report link counters, so the daemon gates
    # it on interval >= 10s. The TUI is watched live, so honour the same gate.
    sampler = _Sampler(interval, cpu_debug, enable_nvlink=(interval >= 10),
                       watcher=watcher)
    sampler.start()
    try:
        while True:
            drained = False
            while True:
                try:
                    kind, payload = sampler.q.get_nowait()
                except queue.Empty:
                    break
                drained = True
                if kind == "sample":
                    st["error"] = None
                    _push_sample(st, payload)
                    st["outfile"] = _display_path(_data_path("metrics"))
                    st["wrote"] = sampler.wrote
                elif kind == "done":
                    return payload          # watched workload finished
                else:
                    st["error"] = payload
            _tui_draw(scr, st, C, sampler)

            ch = _read_key(scr)
            if ch == -1:
                continue
            if st["help"]:
                st["help"] = False
                continue
            page = max(1, (scr.getmaxyx()[0] - 12))
            if ch in (ord("q"), ord("Q")):
                return
            if ch == ord(" "):
                st["paused"] = not st["paused"]
                sampler.pause(st["paused"])
            elif ch in (ord("r"), ord("R")):
                sampler.refresh_now()
            elif ch in (ord("?"), ord("h"), ord("H")):
                st["help"] = True
            # ↑↓ walk the HISTORY series; PgUp/PgDn walk the LOG. The draw
            # clamps hist_scroll, since only it knows how many rows fit.
            elif ch in (curses.KEY_UP, ord("k")):
                st["hist_scroll"] = max(0, st["hist_scroll"] - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                st["hist_scroll"] += 1
            elif ch == curses.KEY_HOME:
                st["hist_scroll"] = 0
            elif ch == curses.KEY_PPAGE:
                st["log_scroll"] = min(st["log_scroll"] + page, max(0, len(st["log"]) - 1))
            elif ch == curses.KEY_NPAGE:
                st["log_scroll"] = max(0, st["log_scroll"] - page)
            elif ch in (ord("g"), ord("G")):
                st["log_scroll"] = 0
                st["hist_scroll"] = 0
            elif ch == curses.KEY_RESIZE:
                scr.erase()
    finally:
        sampler.stop()


def tui(interval=2, _display_name=None, cpu_debug=False, watch=None,
        linger_s=10.0):
    """Interactive nvitop-style dashboard. Appends the same JSON as raw mode."""
    global display_name
    display_name = _display_name
    if curses is None:
        print("TUI mode needs the curses module (POSIX only).", file=sys.stderr)
        sys.exit(1)
    if not sys.stdout.isatty():
        print("TUI mode requires a TTY. Re-run from a real terminal.", file=sys.stderr)
        sys.exit(1)
    # Box-drawing and block glyphs need the terminal's real encoding; without
    # this curses renders them as '?' under the default C locale.
    try:
        import locale
        locale.setlocale(locale.LC_ALL, "")
    except Exception:
        pass
    watcher = _Watcher(watch, linger_s=linger_s) if watch else None
    reason = curses.wrapper(_tui_main, interval, _display_name, cpu_debug,
                            watcher)
    # Printed after curses has restored the terminal, so it survives on screen.
    if reason:
        print(reason)
    print(os.path.abspath(_data_path("metrics")))


# ─── Entry point ────────────────────────────────────────────────────────────

def _pick_mode(want_tui, want_raw, want_silent, is_tty):
    """Choose 'tui', 'raw' or 'silent'. Raises ValueError on a conflict.

    The dashboard is the default, but it needs a terminal. A missing TTY falls
    back to raw rather than exiting, because the systemd unit has no TTY and
    Restart=always would turn an exit(1) into a silent five-second crash loop
    that collects nothing. An explicit --tui still errors on no TTY, since
    there the user asked for something impossible rather than just running the
    default in a pipe."""
    chosen = [n for n, want in (("tui", want_tui), ("raw", want_raw),
                                ("silent", want_silent)) if want]
    if len(chosen) > 1:
        raise ValueError("--" + ", --".join(chosen) + " are mutually exclusive")
    if chosen:
        return chosen[0]
    return "tui" if is_tty else "raw"


_USAGE = """Usage:
  python3 collector.py <interval> <display_name> [mode] [options]

  <interval>      polling interval in seconds (10 for unattended runs, 1-5 live)
  <display_name>  machine identifier, used in the JSON filename and the
                  dashboard (e.g. XE9785L_MI355X)

Modes (mutually exclusive; all write the same JSON to data/):
  (default)       full-screen dashboard
  --raw           line-per-sample logging to stdout. Used by the systemd unit.
  --silent        no output while running; prints the data file path at the end.
                  Meant to be backgrounded next to a benchmark.
  --tui           force the dashboard; fails if there is no TTY

Options:
  --watch NAME    stop collecting once no process matches NAME, waiting 10s
                  first so the cooldown is captured. NAME is matched against
                  process names and command lines, case-insensitively. Gives up
                  if nothing matches within 60s of starting.
  --linger SECS   override that 10s grace period
  --cpu-debug     also record per-core CPU temperature and frequency

Every mode writes data/metrics_<display_name>_<UTC date>.json. Without a TTY
the dashboard is skipped automatically, so cron and systemd still collect.

  # collect quietly for as long as the benchmark runs, then print the path
  python3 collector.py 10 XE7740_H200 --silent --watch run_mlperf.sh"""

if __name__ == "__main__":
    args = sys.argv[1:]
    cpu_debug = "--cpu-debug" in args
    while "--cpu-debug" in args:
        args.remove("--cpu-debug")

    def _take_value(flag):
        """Pull `--flag VALUE` out of args, returning VALUE or None."""
        if flag not in args:
            return None
        i = args.index(flag)
        if i + 1 >= len(args):
            print(f"{flag} needs a value\n", file=sys.stderr)
            print(_USAGE)
            sys.exit(1)
        val = args[i + 1]
        del args[i:i + 2]
        return val

    watch = _take_value("--watch")
    linger_raw = _take_value("--linger")
    linger_s = 10.0
    if linger_raw is not None:
        try:
            linger_s = float(linger_raw)
        except ValueError:
            print(f"--linger needs a number of seconds, got {linger_raw!r}",
                  file=sys.stderr)
            sys.exit(1)

    flags = {}
    for flag in ("--tui", "--raw", "--silent"):
        flags[flag] = flag in args
        while flag in args:
            args.remove(flag)

    unknown = [a for a in args if a.startswith("-")]
    if len(args) < 2 or unknown:
        if unknown:
            print(f"unknown option: {unknown[0]}\n", file=sys.stderr)
        print(_USAGE)
        sys.exit(1)
    try:
        interval = int(args[0])
    except ValueError:
        print(f"interval must be a whole number of seconds, got {args[0]!r}\n",
              file=sys.stderr)
        print(_USAGE)
        sys.exit(1)
    _display_name = args[1]
    try:
        mode = _pick_mode(flags["--tui"], flags["--raw"], flags["--silent"],
                          sys.stdout.isatty())
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    if mode == "silent":
        # _probe_gpu() chatters on stdout, and silent mode promises stdout is
        # nothing but the data path so it can be used as
        #   f=$(collector.py 10 X --silent --watch job)
        with open(os.devnull, "w") as _null, contextlib.redirect_stdout(_null):
            _probe_gpu()
    else:
        _probe_gpu()
    if mode == "tui":
        tui(interval, _display_name, cpu_debug=cpu_debug, watch=watch,
            linger_s=linger_s)
    elif mode == "silent":
        silent(interval, _display_name, cpu_debug=cpu_debug, watch=watch,
               linger_s=linger_s)
    else:
        if not (flags["--raw"] or sys.stdout.isatty()):
            print("no TTY — logging to stdout instead of the dashboard "
                  "(pass --raw to make this explicit)", file=sys.stderr)
        daemon(interval, _display_name, cpu_debug=cpu_debug, watch=watch,
               linger_s=linger_s)

