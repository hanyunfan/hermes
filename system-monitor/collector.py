#!/usr/bin/env python3
"""
System metrics collector: CPU, GPU (up to 8), memory, GPU power, network.
Runs as daemon, writes JSON Lines.
"""

import json
import os
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

GPU_AVAILABLE = True
GPU_COUNT = 0
GPU_TYPE  = None

# ─── GPU probe ─────────────────────────────────────────────────────────────────

def _probe_gpu():
    global GPU_COUNT, GPU_TYPE
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True, timeout=5
        )
        raw = result.stdout.strip().split("\n")[0].strip()
        # Strip leading "NVIDIA " prefix, replace spaces with underscores
        GPU_TYPE = raw[7:].strip().replace(" ", "_") if raw.startswith("NVIDIA ") else raw.replace(" ", "_")
        GPU_COUNT = min(8, len([n for n in result.stdout.strip().split("\n") if n.strip()]))
    except Exception:
        GPU_AVAILABLE = False
        print("nvidia-smi not available, GPU metrics disabled.")

_probe_gpu()


# ─── System power (BMC / IPMI, whole-machine AC input) ────────────────────────

def get_system_power():
    """
    Returns whole-machine AC input power in watts (float), or None if unavailable.
    Uses: ipmitool dcmi power reading | grep Instantaneous
    Falls back to /dev/ipmi0 presence check (placeholder for future use).
    """
    # ── Method 1: ipmitool DCMI (BMC-based, no sudo needed) ─────────────────
    try:
        result = subprocess.run(
            ["ipmitool", "dcmi", "power", "reading"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Instantaneous" in line:
                    # e.g. "  Instantaneous power reading:    2000 W"
                    val = line.split(":")[-1].strip().split()[0]
                    return float(val)
    except Exception:
        pass

    # ── Method 2: /dev/ipmi0 via OpenIPMI driver (no sudo needed) ────────────
    # /dev/ipmi0 is a character device; simple read() returns nothing.
    # Real IPMI communication requires ioctl calls — not implemented here.
    try:
        if os.path.exists("/dev/ipmi0"):
            pass
    except Exception:
        pass

    return None


# ─── CPU power (RAPL CPU package power, requires sudo) ───────────────────────

def get_cpu_power():
    """
    Returns CPU package power in watts (float) via RAPL energy delta,
    or None if sudo is not available without password.
    Reads /sys/class/powercap/intel-rapl:0/energy_uj (cumulative μJ since boot)
    and maintains _RAPL_PREV to compute watts = delta_J / delta_s.
    """
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
            joules = float(result.stdout.strip()) / 1_000_000  # μJ → J
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


# ─── GPU power (nvidia-smi, no sudo needed) ────────────────────────────────────

def get_gpu_power():
    """Returns [{id, power_w, power_limit_w}] or None."""
    if not GPU_AVAILABLE or GPU_COUNT == 0:
        return None
    gpus = []
    for i in range(GPU_COUNT):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--id=" + str(i),
                 "--query-gpu=power.draw,power.limit",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=5
            )
            power_draw, power_limit = result.stdout.strip().split(", ")
            gpus.append({
                "id": i,
                "power_w": float(power_draw),
                "power_limit_w": float(power_limit)
            })
        except Exception:
            gpus.append({"id": i})
    return gpus


# ─── GPU PCIe + NVLink throughput (nvidia-smi dmon, no sudo) ──────────────────

_GPU_IO_PREV = {}   # gpu_id -> {rxpci, txpci, nvlrx, nvltx}


_GPU_IO_DEBUG = os.environ.get("COLLECTOR_DEBUG", "0") == "1"


def get_gpu_io(enabled=True):
    """
    Returns list of dicts with PCIe and NVLink throughput in MB/s per GPU,
    or None if nvidia-smi dmon is unavailable / disabled.

    When enabled=False, returns None immediately (fast path, no subprocess call).
    NVLink data is only meaningful when the collector interval is >= 10s,
    as the nvidia-smi dmon needs ~3s to collect valid NVLink samples.
    """
    if not enabled or not GPU_AVAILABLE or GPU_COUNT == 0:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "dmon", "-s", "t", "--gpm-metrics", "60,61", "-c", "4", "-o", "T"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            sys.stderr.write(f"[get_gpu_io] dmon exit code {result.returncode}\n")
            return None
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[get_gpu_io] dmon timed out after 8s — killing\n")
        return None
    except Exception as e:
        sys.stderr.write(f"[get_gpu_io] exception: {e}\n")
        return None

    col_map = {}   # metric name (lowercase) -> column index in data_cols
    gpus_io = {}  # gpu_id -> {rxpci_mbs, txpci_mbs, nvlrx_mbs, nvltx_mbs}

    for line in result.stdout.strip().splitlines():
        parts = line.strip().split()
        if not parts:
            continue

        if _GPU_IO_DEBUG:
            sys.stderr.write(f"[get_gpu_io] DEBUG line: {parts}\n")

        # Header detection: look for the line that has metric names like
        # rxpci/txpci/nvlrx/nvltx (or pcirx/pcitx).  This is the line that
        # starts with "# gpu" (metric names, no timestamp) or "#Time" (with
        # timestamp).  We identify it by the presence of a known metric name.
        if parts[0].startswith("#"):
            metric_names = {"rxpci", "txpci", "nvlrx", "nvltx", "pcirx", "pcitx"}
            header_cols = [c.lower() for c in parts]
            if _GPU_IO_DEBUG:
                sys.stderr.write(f"[get_gpu_io] DEBUG header_cols={header_cols} intersect={metric_names & set(header_cols)}\n")
            if metric_names & set(header_cols):
                # This is the metric-names header row.
                # Build col_map relative to data columns (parts[1:]) so offsets
                # are always correct regardless of whether the line starts with
                # "#" (no timestamp) or "#Time" (timestamp present).
                for idx, col in enumerate(parts[1:]):   # data-col offset from parts[1]
                    if col.lower() in metric_names:
                        col_map[col.lower()] = idx   # idx is already relative to parts[1] (data_cols)
                if _GPU_IO_DEBUG:
                    sys.stderr.write(f"[get_gpu_io] DEBUG col_map built: {col_map}\n")
            continue

        if not parts[0].isdigit():
            # With -o T, data lines start with timestamp (e.g. "11:20:37"), GPU ID is parts[1]
            if len(parts) > 1 and parts[1].isdigit():
                gpu_id = int(parts[1])
                data_cols = parts[1:]   # skip timestamp; gpu is first data element
            else:
                continue
        else:
            gpu_id = int(parts[0])
            data_cols = parts[1:]       # skip gpu_id; rest are metric values

        if _GPU_IO_DEBUG:
            sys.stderr.write(f"[get_gpu_io] DEBUG gpu_id={gpu_id} data_cols={data_cols} col_map={col_map}\n")

        def val(key):
            idx = col_map.get(key)
            if idx is None or idx >= len(data_cols) or data_cols[idx] == "-":
                return None
            try:
                return float(data_cols[idx])
            except ValueError:
                return None

        # rxpci/txpci: PCIe RX/TX in MB/s (from -s t)
        # nvlrx/nvltx: NVLink RX/TX — nvidia-smi may report these as
        #   "nvlrx"/"nvltx" (L4 etc.) OR "pcirx"/"pcitx" (H100 etc.)
        #   Both are in GPM:MiB/s → convert to MB/s (×1.048576)
        rxpci = val("rxpci")
        txpci = val("txpci")
        # Must use "is not None" — val() returns float which can be 0.0 (falsy)
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

    if _GPU_IO_DEBUG:
        sys.stderr.write(f"[get_gpu_io] DEBUG return: {[gpus_io.get(i) for i in range(min(GPU_COUNT,8))]}\n")

    return [gpus_io.get(i, {"id": i}) for i in range(GPU_COUNT)]


# ─── Network throughput (rx/tx bytes delta, no sudo) ───────────────────────────

_NET_PREV = {}   # iface -> (rx_bytes, tx_bytes, timestamp)
_RAPL_PREV = None   # (joules, timestamp)
_NET_LOCK = threading.Lock()


def _read_net_stats():
    """
    Reads current rx_bytes / tx_bytes for all non-loopback, non-docker interfaces.
    Returns dict: iface -> {rx_bytes, tx_bytes}
    """
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
    """
    Returns list of dicts with iface name, rx_mbs, tx_mbs (MB/s as float).
    Computes delta from previous sample.  Returns [] if no delta available yet.
    Skips loopback / docker.
    """
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
                    # Only record if counter advanced or this is the first sample after boot
                    if rx_rate >= 0 and tx_rate >= 0:
                        result.append({
                            "name": iface,
                            "rx_mbs": round(rx_rate, 3),
                            "tx_mbs": round(tx_rate, 3)
                        })
            _NET_PREV[iface] = (cur["rx_bytes"], cur["tx_bytes"], now)

    # Sort: IB first, then Ethernet, each group by name
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


# ─── GPU stats (utilization, memory, PCIe/NVLink) — parallel execution ────────

def _query_gpu_util_mem(gpu_id):
    """Query utilization + memory for one GPU. Returns (gpu_id, dict) or (gpu_id, None)."""
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


def _query_gpu_power(gpu_id):
    """Query power + temperature for one GPU. Returns (gpu_id, dict) or (gpu_id, None)."""
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


def get_gpu_stats(enable_nvlink=True):
    """
    Collect stats for all GPUs in parallel.
    GPU util/mem queries (x8) + dmon (x1, NVLink) all run concurrently.
    Returns (gpu_stats_list, gpu_power_list, gpu_io_list).
    """
    if not GPU_AVAILABLE or GPU_COUNT == 0:
        return None, None, None

    # GPU util+mem queries — one worker per GPU
    with ThreadPoolExecutor(max_workers=GPU_COUNT) as ex:
        util_mem_futures = [ex.submit(_query_gpu_util_mem, i) for i in range(GPU_COUNT)]
        util_mem_results = [f.result() for f in util_mem_futures]

    # NVLink/PCIe via dmon — runs in parallel with the GPU queries above
    gpu_io = get_gpu_io(enabled=enable_nvlink)  # single dmon subprocess

    # gpu_power queries — also parallel with dmon (they're all nvidia-smi)
    with ThreadPoolExecutor(max_workers=GPU_COUNT) as ex:
        power_futures = [ex.submit(_query_gpu_power, i) for i in range(GPU_COUNT)]
        power_results = [f.result() for f in power_futures]

    # Build gpu_stats list
    gpus = [None] * GPU_COUNT
    for gpu_id, entry in util_mem_results:
        gpus[gpu_id] = entry

    # Merge NVLink/PCIe into gpu entries
    if gpu_io:
        io_map = {g["id"]: g for g in gpu_io}
        for i in range(GPU_COUNT):
            io_entry = io_map.get(i, {})
            # Merge but skip 'id' key to avoid duplicate
            for k, v in io_entry.items():
                if k != "id" and gpus[i] is not None:
                    gpus[i][k] = v
            if _GPU_IO_DEBUG and gpus[i]:
                sys.stderr.write(f"[get_gpu_stats] DEBUG gpu[{i}] after io merge: nvlrx={gpus[i].get('nvlrx_mbs')} nvltx={gpus[i].get('nvltx_mbs')}\n")

    # Build gpu_power list
    power_map = {r[0]: r[1] for r in power_results}
    gpu_power = [power_map.get(i, {"id": i}) for i in range(GPU_COUNT)]

    return gpus, gpu_power, gpu_io


# ─── Main collect ──────────────────────────────────────────────────────────────

def collect(enable_nvlink=True):
    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    net = _get_net_throughput_mbs()
    sys_power = get_system_power()   # BMC whole-machine AC power
    cpu_power = get_cpu_power()      # RAPL CPU package power

    # All GPU queries (util/mem x8 + power x8 + dmon x1) run in parallel
    gpu_stats, gpu_power, _ = get_gpu_stats(enable_nvlink=enable_nvlink)

    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": HOSTNAME,
        "display_name": display_name,
        "gpu_count": GPU_COUNT,
        "gpu_type": GPU_TYPE,
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "memory_used_mb": mem.used / (1024 ** 2),
        "memory_total_mb": mem.total / (1024 ** 2),
        "network": net,
        "system_power_w": sys_power,  # BMC whole-machine AC power
        "cpu_power_w": cpu_power,     # RAPL CPU package power
        "gpu_power": gpu_power,
        "gpu": gpu_stats
    }
    return stats


# ─── Daemon ───────────────────────────────────────────────────────────────────

def append_to_file(data, period):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    hostname = data.get("hostname", HOSTNAME)
    path = os.path.join(DATA_DIR, f"{period}_{hostname}_{ts}.json")
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


def daemon(interval=10, display_name=None):
    gpu_label = f"{GPU_COUNT}x GPU" if GPU_COUNT else "no GPU"
    enable_nvlink = (interval >= 10)
    shown_name = display_name or HOSTNAME
    if display_name:
        print(f"  Display name: [{display_name}]  (hostname: [{HOSTNAME}])")
    if interval < 10:
        print("\n" + "=" * 60)
        print("\033[91m  WARNING: NVLink/PCIe monitoring will NOT start\033[0m")
        print(f"           This feature requires interval >= 10s (current: {interval}s)")
        print(f"           PCIe/NVLink data will NOT be collected.")
        print(f"           Rerun with: python3 collector.py --interval 10")
        print("=" * 60 + "\n")
    print(f"Collector starting on [{HOSTNAME}], interval={interval}s, NVLink={'enabled' if enable_nvlink else 'disabled'}, GPU={gpu_label}")
    while True:
        try:
            stats = collect(enable_nvlink=enable_nvlink)
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
                    gpu_str += f" GPU{g['id']}={g.get('utilization','?')}%{nv}"

            print(f"[{stats['timestamp']}] CPU={stats['cpu_percent']}% "
                  f"MEM={stats['memory_percent']}%{pwr_str}{gpu_str}{net_str}")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    display_name = sys.argv[2] if len(sys.argv) > 2 else None
    daemon(interval, display_name=display_name)
