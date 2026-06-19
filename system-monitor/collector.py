#!/usr/bin/env python3
"""
System metrics collector: CPU, GPU (up to 8), memory, GPU power, network.
Runs as daemon, writes JSON Lines.

Supports NVIDIA (nvidia-smi) and AMD (amd-smi CLI) GPUs.
No extra Python packages required.
"""

import json
import os
import re
import shutil
import collections
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psutil

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

def _probe_nvidia():
    global GPU_COUNT, GPU_TYPE
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True, timeout=5
        )
        raw = result.stdout.strip().split("\n")[0].strip()
        GPU_TYPE = raw[7:].strip().replace(" ", "_") if raw.startswith("NVIDIA ") else raw.replace(" ", "_")
        GPU_COUNT = min(8, len([n for n in result.stdout.strip().split("\n") if n.strip()]))
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
            "utilization": float(util),
            "memory_used_mb": float(mem_used),
            "memory_total_mb": float(mem_total)
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
            "power_w": float(power_draw),
            "power_limit_w": float(power_limit),
            "temp_c": float(temp_c),
            "temp_limit": float(temp_limit)
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


# ─── Daemon ─────────────────────────────────────────────────────────────────

def append_to_file(data, period):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    # Use display_name if set (distinguishes machines with same hostname but different GPU types)
    name = display_name if display_name else data.get("hostname", HOSTNAME)
    path = os.path.join(DATA_DIR, f"{period}_{name}_{ts}.json")
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


def daemon(interval=10, _display_name=None, cpu_debug=False):
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
    while True:
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
        time.sleep(interval)


# ─── TUI mode (--tui) ───────────────────────────────────────────────────────
# Mirrors the Syllo/nvtop look-and-feel: bars + per-GPU rows + footer.
# Pure ANSI escape sequences — no curses/blessed dependency. Activated by
# `--tui <interval> <display_name>` instead of the daemon's positional args.
#
# Layout (≈80×24 terminal):
#   ╭─ <hostname> ───────────── <utc-time> ───── <interval>s ─╮
#   │  CPU  <type> <Nc/Nt>  <bar> <pct>% <freq>             │
#   │  MEM  <type> <total>   <bar> <pct>% <used>/<total>    │
#   │  SYS  <total>W  CPU=…W  GPU0=…W  …                    │
#   │  GPU<i> <name>  <bar> <pct>% <temp>°C <freq> <pwr>/<lim>│
#   │  NET  <iface> RX=… TX=…                                │
#   │  q: quit  space: pause  r: refresh  ?: help             │
#   ╰──────────────────────────────────────────────────────────╯
#
# See DESIGN-tui.md for the design rationale and edge-case handling.

# Low-level ANSI helpers. Each writes directly to stdout and flushes so
# the render feels "live" even on slower shells.
def _ansi(code): return f"\033[{code}m"

def _term_write(s):
    sys.stdout.write(s); sys.stdout.flush()

def _alt_screen_on():  _term_write("\033[?1049h")   # switch to alt buffer
def _alt_screen_off(): _term_write("\033[?1049l")   # back to main buffer
def _hide_cursor():    _term_write("\033[?25l")
def _show_cursor():    _term_write("\033[?25h")
def _clear_screen():   _term_write("\033[2J\033[H")

def _bar(pct, width=20):
    """Return a coloured bar string of fixed character width.

    Green <60%, yellow 60–85%, red ≥85% — same thresholds as htop."""
    pct = max(0.0, min(100.0, pct or 0.0))
    filled = int(round(pct * width / 100.0))
    color = "31" if pct >= 85 else "33" if pct >= 60 else "32"
    fill_ch  = "█"
    empty_ch = "░"
    return (f"\033[{color}m{fill_ch * filled}"
            f"\033[37m{empty_ch * (width - filled)}\033[0m")

def _fmt_bytes_mb(mb):
    if mb is None: return "?"
    if mb >= 1024:  return f"{mb/1024:.1f}G"
    return f"{mb:.0f}M"

def _fmt_freq(mhz):
    if mhz is None: return "?"
    if mhz >= 1000: return f"{mhz/1000:.1f}GHz"
    return f"{mhz:.0f}MHz"

def _read_key_nonblocking(timeout=0.0):
    """Best-effort single keypress read. Returns '' on no-input / unavailable.

    Uses select() on stdin (POSIX) — falls back to '' on non-POSIX so the
    TUI still works on Windows for development, just without key handling."""
    if not sys.stdin or not sys.stdin.isatty(): return ''
    try:
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r: return ''
        ch = sys.stdin.read(1)
        # Consume any trailing bytes for escape sequences (arrow keys etc.)
        if ch == '\x1b':
            r2, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r2: sys.stdin.read(2)
        return ch
    except Exception:
        return ''

def _tui_render(state, interval, error=None):
    """Build one frame of the 3-layer TUI and write it to stdout.

    Layout adapts to terminal size:
      L1 (top stat strip)  : 4-8 rows, current snapshot with bars
      L2 (sparkline grid)  : 1 row per metric, scrolls history
      L3 (log strip)       : 3-8 rows, scrollable event log

    Cursor-home (\\033[H) at start, clear-to-end (\\033[J) at end so a
    shorter frame than the previous one cleans up neatly."""
    # Resolve terminal size — honour COLUMNS/LINES env vars as fallback so
    # `script -T xterm COLUMNS=120` works in CI / captured-output scenarios.
    cols, rows = shutil.get_terminal_size((120, 32))
    try:
        env_cols = int(os.environ.get("COLUMNS", "")) if os.environ.get("COLUMNS") else None
        env_rows = int(os.environ.get("LINES",   "")) if os.environ.get("LINES")   else None
        if env_cols: cols = env_cols
        if env_rows: rows = env_rows
    except (ValueError, TypeError):
        pass

    # Allocate rows to each layer. Footer is 1 row, 2 separators = 2 rows.
    log_rows = min(8, max(3, rows // 5))
    top_rows = min(8, max(4, (rows - log_rows) // 4))
    spark_rows = max(2, rows - top_rows - log_rows - 3)   # 3 = 2 separators + footer
    # Sparkline width is whatever's left after the label and value column.
    # Layout: "  LABEL<10>  SPARK_W  CURRENT>20"
    label_w = 12
    value_w = 22
    spark_w = max(8, cols - 2 - label_w - 2 - value_w)

    out = []
    out += _render_top_strip(state, top_rows, cols)
    out.append(_tui_separator(cols, "─"))
    out += _render_sparkline_grid(state, spark_rows, spark_w, cols,
                                  label_w=label_w, value_w=value_w, interval=interval)
    out.append(_tui_separator(cols, "─"))
    out += _render_log_strip(state, log_rows, cols)
    out.append(_render_footer(state, cols, error))
    sys.stdout.write("\033[H" + "\n".join(out) + "\n\033[J")
    sys.stdout.flush()


def _render_top_strip(state, max_rows, cols):
    """L1: current snapshot per metric, like webpage stat cards.

    Returns a list of row strings. Adapts to max_rows: skips lower-priority
    rows when the terminal is short."""
    accent = "\033[36m"   # cyan
    dim    = "\033[90m"
    bold   = "\033[1m"
    rst    = "\033[0m"
    rows = []

    cpu_name = state.get("cpu_type") or "?"
    cpu_name = cpu_name.replace("Intel(R) Core(TM) ", "").replace("CPU ", "")
    cpu_name = cpu_name.replace("AMD ", "").replace("Ryzen ", "R")
    cpu_pct = state.get("last", {}).get("cpu_percent") or 0
    cpu_freq = state.get("last", {}).get("cpu_freq_str", "?")
    rows.append(f"{accent}│{rst}  CPU  {cpu_name:<22} {_bar(cpu_pct)} {cpu_pct:5.1f}%  {cpu_freq}")

    mem_pct = state.get("last", {}).get("memory_percent") or 0
    mem_used = _fmt_bytes_mb(state.get("last", {}).get("memory_used_mb"))
    mem_tot = _fmt_bytes_mb(state.get("last", {}).get("memory_total_mb"))
    rows.append(f"{accent}│{rst}  MEM  {'':22} {_bar(mem_pct)} {mem_pct:5.1f}%  {mem_used}/{mem_tot}")

    sys_w   = state.get("last", {}).get("system_power_w")
    cpu_w   = state.get("last", {}).get("cpu_power_w")
    if sys_w is not None or cpu_w is not None:
        parts = []
        if sys_w is not None: parts.append(f"{sys_w:.0f}W")
        if cpu_w is not None: parts.append(f"CPU={cpu_w:.0f}W")
        rows.append(f"{accent}│{rst}  SYS  {' '.join(parts)}")

    # One row per GPU — pack into 2 columns if there are many and rows allow.
    gpus = state.get("last", {}).get("gpu") or []
    gpwr = state.get("last", {}).get("gpu_power") or []
    if gpus:
        col_width = (cols - 4) // 2
        per_row = 2
        for i in range(0, len(gpus), per_row):
            row_parts = [f"{accent}│{rst}  "]
            for j in range(per_row):
                idx = i + j
                if idx >= len(gpus): break
                g = gpus[idx]; pw_entry = gpwr[idx] if idx < len(gpwr) else {}
                name = (g.get("name") or f"GPU{idx}").replace("NVIDIA ", "").replace("AMD ", "")
                util = g.get("utilization")
                if util is None and pw_entry.get("power_limit_w"):
                    util = (pw_entry.get("power_w") or 0) / pw_entry["power_limit_w"] * 100
                temp = g.get("temperature_c")
                temp_s = f"{temp:.0f}°C" if temp is not None else "?"
                pw = pw_entry.get("power_w")
                row_parts.append(
                    f"GPU{idx} {name[:14]:<14} {_bar(util)} {util or 0:4.0f}%  {temp_s}  "
                    f"{pw:.0f}W" if pw is not None else f"GPU{idx} {name[:14]:<14} {_bar(util)} {util or 0:4.0f}%  {temp_s}  ?W"
                )
            rows.append((" " * 4).join(row_parts[:per_row+1] + [""] * (per_row + 1 - len(row_parts))))

    # Network row (aggregate)
    netifs = state.get("last", {}).get("network") or []
    if netifs:
        rx_total = sum(n.get("rx_mbs", 0) or 0 for n in netifs)
        tx_total = sum(n.get("tx_mbs", 0) or 0 for n in netifs)
        ifaces = " ".join(n["name"] for n in netifs)[:24]
        rows.append(f"{accent}│{rst}  NET  {ifaces:<24} RX={rx_total:6.1f}MB/s  TX={tx_total:6.1f}MB/s")

    # Truncate to fit max_rows (drop lowest-priority rows from the bottom).
    return rows[:max_rows]


def _render_sparkline_grid(state, max_rows, spark_w, cols, label_w=12, value_w=22, interval=2):
    """L2: grouped sparkline grid.

    Returns rows of the form:
        ── GROUP HEADER ─────────────────
          label    ┤▆▅▄▃▂┤   35.0%

    Groups are emitted in priority order; a group is skipped entirely if
    none of its series have data. Each row is framed by `─┤` on the left
    and `┤─` on the right so the time axis is visually obvious (newest
    at the right bracket, oldest at the left). Every sparkline row is
    followed by a thin X-axis tick row (`─Xs ago ─── now`) so the user
    can read the time window the sparkline covers.

    A single-sample sparkline (just one point in the buffer) is rendered
    centred in its column rather than flush-right, so the row reads as
    "a measurement in progress" instead of "a single bar at the end".
    """
    dim = "\033[90m"; rst = "\033[0m"; accent = "\033[36m"
    rows = []

    history = state["history"]
    gpus = state.get("last", {}).get("gpu") or []
    cpu_debug_on = bool(state.get("have_cpu_debug"))

    # The X-axis tick row only makes sense if there's actually a time
    # history to read. Show it just below the first sparkline group.
    age_str = _spark_age_label(history.get("cpu_pct"), interval)

    # ── Group 1: CPU + MEMORY (always present) ────────────────────────
    rows.append(f"{accent}{'─' * 2} SYSTEM {'─' * max(0, cols - 11)}{rst}")
    for label, key, fmt, fixed_max in [
        ("CPU %",   "cpu_pct", lambda v: f"{v:5.1f}%",  100.0),
        ("MEM %",   "mem_pct", lambda v: f"{v:5.1f}%",  100.0),
    ]:
        if len(rows) >= max_rows: return rows
        rows.append(_fmt_spark_row(history, label, key, fmt, spark_w, label_w, value_w))
    if age_str and len(rows) < max_rows:
        rows.append(f"  {dim}{' ' * (label_w - 2)}{age_str}{rst}")

    # ── Group 2: NETWORK ─────────────────────────────────────────────
    rows.append(f"{accent}{'─' * 2} NETWORK {'─' * max(0, cols - 12)}{rst}")
    for label, key, fmt, fixed_max in [
        ("NET RX", "net_rx", lambda v: f"{v:6.1f} MB/s", None),
        ("NET TX", "net_tx", lambda v: f"{v:6.1f} MB/s", None),
    ]:
        if len(rows) >= max_rows: return rows
        rows.append(_fmt_spark_row(history, label, key, fmt, spark_w, label_w, value_w))
    if state.get("have_pcie"):
        if len(rows) >= max_rows: return rows
        rows.append(f"{dim}  (PCIe+NVLink aggregated across all GPUs){rst}")
        rows.append(_fmt_spark_row(history, "PCIe/NVL", "pcie",
                                   lambda v: f"{v:6.2f} GB/s",
                                   spark_w, label_w, value_w))

    # ── Group 3: per-GPU rows (one block per GPU) ─────────────────────
    for i in range(len(gpus)):
        rows.append(f"{accent}{'─' * 2} GPU{i} {'─' * max(0, cols - 9)}{rst}")
        for label, key, fmt, fixed_max in [
            (f"GPU{i} util",   ("gpu_util", i), lambda v: f"{v:5.0f}%",   100.0),
            (f"GPU{i} mem",    ("gpu_mem",  i), lambda v: _fmt_bytes_mb(v * 1024), None),
            (f"GPU{i} power",  ("gpu_pwr",  i), lambda v: f"{v:5.0f}W",   None),
            (f"GPU{i} temp",   ("gpu_temp", i), lambda v: f"{v:5.0f}°C",  None),
        ]:
            if len(rows) >= max_rows: return rows
            rows.append(_fmt_spark_row(history, label, key, fmt, spark_w, label_w, value_w))

    # ── Group 4: DEBUG — per-core / per-sensor CPU breakdown ──────────
    if cpu_debug_on:
        rows.append(f"{accent}{'─' * 2} DEBUG (CPU per-core) {'─' * max(0, cols - 22)}{rst}")
        # Package / mean: existing "cpu_temp" and "cpu_freq" buffers.
        if len(rows) < max_rows:
            rows.append(_fmt_spark_row(history, "Pkg temp °C", "cpu_temp",
                                       lambda v: f"{v:5.1f}°C", spark_w, label_w, value_w))
        if len(rows) < max_rows:
            rows.append(_fmt_spark_row(history, "Mean freq", "cpu_freq",
                                       lambda v: f"{v:5.0f}MHz", spark_w, label_w, value_w))
        # Min / max / per-CCD temperature: derived from cpu_therm_temp_c[]
        # on the latest sample. We compute these ad-hoc every frame rather
        # than maintaining separate ring buffers (saves memory + simplifies
        # state, since the underlying per-sensor values are mostly stable).
        therms = state.get("last", {}).get("cpu_therm_temp_c") or []
        valid = [t for t in therms if t is not None]
        if valid and len(rows) < max_rows:
            rows.append(f"{dim}  CPU therm sensors ({len(valid)}):  "
                        f"min={min(valid):.0f}°C  max={max(valid):.0f}°C  "
                        f"avg={sum(valid)/len(valid):.1f}°C{rst}")
            # Sparkline of the max temperature across sensors over time.
            # Note: cpu_temp_max history buffer is appended in _push_sample(),
            # not here — appending during render would conflate multiple
            # frames per cycle into the ring buffer and break the time axis.
            if len(rows) < max_rows:
                rows.append(_fmt_spark_row(history, "Max T °C", "cpu_temp_max",
                                           lambda v: f"{v:5.0f}°C",
                                           spark_w, label_w, value_w))
        # Per-core freq min/max: derived from cpu_core_freq_mhz[].
        freqs = state.get("last", {}).get("cpu_core_freq_mhz") or []
        f_valid = [f for f in freqs if f]
        if f_valid and len(rows) < max_rows:
            rows.append(f"{dim}  CPU core freq ({len(f_valid)} cores):  "
                        f"min={min(f_valid):.0f}MHz  max={max(f_valid):.0f}MHz  "
                        f"avg={sum(f_valid)/len(f_valid):.0f}MHz{rst}")
            # Same as above — min/max buffers are appended in _push_sample().
            if len(rows) < max_rows:
                rows.append(_fmt_spark_row(history, "F min", "cpu_freq_min",
                                           lambda v: f"{v:5.0f}MHz",
                                           spark_w, label_w, value_w))
            if len(rows) < max_rows:
                rows.append(_fmt_spark_row(history, "F max", "cpu_freq_max",
                                           lambda v: f"{v:5.0f}MHz",
                                           spark_w, label_w, value_w))

    return rows if rows else [f"{dim}(no metrics to chart){rst}"]


def _spark_age_label(buf, interval):
    """Return a small X-axis label like '─4m ago ──────── now' that
    sits below a sparkline group and tells the user how far back the
    leftmost sample is. Returns '' if the buffer is empty or the
    sparkline is too narrow to label usefully."""
    if buf is None or len(buf.values()) == 0:
        return ""
    secs = (len(buf.values()) - 1) * interval
    if secs >= 60:
        return f"─{secs // 60}m ago ──────────────── now"
    if secs >= 10:
        return f"─{secs}s ago ────────────────── now"
    return f"─{secs}s ago ───────── now"


def _fmt_spark_row(history, label, key, fmt, spark_w, label_w, value_w, interval=2):
    """Format one sparkline row: `  LABEL<10> ─┤SPARK_W┤─  CURRENT>20`.

    The left `─┤` and right `┤─` brackets frame the sparkline so the
    time axis is visually obvious (newest sample at the right bracket,
    oldest at the left). A 1-sample buffer is rendered centred in the
    column instead of flush-right, which otherwise looks like a static
    bar instead of a time series in progress."""
    dim = "\033[90m"; rst = "\033[0m"
    buf = _resolve_buf(history, key)
    if buf is None:
        return f"  {label:<{label_w-2}}─┤{' ' * spark_w}┤─  {'—':>{value_w}}"
    vals = buf.values()
    if not vals:
        current = "  —  "
    else:
        current = fmt(vals[-1])
    if len(vals) == 1:
        sl = " " * (spark_w // 2 - 1) + _SPARK[0] + " " * (spark_w - spark_w // 2)
    else:
        sl = _sparkline(buf, spark_w, vmin=0.0, vmax=None)
    cur_disp = current[:value_w]
    return f"  {label:<{label_w-2}}─┤{sl}┤─  {cur_disp:>{value_w}}"


def _render_log_strip(state, max_rows, cols):
    """L3: nvtop-style event pane. Shows the last N samples as one-line
    summaries; supports scrollback via state['log_scroll'] (0 = newest
    at the bottom of the strip, positive N = scrolled up N rows)."""
    accent = "\033[36m"; dim = "\033[90m"; rst = "\033[0m"; yel = "\033[33m"
    log = list(state["log"])
    if not log:
        return [f"{dim}  (waiting for first sample…){rst}"]
    scroll = state.get("log_scroll", 0)
    # Window: log[-max_rows - scroll : -scroll or None]
    end = len(log) - scroll if scroll > 0 else len(log)
    start = max(0, end - max_rows)
    window = log[start:end]
    rows = []
    if scroll > 0:
        rows.append(f"{yel}  ⤴ scrolled up {scroll} lines  (G: jump to newest){rst}")
    for entry in window:
        ts = entry.get("ts", "")[:19]
        bits = [f"CPU={entry.get('cpu', 0):.0f}%", f"MEM={entry.get('mem', 0):.0f}%"]
        if entry.get("gpu") is not None:
            bits.append(f"GPU={entry['gpu']:.0f}%")
        if entry.get("temp") is not None:
            bits.append(f"T={entry['temp']:.0f}°C")
        if entry.get("pwr") is not None:
            bits.append(f"P={entry['pwr']:.0f}W")
        if entry.get("net") is not None:
            bits.append(f"NET={entry['net']:.1f}MB/s")
        line = f"  {ts}  " + "  ".join(bits)
        rows.append(f"{dim}{line[:cols-4]}{rst}")
    return rows


def _render_footer(state, cols, error):
    """One-line footer: status (PAUSED / ERR / live) + key bindings."""
    accent = "\033[36m"; dim = "\033[90m"; rst = "\033[0m"; red = "\033[31m"; yel = "\033[33m"
    bind = f"{dim}q: quit  space: pause  r: refresh  ↑↓: scroll log  G: latest  ?: help{rst}"
    if error:
        status = f"{red}ERR: {error}{rst}"
    elif state.get("paused"):
        status = f"{yel}⏸ PAUSED{rst}"
    else:
        status = f"{dim}⟳ live{rst}"
    return f"{accent}╰─{rst}  {status}  {bind}  {accent}─╯{rst}"


def _tui_separator(cols, ch="─"):
    """A horizontal rule using a Unicode box-drawing character."""
    return "\033[36m├" + ch * (cols - 2) + "┤\033[0m"


def _resolve_buf(history, key):
    """Look up a ring buffer from the history dict, supporting tuple keys
    for per-GPU series like ('gpu_util', 0)."""
    if isinstance(key, tuple):
        parent_key, idx = key
        lst = history.get(parent_key) or []
        if idx < len(lst):
            return lst[idx]
        return None
    return history.get(key)


# ── History buffer + sparkline rendering ────────────────────────────────

class _RingBuf:
    """Fixed-capacity ring buffer of floats (NaN-safe)."""
    __slots__ = ("cap", "_d")
    def __init__(self, cap): self.cap = cap; self._d = collections.deque(maxlen=cap)
    def append(self, v): self._d.append(v)
    def values(self):   return list(self._d)
    def __len__(self):  return len(self._d)


# Unicode block elements, low → high (8 levels).
_SPARK = "▁▂▃▄▅▆▇█"

def _sparkline(buf, width, vmin=0.0, vmax=None):
    """Render a sparkline of `width` chars from a _RingBuf.

    Auto-scales to [vmin, vmax] if vmax is None (uses observed range).
    NaN / None are rendered as spaces. Left-pads with spaces when the
    history is shorter than `width`."""
    if not isinstance(buf, _RingBuf): return " " * width
    vals = buf.values()
    if not vals: return " " * width
    if vmax is None:
        finite = [v for v in vals if v is not None]
        vmin = vmin if vmin is not None else (min(finite) if finite else 0.0)
        vmax = max(finite) if finite else 1.0
        if vmax == vmin: vmax = vmin + 1.0
    span = max(1e-9, vmax - vmin)
    vals = vals[-width:]
    out = []
    for v in vals:
        if v is None:
            out.append(" "); continue
        idx = int(round((v - vmin) / span * (len(_SPARK) - 1)))
        idx = max(0, min(len(_SPARK) - 1, idx))
        out.append(_SPARK[idx])
    pad = " " * (width - len(out))
    return pad + "".join(out)


# ── Per-cycle sample collection + state update ────────────────────────────

def _push_sample(state, stats):
    """Update the per-series ring buffers and append one entry to the log."""
    hist = state["history"]
    hist["cpu_pct"].append(stats.get("cpu_percent"))
    hist["mem_pct"].append(stats.get("memory_percent"))

    gpus   = stats.get("gpu") or []
    gpwr   = stats.get("gpu_power") or []
    # Resize per-GPU buffer lists if GPU count changed.
    for key in ("gpu_util", "gpu_mem", "gpu_pwr", "gpu_temp"):
        while len(hist[key]) < len(gpus):
            hist[key].append(_RingBuf(hist["cpu_pct"].cap))
    for i, g in enumerate(gpus):
        hist["gpu_util"][i].append(g.get("utilization"))
        mem = g.get("memory_used_mb")
        if mem is None and i < len(gpwr):
            mem = gpwr[i].get("memory_used_mb")
        hist["gpu_mem"][i].append((mem or 0) / 1024.0)   # to GB
        if i < len(gpwr):
            hist["gpu_pwr"][i].append(gpwr[i].get("power_w"))
        if g.get("temperature_c") is not None:
            hist["gpu_temp"][i].append(g.get("temperature_c"))

    # Network aggregate (rx+tx sum) for the NET sparkline; split series for RX/TX.
    netifs = stats.get("network") or []
    rx_total = sum(n.get("rx_mbs", 0) or 0 for n in netifs)
    tx_total = sum(n.get("tx_mbs", 0) or 0 for n in netifs)
    hist["net_rx"].append(rx_total)
    hist["net_tx"].append(tx_total)

    # PCIe / NVLink: aggregate across ALL GPUs (sum NVL + PCIe rx/tx).
    # Without this, a 0-GPU box shows nothing and a multi-GPU box only
    # shows GPU0's link — both wrong for "what's on the bus overall".
    pcie_val = 0.0
    have_pcie = False
    if gpus or gpwr:
        nvl_total = 0.0
        for p in gpwr:
            nvl_total += (p.get("nvlrx_mbs") or 0) + (p.get("nvltx_mbs") or 0)
        pci_total = 0.0
        for g in gpus:
            pci_total += (g.get("rxpci_mbs") or 0) + (g.get("txpci_mbs") or 0)
        # Also fall back to pcie_bandwidth_mbs on gpu_power entries (older collector)
        if nvl_total == 0 and pci_total == 0:
            for p in gpwr:
                nvl_total += (p.get("pcie_bandwidth_mbs") or 0)
        if nvl_total or pci_total:
            pcie_val = (nvl_total + pci_total) / 1024.0   # MB/s → GB/s
            have_pcie = True
    hist["pcie"].append(pcie_val if have_pcie else None)
    state["have_pcie"] = state.get("have_pcie", False) or have_pcie

    # CPU debug series (only when --cpu-debug is on and the data is present).
    if stats.get("cpu_debug"):
        therm = stats.get("cpu_therm_temp_c") or []
        pkg = stats.get("cpu_package_temp_c")
        # Pick the most informative thermal reading: package temp if present,
        # else first non-null sensor.
        therm_val = pkg
        if therm_val is None:
            for t in therm:
                if t is not None:
                    therm_val = t; break
        hist["cpu_temp"].append(therm_val)
        # CPU freq = mean of logical cores (or first available).
        freqs = stats.get("cpu_core_freq_mhz") or []
        if freqs:
            finite = [f for f in freqs if f]
            hist["cpu_freq"].append(sum(finite) / len(finite) if finite else None)
        else:
            hist["cpu_freq"].append(None)
        state["have_cpu_debug"] = True

    # Cached frequency string for the top CPU row.
    try:
        cf = psutil.cpu_freq()
        state["last"]["cpu_freq_str"] = _fmt_freq(cf.current if cf else None)
    except Exception:
        state["last"]["cpu_freq_str"] = "?"

    # Per-sensor / per-core min/max series for the DEBUG group. These need
    # to be appended once per cycle, not on every render frame — pushing
    # here keeps the ring buffer's sample timing aligned with the other
    # sparklines (so a 30-sample history actually covers 30 cycles).
    if stats.get("cpu_debug"):
        therms = stats.get("cpu_therm_temp_c") or []
        valid = [t for t in therms if t is not None]
        if valid:
            state["history"].setdefault("cpu_temp_max", _RingBuf(120)).append(max(valid))
        freqs = stats.get("cpu_core_freq_mhz") or []
        f_valid = [f for f in freqs if f]
        if f_valid:
            state["history"].setdefault("cpu_freq_min", _RingBuf(120)).append(min(f_valid))
            state["history"].setdefault("cpu_freq_max", _RingBuf(120)).append(max(f_valid))

    # Append to log (one entry per sample).
    state["log"].append({
        "ts":   stats.get("timestamp", ""),
        "cpu":  stats.get("cpu_percent") or 0,
        "mem":  stats.get("memory_percent") or 0,
        "gpu":  (gpus[0].get("utilization") if gpus else None),
        "temp": (gpus[0].get("temperature_c") if gpus else None),
        "pwr":  (gpwr[0].get("power_w") if gpwr else None),
        "net":  rx_total + tx_total,
    })
    # Auto-scroll reset: if the user is at the newest, keep them there; if
    # they scrolled up, leave them scrolled (preserves context on refresh).
    if state.get("log_scroll", 0) > 0 and not state.get("paused"):
        # While not paused and scrolled, advance scroll by 1 each refresh so
        # new lines appear at the bottom of the visible window.
        state["log_scroll"] += 1


def _tui_state(cpu_type, cpu_count):
    """Initial state for a TUI session."""
    return {
        "cpu_type": cpu_type,
        "cpu_count": cpu_count,
        "history": {
            "cpu_pct":  _RingBuf(120),
            "mem_pct":  _RingBuf(120),
            "gpu_util": [],
            "gpu_mem":  [],
            "gpu_pwr":  [],
            "gpu_temp": [],
            "net_rx":   _RingBuf(120),
            "net_tx":   _RingBuf(120),
            "pcie":     _RingBuf(120),
            "cpu_temp": _RingBuf(120),
            "cpu_freq": _RingBuf(120),
        },
        "log":          collections.deque(maxlen=500),
        "log_scroll":   0,
        "paused":       False,
        "have_cpu_debug": False,
        "have_pcie":    False,
        "last": {},
    }


def tui(interval=2, _display_name=None, cpu_debug=False):
    """Run the collector as an interactive nvtop-style TUI.

    3-layer layout fills the terminal:
      L1 top stat strip     : current snapshot with bars
      L2 sparkline grid     : one row per metric, scrolls history
      L3 log strip          : nvtop-style event pane, scrollable

    Key bindings (read every 100ms between collects):
      q / Ctrl-C            : quit (terminal restored)
      space                 : pause/resume
      r                     : force-refresh (skip sleep, re-collect)
      ↑                     : scroll log up
      ↓                     : scroll log down
      G / g                 : jump log to newest
      ?                     : help (TODO)"""
    global display_name
    display_name = _display_name
    if not sys.stdout.isatty():
        print("TUI mode requires a TTY. Re-run from a real terminal.", file=sys.stderr)
        sys.exit(1)

    import signal
    _alt_screen_on(); _hide_cursor(); _clear_screen()

    def _cleanup(*_):
        _show_cursor(); _alt_screen_off()
        sys.stdout.write("\n"); sys.stdout.flush()
        sys.exit(0)
    signal.signal(signal.SIGINT,  _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)
    # SIGWINCH handler: redraw on resize. Fall back to SIGUSR1 on systems
    # without it (rare on Linux); never use SIGUSR1's default behavior
    # (which is to terminate the process) by ensuring we override it.
    winch = getattr(signal, "SIGWINCH", None)
    if winch is not None:
        try:
            signal.signal(winch, lambda *_: None)
        except (AttributeError, ValueError):
            pass

    state = _tui_state(CPU_TYPE, CPU_COUNT)
    # Always enable NVLink/PCIe monitoring in TUI mode — the user is
    # sitting at the TTY precisely because they want to see link metrics,
    # and we want them to appear without having to wait 10s between samples.
    enable_nvlink = True
    print(f"Collecting TUI on [{HOSTNAME}], interval={interval}s, NVLink={'on' if enable_nvlink else 'off'}{', cpu-debug=on' if cpu_debug else ''}",
          file=sys.stderr)
    last_err = None
    try:
        while True:
            try:
                stats = collect(enable_nvlink=enable_nvlink, cpu_debug=cpu_debug)
                # Cache last full snapshot for L1 top strip.
                state["last"] = dict(stats)
                state["last"]["cpu_freq_str"] = state["last"].get("cpu_freq_str", "?")
                if not state.get("paused"):
                    _push_sample(state, stats)
                last_err = None
            except Exception as e:
                last_err = str(e)
            _tui_render(state, interval, error=last_err)

            # Sleep in 100ms slices, polling keys.
            slept = 0.0
            slice_s = 0.1
            while slept < interval:
                key = _read_key_nonblocking(slice_s)
                if not key: continue
                if key in ('q', 'Q'): return
                if key == ' ':        state["paused"] = not state["paused"]
                if key in ('r', 'R'): break     # out of sleep loop → re-collect
                if key == '\x1b':
                    # Read the next 2 bytes to figure out the escape sequence.
                    try:
                        import select as _sel
                        r2, _, _ = _sel.select([sys.stdin], [], [], 0.05)
                        seq = sys.stdin.read(2) if r2 else ''
                    except Exception:
                        seq = ''
                    if seq == '[A' or seq == 'OA':   # ↑
                        state["log_scroll"] = state.get("log_scroll", 0) + 1
                    elif seq == '[B' or seq == 'OB': # ↓
                        state["log_scroll"] = max(0, state.get("log_scroll", 0) - 1)
                elif key in ('g', 'G'):
                    state["log_scroll"] = 0
                slept += slice_s
    finally:
        _cleanup()


if __name__ == "__main__":
    _probe_gpu()
    args = sys.argv[1:]
    cpu_debug = "--cpu-debug" in args
    if cpu_debug:
        args.remove("--cpu-debug")
    tui_mode = "--tui" in args
    if tui_mode:
        args.remove("--tui")
    if len(args) < 2:
        print("Usage:")
        print("  python3 collector.py <interval> <display_name> [--cpu-debug]")
        print("     — daemon mode: writes per-cycle JSON to data/")
        print("  python3 collector.py --tui <interval> <display_name> [--cpu-debug]")
        print("     — interactive nvtop-style TUI on the local terminal")
        print("  <interval>    : polling interval in seconds (e.g. 10 for daemon, 1–5 for TUI)")
        print("  <display_name>: machine description, used in JSON filename and frontend (e.g. XE9785L_MI355X)")
        print("  --cpu-debug   : opt-in flag to record per-core CPU temperature + frequency")
        print("  --tui         : render an interactive TUI instead of writing JSON files")
        sys.exit(1)

    interval = int(args[0])
    _display_name = args[1]
    if tui_mode:
        tui(interval, _display_name, cpu_debug=cpu_debug)
    else:
        daemon(interval, _display_name, cpu_debug=cpu_debug)

