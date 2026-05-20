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

# ─── GPU globals ───────────────────────────────────────────────────────────────

GPU_AVAILABLE = True
GPU_COUNT = 0
GPU_TYPE  = None
GPU_VENDOR = None   # "nvidia" or "amd"


# ─── GPU probe: detect vendor then load appropriate backend ───────────────────

def _probe_gpu():
    """
    Detect GPU vendor via lspci, then dispatch to the correct backend.
    """
    global GPU_COUNT, GPU_TYPE, GPU_VENDOR

    try:
        result = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "VGA" in line or "3D controller" in line:
                if any(kw in line for kw in ("NVIDIA", "GeForce", "Quadro", "RTX", "A100", "H100")):
                    GPU_VENDOR = "nvidia"
                    break
                if any(kw in line for kw in ("AMD", "Radeon", "Instinct")):
                    GPU_VENDOR = "amd"
                    break
    except Exception:
        pass

    if GPU_VENDOR is None:
        try:
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, check=True, timeout=5
            )
            GPU_VENDOR = "nvidia"
        except Exception:
            try:
                subprocess.run(
                    ["amd-smi", "list"],
                    capture_output=True, timeout=5
                )
                GPU_VENDOR = "amd"
            except Exception:
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
    global GPU_COUNT, GPU_TYPE
    try:
        # Get GPU count: each "GPU: <id>" line in output
        result = subprocess.run(
            ["amd-smi", "list"],
            capture_output=True, text=True, timeout=10
        )
        gpu_ids = re.findall(r"^GPU:\s+(\d+)", result.stdout, re.MULTILINE)
        GPU_COUNT = min(8, len(gpu_ids))

        if GPU_COUNT == 0:
            raise RuntimeError("amd-smi list returned no GPU entries")

        # Get GPU name (board_name / name) from `amd-smi static -a`
        result = subprocess.run(
            ["amd-smi", "static", "-a", "-g", "0"],
            capture_output=True, text=True, timeout=10
        )
        # Look for "Marketing Name" or "Board Name" in the output
        name = None
        for line in result.stdout.splitlines():
            if any(k in line for k in ("Marketing Name", "Board Name", "Name", "Model")):
                # Format: "    Marketing Name: <name>" or similar
                parts = line.strip().split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    name = parts[1].strip()
                    break
        if not name:
            name = f"AMD_GPU_{gpu_ids[0]}"
        GPU_TYPE = name.replace(" ", "_")

        print(f"AMD GPU detected: {GPU_COUNT}x {GPU_TYPE} via amd-smi")
    except Exception as e:
        global GPU_AVAILABLE
        GPU_AVAILABLE = False
        GPU_COUNT = 0
        GPU_TYPE = None
        print(f"amd-smi not available, AMD GPU metrics disabled: {e}")


# ─── Helper: run amd-smi for a specific GPU, parse output ─────────────────────

def _amd_run(gpu_id, subcmd, timeout=8):
    """Run `amd-smi <subcmd> -g <gpu_id>`, return stdout text."""
    try:
        result = subprocess.run(
            ["amd-smi", subcmd, "-g", str(gpu_id)],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _amd_run_all(subcmd, timeout=8):
    """Run `amd-smi <subcmd>` (all GPUs), return stdout text."""
    try:
        result = subprocess.run(
            ["amd-smi", subcmd],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _parse_metric_block(stdout, gpu_id, *keys):
    """
    Parse an amd-smi output block for a specific GPU.
    The output format is:
        GPU: <id>
            KEY: VALUE
            KEY2: VALUE2
    Returns a dict {key: value} for the requested keys, or {} if not found.
    Only looks at the block belonging to gpu_id.
    """
    # Split into per-GPU blocks
    blocks = re.split(r"^GPU:\s+\d+", stdout, flags=re.MULTILINE)
    target = None
    for i, block in enumerate(blocks):
        # Check if this block's GPU id matches
        if f"GPU: {gpu_id}" in stdout.split("GPU:")[i] if i < len(blocks) else False:
            target = block
            break

    if target is None:
        # Fallback: find block by scanning
        current_gpu = None
        block_map = {}
        current_block = []
        for line in stdout.splitlines():
            m = re.match(r"^GPU:\s+(\d+)", line)
            if m:
                if current_gpu is not None:
                    block_map[current_gpu] = "\n".join(current_block)
                current_gpu = int(m.group(1))
                current_block = []
            else:
                current_block.append(line)
        if current_gpu is not None:
            block_map[current_gpu] = "\n".join(current_block)
        target = block_map.get(gpu_id, "")

    result = {}
    for key in keys:
        # Match "KEY: VALUE" or "KEY: UNIT" lines
        pattern = re.compile(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", re.MULTILINE)
        m = pattern.search(target)
        if m:
            val_str = m.group(1).strip()
            # Strip trailing units like "W", "MB", "GB", "°C", "Mb/s", "%"
            val_clean = re.sub(r"\s*(W|MB|GB|Mb/s|GT/s|%|°C)\s*$", "", val_str)
            # Handle "N/A"
            if val_clean == "N/A":
                result[key] = None
            else:
                result[key] = val_clean
    return result


# ─── GPU power ────────────────────────────────────────────────────────────────

def get_gpu_power():
    """Returns [{id, power_w}] or None. AMD has no power_limit in amd-smi metric."""
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


def _amd_get_gpu_power():
    """amd-smi metric -p: SOCKET_POWER: XX W"""
    stdout = _amd_run_all("metric -p", timeout=10)
    gpus = []
    for i in range(GPU_COUNT):
        vals = _parse_metric_block(stdout, i, "SOCKET_POWER")
        entry = {"id": i}
        raw = vals.get("SOCKET_POWER")
        if raw is not None:
            try:
                entry["power_w"] = float(raw)
            except ValueError:
                pass
        gpus.append(entry)
    return gpus


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
    """
    amd-smi metric -P: PCIe aggregate bandwidth in Mb/s (no per-direction split).
    Converts to MB/s. NVLink fields stay None.
    """
    stdout = _amd_run_all("metric -P", timeout=10)
    gpus_io = {}
    for i in range(GPU_COUNT):
        vals = _parse_metric_block(stdout, i, "BANDWIDTH")
        raw = vals.get("BANDWIDTH")
        if raw is not None:
            try:
                mbps = float(raw)
                gpus_io[i] = {
                    "id": i,
                    "rxpci_mbs": None,   # amd-smi -P has no direction split
                    "txpci_mbs": None,
                    "nvlrx_mbs": None,
                    "nvltx_mbs": None,
                    # Store aggregate as "pcie_bandwidth_mbs" for transparency
                    "pcie_bandwidth_mbs": round(mbps / 8, 3),
                }
            except ValueError:
                gpus_io[i] = {"id": i}
        else:
            gpus_io[i] = {"id": i}
    return [gpus_io.get(i, {"id": i}) for i in range(GPU_COUNT)]


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
    """
    amd-smi metric -u: GFX_ACTIVITY: XX %
    amd-smi metric -m: USED_VRAM / TOTAL_VRAM (MB)
    """
    entry = {"id": gpu_id}

    # Utilization
    stdout_u = _amd_run(gpu_id, "metric -u", timeout=8)
    vals_u = _parse_metric_block(stdout_u, gpu_id, "GFX_ACTIVITY")
    raw_util = vals_u.get("GFX_ACTIVITY")
    if raw_util is not None:
        try:
            entry["utilization"] = float(raw_util.rstrip(" %"))
        except ValueError:
            pass

    # Memory
    stdout_m = _amd_run(gpu_id, "metric -m", timeout=8)
    vals_m = _parse_metric_block(stdout_m, gpu_id, "USED_VRAM", "TOTAL_VISIBLE_VRAM")
    raw_used = vals_m.get("USED_VRAM")
    raw_total = vals_m.get("TOTAL_VISIBLE_VRAM")
    if raw_used is not None:
        try:
            entry["memory_used_mb"] = float(raw_used.rstrip(" MB"))
        except ValueError:
            pass
    if raw_total is not None:
        try:
            entry["memory_total_mb"] = float(raw_total.rstrip(" MB"))
        except ValueError:
            pass

    return (gpu_id, entry)


def _amd_query_gpu_power(gpu_id):
    """
    amd-smi metric -p: SOCKET_POWER: XX W
    amd-smi metric -t: HOTSPOT: XX °C (EDGE is N/A on MI300)
    """
    entry = {"id": gpu_id}

    # Power
    stdout_p = _amd_run(gpu_id, "metric -p", timeout=8)
    vals_p = _parse_metric_block(stdout_p, gpu_id, "SOCKET_POWER")
    raw_power = vals_p.get("SOCKET_POWER")
    if raw_power is not None:
        try:
            entry["power_w"] = float(raw_power.rstrip(" W"))
        except ValueError:
            pass

    # Temperature: prefer HOTSPOT, fall back to EDGE
    stdout_t = _amd_run(gpu_id, "metric -t", timeout=8)
    vals_t = _parse_metric_block(stdout_t, gpu_id, "HOTSPOT", "EDGE")
    raw_temp = vals_t.get("HOTSPOT") or vals_t.get("EDGE")
    if raw_temp is not None:
        try:
            entry["temp_c"] = float(raw_temp.rstrip(" °C"))
        except ValueError:
            pass

    return (gpu_id, entry)


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

def collect(enable_nvlink=True):
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
    return stats


# ─── Daemon ─────────────────────────────────────────────────────────────────

def append_to_file(data, period):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    hostname = data.get("hostname", HOSTNAME)
    path = os.path.join(DATA_DIR, f"{period}_{hostname}_{ts}.json")
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


def daemon(interval=10, _display_name=None):
    global display_name
    display_name = _display_name
    gpu_label = f"{GPU_COUNT}x GPU" if GPU_COUNT else "no GPU"
    vendor_label = f"({GPU_VENDOR.upper()})" if GPU_VENDOR else ""
    enable_nvlink = (interval >= 10)
    if _display_name:
        print(f"  Display name: [{_display_name}]  (hostname: [{HOSTNAME}])")
    if interval < 10:
        print("\n" + "=" * 60)
        print("\033[91m  WARNING: NVLink/PCIe monitoring will NOT start\033[0m")
        print(f"           This feature requires interval >= 10s (current: {interval}s)")
        print("=" * 60 + "\n")
    print(f"Collector starting on [{HOSTNAME}], interval={interval}s, NVLink={'enabled' if enable_nvlink else 'disabled'}, GPU={gpu_label} {vendor_label}")
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
                    elif g.get("pcie_bandwidth_mbs") is not None:
                        nv = f" PCIe={g['pcie_bandwidth_mbs']:.1f}MB/s"
                    gpu_str += f" GPU{g['id']}={g.get('utilization','?')}%{nv}"

            print(f"[{stats['timestamp']}] CPU={stats['cpu_percent']}% "
                  f"MEM={stats['memory_percent']}%{pwr_str}{gpu_str}{net_str}")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    _display_name = sys.argv[2] if len(sys.argv) > 2 else None
    daemon(interval, _display_name)
