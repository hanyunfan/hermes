# System Monitor

**Multi-machine GPU server monitoring dashboard.** Collects CPU, memory, GPU, power, and network metrics from one or more servers and displays them in a browser via [GitHub Pages](https://hanyunfan.github.io/hermes/system-monitor/).

```
┌─────────────┐         ┌─────────────────────────┐         ┌──────────────────┐
│  Machines   │  cron   │   GitHub Repository    │  Pages  │   Browser        │
│  running    │────────▶│   (hermes repo)         │───────▶│   Dashboard      │
│  collector  │  hourly │   data/                 │ static  │   Chart.js SPA   │
│  (daemon)   │         │   machines.json         │  host   │                  │
└─────────────┘         └─────────────────────────┘         └──────────────────┘
```

## Features

| Metric | Source | Notes |
|--------|--------|-------|
| CPU % | `psutil` | Per-core aggregate |
| Memory used/total | `psutil` | System RAM |
| GPU utilization, memory | `nvidia-smi` | Up to 8 GPUs per machine |
| GPU temperature | `nvidia-smi` / `amd-smi` | Per-GPU temperature (°C) |\n| GPU power draw | `nvidia-smi` | Per-GPU watts + TDP limit |
| PCIe RX/TX throughput | `nvidia-smi dmon` | GPU0 only; requires `interval >= 10s` |
| NVLink RX/TX throughput | `nvidia-smi dmon` | GPU0 only; requires `interval >= 10s` |
| Network throughput | `psutil` | Per interface (e.g. eth0, ib0) |
| System power (whole-machine) | `ipmitool dcmi` | BMC-based; requires `ipmitool` + BMC access |
| CPU power (package) | `intel_rapl` | RAPL CPU package power |
| **CPU core temperature** (opt-in) | `psutil.sensors_temperatures` | Per physical core (°C). Intel `coretemp` / AMD `k10temp` if exposed. Requires `--cpu-debug` flag. |
| **CPU core frequency** (opt-in) | `psutil.cpu_freq(percpu=True)` | Per logical core (MHz). Requires `--cpu-debug` flag. |

> **PCIe/NVLink**: These metrics use `nvidia-smi dmon` which needs ~3–4 seconds of sampling to produce valid numbers. The collector therefore only enables them when `interval >= 10s`. If you start with a smaller interval, a red WARNING is printed and these fields will be absent from the JSON.

> **System power**: Requires `ipmitool` command to be installed and the BMC (Baseboard Management Controller) to have `DCMI power reading` permission. If unavailable, `system_power_w` is `null`.

## Architecture

### 1. Collector (`collector.py`) — runs on every machine
A Python daemon that samples metrics every N seconds and **appends** JSON Lines to a local file.

- **Platform**: Linux with `psutil` (CPU/memory) and `nvidia-smi` (GPU)
- **Output**: `data/metrics_<display_name>_<YYYYMMDD>.json` — one JSON object per line. `display_name` is a required argument (e.g. `XE9785L_MI355X`) used to distinguish machines with identical hostnames.
- **Scheduling**: `systemd` service (`system-monitor.service`) for auto-start on boot
- **Hostname**: auto-detected via `socket.gethostname()` — each machine gets its own file

### 2. GitHub Repository — stores and distributes data
A GitHub repo holds all data files and the static web dashboard.

- **`machines.json`** — regenerated from data files by `sync_machines.py`; lists all discovered machines, GPU types, and GPU counts
- **GitHub Actions** (`.github/workflows/sync-machines.yml` at repo root) — automatically runs `sync_machines.py` and pushes updated `machines.json` whenever a new data file is pushed to `system-monitor/data/`
- **GitHub Pages** — serves the `index.html` and `data/` directory as a static site

### 3. Dashboard (`index.html`) — browser UI
Chart.js-powered SPA served directly from GitHub Pages.

- **Range selector**: Hour / Day / Week — controls the time window
- **Machine selector**: switch between machines
- **Per-GPU charts**: each GPU gets its own colored line
- **PCIe/NVLink chart**: GPU0 PCIe RX/TX + NVLink RX/TX (hidden if no data)
- **Power chart**: per-GPU watts + system power (BMC) + CPU power (RAPL) + GPU temperature
- **Aggregate stats**: mean CPU %, mean GPU utilization, total GPU memory
- **Auto-refresh**: polls every 10 seconds

## Setup

### 1. Install dependencies

```bash
pip install psutil
```

### 2. Start the collector

```bash
# Usage: python3 collector.py <interval> <display_name> [--cpu-debug]
#   <interval>    : polling interval in seconds (e.g. 10)
#   <display_name>: machine identifier used in JSON filename and frontend (e.g. XE9785L_MI355X)
#   --cpu-debug   : opt-in flag to record per-core CPU temperature + frequency

# Run once to test:
python3 collector.py 10 XE9785L_MI355X            # AMD MI355X machine
python3 collector.py 10 XE9680_A100               # NVIDIA A100 machine

# PCIe/NVLink enabled (requires interval >= 10s):
python3 collector.py 10 XE9680_A100
# Smaller intervals work but PCIe/NVLink metrics are skipped:
python3 collector.py 5 XE9680_A100                 # red WARNING printed

# CPU debug mode (opt-in) — adds per-core temperature and frequency charts:
python3 collector.py 10 XE9785L_MI355X --cpu-debug

# Or install as a systemd service (auto-starts on boot):
sudo cp system-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now system-monitor
```

> **Important**: `display_name` is required. Without it the collector exits with a usage message. Use a unique name per machine — if two machines share the same `display_name`, their data files will collide.

### 3. (Optional) Run a local HTTP server for development

```bash
python3 server.py
# → http://localhost:8765
```

### 4. Optional: system power via ipmitool

If `ipmitool` is installed and the BMC has DCMI permission, whole-machine AC power is collected automatically:

```bash
# Test BMC access:
ipmitool dcmi power reading

# Expected output:
#   Instantaneous power reading:           1234 W
```

If the command fails or times out, `system_power_w` will be `null` in the JSON (no error is printed).

## GitHub Pages URL

```
https://hanyunfan.github.io/hermes/system-monitor/
```

The dashboard is a pure static SPA — no server-side logic, no authentication. Anyone with the link can view it.

## Data sources

The dashboard has two view sources, switchable with the **Source:** buttons in the top bar:

| Source | What you see | When to use |
|--------|--------------|-------------|
| **GitHub** (default) | The full repo's `data/` directory via `raw.githubusercontent.com` | Production / shared view. Every machine that has ever pushed is here. |
| **Local :8765** | Whatever `server.py` is serving on `localhost:8765` | Local development. Use while running `collector.py` on this machine so you see data *before* it gets pushed. |

The choice is remembered in `localStorage` and re-applied on next page load.

> Note: the two views are *not* synchronized. A machine uploaded to the local server does **not** appear in the GitHub view, and vice versa. To move a file from local to GitHub, use the **Upload JSON** button (see below) — the file is pushed to the repo and the GitHub view will pick it up automatically.

## Uploading a JSON file from the dashboard

The **⬆ Upload JSON** button on the top bar pushes a `metrics_*.json` file to the GitHub repo via the [Contents API](https://docs.github.com/en/rest/repos/contents). The flow is:

```
[Browser] ──PUT Contents API──▶ [GitHub repo]
                                     │
                                     ▼  (push event)
                          [sync-machines.yml Actions workflow]
                                     │
                                     ▼  (auto-commits machines.json)
                          [machines.json updated in ~5–10s]
                                     │
                                     ▼  (≤30s frontend poll)
                          [New machine appears in dropdown]
```

### One-time setup: create a PAT

The Contents API needs a Personal Access Token (classic, with `repo` scope, or fine-grained with **Contents: Read and write** for this repo).

1. Visit <https://github.com/settings/tokens/new> (or **Settings → Developer settings → Personal access tokens**)
2. Pick **Fine-grained token** (recommended) or **Tokens (classic)**
3. Resource owner: your account. Repository access: **Only select repositories → hanyunfan/hermes**
4. Permissions → **Contents: Read and write**
5. Generate, copy the token (you'll only see it once)
6. In the dashboard, click **⬆ Upload JSON** → a prompt asks for the token. Paste it.
7. The token is stored in your browser's `localStorage` under `systemMonitorGithubPAT`. It is **never** sent anywhere except `api.github.com`.

To clear the token: open DevTools → Application → Local Storage → delete the `systemMonitorGithubPAT` key, or just call `localStorage.removeItem('systemMonitorGithubPAT')` in the console.

### What happens if the PAT is wrong / expired

The dashboard clears it from localStorage and asks for a new one. Old token isn't recoverable — generate a new one in the GitHub settings.

### Why no PAT-prompt UI outside the upload button

The read paths (viewing machines, charts) go through `raw.githubusercontent.com`, which is **public read** for this repo. Only writes need a token. So you can hand the dashboard URL to anyone without giving them a token.

## Data Format

Each line in `data/metrics_<display_name>_<YYYYMMDD>.json`:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601 UTC) | When the sample was taken |
| `hostname` | string | Machine hostname |
| `display_name` | string or null | Optional display name for the dashboard UI; null to use hostname |
| `gpu_count` | integer | Number of GPUs on this machine (0–8) |
| `gpu_type` | string or null | GPU model name (e.g. "NVIDIA H100 80GB") |
| `cpu_percent` | float | CPU utilization % (0–100) |
| `memory_percent` | float | System RAM utilization % |
| `memory_used_mb` | float | System RAM used (MB) |
| `memory_total_mb` | float | System RAM total (MB) |
| `network` | array | Per-interface network throughput (see below) |
| `system_power_w` | float or null | Whole-machine power (W) via BMC/ipmitool; null if unavailable |
| `cpu_power_w` | float or null | CPU package power (W) via RAPL; null if unavailable |
| `gpu_power` | array or null | Per-GPU power draw (see below); null if no GPU |
| `gpu` | array or null | Per-GPU stats (see below); null if no GPU |
| `cpu_debug` | bool | **Only present when collector is run with `--cpu-debug` flag.** Signals that the per-core arrays below are populated. |
| `cpu_core_temp_c` | array of float or null | Per **physical** core temperature (°C); sparse — `null` for cores with no sensor. Empty `[]` on chips that only expose package temperature (e.g. AMD Zen via k10temp). Only present with `--cpu-debug`. |
| `cpu_core_freq_mhz` | array of float | Per **logical** core current frequency (MHz). Length equals `psutil.cpu_count(logical=True)`. Only present with `--cpu-debug`. |

`network[]` elements:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Interface name (e.g. "eth0", "ib0") |
| `rx_mbs` | float | RX throughput (MB/s) |
| `tx_mbs` | float | TX throughput (MB/s) |

`gpu_power[]` elements:

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | GPU index (0–7) |
| `power_w` | float | Current power draw (W) |
| `power_limit_w` | float | Power limit / TDP (W) |
| `temp_c` | float | GPU temperature (°C) |

`gpu[]` elements:

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | GPU index (0–7) |
| `utilization` | float | GPU utilization % (0–100) |
| `memory_used_mb` | float | GPU memory used (MB) |
| `memory_total_mb` | float | GPU memory total (MB) |
| `rxpci_mbs` | float or null | PCIe RX throughput (MB/s); null if N/A or interval < 10s |
| `txpci_mbs` | float or null | PCIe TX throughput (MB/s); null if N/A or interval < 10s |
| `nvlrx_mbs` | float or null | NVLink RX throughput (MB/s); null if no NVLink or interval < 10s |
| `nvltx_mbs` | float or null | NVLink TX throughput (MB/s); null if no NVLink or interval < 10s |
| `error` | string | Present if nvidia-smi query failed |

## Project Files

| File | Purpose |
|------|---------|
| `collector.py` | Daemon — samples and writes metrics to `data/` |
| `index.html` | Dashboard — Chart.js SPA served via GitHub Pages |
| `server.py` | Optional local HTTP server (dev only, port 8765) |
| `sync_machines.py` | Syncs `machines.json` from data files (used by GitHub Actions) |
| `machines.json` | Auto-generated list of machines and GPU counts |
| `system-monitor.service` | systemd unit for auto-start |
| `.github/workflows/sync-machines.yml` | GitHub Actions: auto-syncs machines.json on data changes |
| `data/` | JSON Lines data files (one per machine per UTC date) |

## Troubleshooting

**"No data for this range"**: Check that the collector daemon is running (`ps aux | grep collector`), and that data has been pushed to GitHub.

**GPU charts show "N/A"**: The `machines.json` may be stale. Push a new data file — GitHub Actions will automatically regenerate `machines.json`. Or manually run `python3 sync_machines.py`.

**Old data in browser**: GitHub Pages can cache aggressively. Hard-refresh with `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac), or open DevTools → Network → disable cache.

**PCIe/NVLink chart shows no data**: This is expected if the collector was started with `interval < 10s`. Restart with `python3 collector.py --interval 10`. The red WARNING message confirms this.

**system_power_w is null**: Confirm `ipmitool dcmi power reading` works on that machine and that the BMC has DCMI permissions.

**CPU core temperature / frequency charts don't appear**: The collector was not started with `--cpu-debug`. Restart with `python3 collector.py 10 <name> --cpu-debug`. Existing files recorded without the flag will not retroactively gain the charts — start a new data file.

**Multiple collectors on same display_name**: Only one collector per `display_name` should run, otherwise data files will interleave and corrupt each other.
