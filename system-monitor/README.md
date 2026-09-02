# System Monitor

**Multi-machine GPU server monitoring dashboard.** Collects CPU, memory, GPU, power, and network metrics from one or more servers and displays them in a browser via [GitHub Pages](https://github.gtie.dell.com/pages/Frank-Han1/devin/system-monitor/).

```
┌─────────────┐         ┌─────────────────────────┐         ┌──────────────────┐
│  Machines   │  cron   │   GitHub Repository    │  Pages  │   Browser        │
│  running    │────────▶│   (devin repo)          │───────▶│   Dashboard      │
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
| GPU temperature | `nvidia-smi` / `amd-smi` | Per-GPU temperature (°C) |
| GPU throttle temperature | `nvidia-smi -q` | `gpu_temp_max_c` — absolute limit (°C), probed once at startup |
| GPU power draw | `nvidia-smi` | Per-GPU watts + TDP limit |
| PCIe RX/TX throughput | `nvidia-smi dmon` | GPU0 only; requires `interval >= 10s` |
| NVLink RX/TX throughput | `nvidia-smi dmon` | GPU0 only; requires `interval >= 10s` |
| Network throughput | `psutil` | Per interface (e.g. eth0, ib0) |
| System power (whole-machine) | `ipmitool dcmi` | BMC-based; requires `ipmitool` + BMC access |
| CPU power (package) | `intel_rapl` | RAPL CPU package power |
| CPU per-core frequency | `psutil.cpu_freq` | Opt-in via `--cpu-debug`; per logical core (MHz) |
| CPU per-sensor temperature | `psutil.sensors_temperatures` | Opt-in via `--cpu-debug`; `Core *` / `Tccd*` / `Tdie` / `Tctl` / `Package*` |
| CPU package temperature | `psutil.sensors_temperatures` | Opt-in via `--cpu-debug`; `Tdie` > `Tctl` > `Package*` |

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

- **`machines.json`** — regenerated from data files by `sync_machines.py`; one entry per machine with `hostname`, `display_name`, `cpu_type`, `cpu_count`, `gpu_type`, `gpu_count` and `latest_date` (the `YYYYMMDD` of that machine's newest data file, used to sort and label the dropdown)
- **GitHub Actions** (`.github/workflows/sync-machines.yml` at repo root) — automatically runs `sync_machines.py` and pushes updated `machines.json` whenever a new data file is pushed to `system-monitor/data/`
- **GitHub Pages** — serves the `index.html` and `data/` directory as a static site

### 3. Dashboard (`index.html`) — browser UI
Chart.js-powered SPA served directly from GitHub Pages.

- **Range selector**: Hour / Day / Week — controls the time window
- **Machine selector**: filterable and sortable — see [Finding a machine](#finding-a-machine)
- **Per-GPU charts**: each GPU gets its own colored line
- **PCIe/NVLink chart**: GPU0 PCIe RX/TX + NVLink RX/TX (hidden if no data)
- **Power chart**: per-GPU watts + system power (BMC) + CPU power (RAPL) + GPU temperature
- **CPU debug charts** (hidden unless the data has `cpu_debug: true`): per-logical-core frequency with Hide-all / L0 / L0–L15 / Show-all presets, per-sensor CPU temperature with dual-socket disambiguation, and package temperature. The two dense ones span the full grid row and use Chart.js decimation, so a 9k-sample day stays responsive with all 128 core lines visible.
- **Aggregate stats**: mean CPU %, mean GPU utilization, total GPU memory
- **Auto-refresh**: polls every 10 seconds

## Setup

### 1. Install dependencies

Nothing to do in the normal case: `collector.py` needs `psutil`, and if the
import fails it creates a venv at `./.venv`, installs `psutil` into it, and
re-executes itself under that interpreter. First start therefore takes a few
extra seconds; later starts just re-exec.

To do it by hand instead (or on a host with no network / a read-only
checkout):

```bash
pip install psutil                  # blocked by PEP 668 on Ubuntu 24.04+/Debian 12+
sudo apt install python3-psutil     # or the distro package
```

The bootstrap needs `python3 -m venv` to work — on Debian/Ubuntu that means
`sudo apt install python3-venv`, otherwise it exits with that hint rather than
crash-looping. Set `SYSMON_VENV=/path/to/venv` to put the venv somewhere other
than the checkout (useful when the checkout is read-only or `noexec`, or to
share one venv across hosts). Verify the bootstrap's error handling with:

```bash
python3 selfcheck_bootstrap.py      # offline, ~0.2s, creates no venv
```

### 2. Start the collector

```bash
# Usage: python3 collector.py <interval> <display_name>
#   <interval>    : polling interval in seconds (e.g. 10)
#   <display_name>: machine identifier used in JSON filename and frontend (e.g. XE9785L_MI355X)

# Run once to test:
python3 collector.py 10 XE9785L_MI355X            # AMD MI355X machine
python3 collector.py 10 XE9680_A100               # NVIDIA A100 machine

# PCIe/NVLink enabled (requires interval >= 10s):
python3 collector.py 10 XE9680_A100
# Smaller intervals work but PCIe/NVLink metrics are skipped:
python3 collector.py 5 XE9680_A100                 # red WARNING printed

# Or install as a systemd service (auto-starts on boot). Edit User=,
# WorkingDirectory= and the display_name in ExecStart= first:
sudo cp system-monitor.service /etc/systemd/system/
sudoedit /etc/systemd/system/system-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now system-monitor
```

> **Important**: `display_name` is required. Without it the collector exits with a usage message. Use a unique name per machine — if two machines share the same `display_name`, their data files will collide.

### 2a. Optional flags: `--cpu-debug` and `--tui`

Both are position-independent and can be combined with the two positional
arguments in any order.

```bash
# Per-core frequency + per-sensor CPU temperatures (for thermal investigations)
python3 collector.py 30 XE9785L_MI355X --cpu-debug

# Interactive nvtop-style terminal UI instead of the logging daemon
python3 collector.py 2 XE9785L_MI355X --tui
```

**`--cpu-debug`** adds five optional fields to each record — `cpu_debug`,
`cpu_core_freq_mhz`, `cpu_therm_raw`, `cpu_package_temp_c` and
`cpu_therm_temp_c` (see [Data Format](#data-format) and `DESIGN-cpu-debug.md`).
The dashboard reveals three extra charts when it sees `cpu_debug: true`; without
the flag the records are shape-identical to every other machine's and those
cards stay hidden.

> **Cost**: roughly **+2.2 KB per sample** on a 128-core box (measured 5072 vs
> ~2900 chars). At a 10s interval that is ~19 MB/day/machine in a repo you
> commit, and the per-cycle stdout line grows to 1–2 KB (every sensor plus 128
> core frequencies) which lands in the journal under systemd. **Use a 30–60s
> interval for `--cpu-debug` runs** unless you specifically need fine detail.
>
> It also depends on kernel-side facilities that are often missing on
> virtualized or locked-down hosts: `psutil.sensors_temperatures()` needs an
> hwmon driver loaded (`coretemp` / `k10temp`) and `psutil.cpu_freq()` needs
> `cpufreq` sysfs. Both fail soft to empty values, so the collector keeps
> running and the affected chart simply stays hidden.

**`--tui`** replaces the daemon with a full-screen, nvitop-inspired dashboard
built on stdlib `curses` (no `rich` / `textual` / `blessed`). Areas: SYSTEM
(CPU + MEM bars, clock, package temp, power rails), GPU (a row per GPU with
util and memory bars, temps, power against limit, PCIe and NVLink rates),
CPU CORES (`--cpu-debug` only), NETWORK, HISTORY sparklines, and a scrollable
LOG.

| Key | Action |
|---|---|
| `q` | quit |
| `space` | pause / resume sampling |
| `r` | sample now, without waiting out the interval |
| `↑` `↓` / `k` `j` | scroll the **HISTORY** series |
| `Home` | back to the first HISTORY series |
| `PgUp` `PgDn` | scroll the **LOG** one page |
| `g` | reset both: newest log line, first series |
| `?` / `h` | help overlay |

An 8-GPU box has four HISTORY series per GPU plus the system ones, so most of
them sit off-screen on a normal terminal. The panel title shows the position
(`HISTORY  3-8 of 33  ↑↓  ▲ ▼`); scroll with the arrow keys to reach the rest.

Sampling runs on its own thread, so keys respond within ~100ms even with
`--tui 60` or while `nvidia-smi dmon` is spending 7s on a sample. While a
sample is in flight the header shows `◌ sampling  took 1.5s`; `r` cannot
interrupt one already running. See `DESIGN-tui.md`, and `selfcheck_tui.py` to
verify a change.

> If resizing the window seems to do nothing, check whether `LINES`/`COLUMNS`
> are exported — ncurses honours those over the real terminal size.

> **`--tui` writes no JSON and requires a TTY** (it exits 1 otherwise). Never
> put it in a systemd unit or cron job: you would silently lose all metrics,
> and with `Restart=always` you get a 5-second crash loop. It is a developer
> convenience for watching a machine live.

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
https://github.gtie.dell.com/pages/Frank-Han1/devin/system-monitor/
```

The dashboard is a pure static SPA — no server-side logic, no authentication. Anyone with the link can view it.

## Data source

Reads (`machines.json` and the `data/` files) are fetched via **same-origin relative paths**. This works both ways with no token required:

| Where the page is served | What it reads |
|--------------------------|---------------|
| **GitHub Pages** (production) | The repo's `data/` directory served statically by Dell Enterprise Pages. Every machine that has ever been pushed is here. |
| **Local `server.py`** (dev) | Whatever is on disk in this folder on `localhost:8765`. Use while running `collector.py` locally so you see data *before* it gets pushed. |

Because reads are same-origin, there is no GitHub-vs-Local toggle — you simply open the URL that serves the data you want. Only **writes** (the Upload button) talk to the GitHub Enterprise API and need a token.

> ⚠️ **Never point reads at `raw.githubusercontent.com`.** That host is
> unreachable from the Dell network, and because `loadMachines()` runs during
> bootstrap a failure there leaves the dropdown stuck on "— Error loading
> machines —" and every chart empty. It also pins the dashboard to one specific
> repo. Relative paths resolve correctly on Dell Enterprise Pages
> (`/pages/Frank-Han1/devin/system-monitor/`), on public Pages
> (`hanyunfan.github.io/hermes/system-monitor/`) and on `localhost:8765` alike,
> so there is never a reason to hardcode a host for reads.

### One file, two sites

`index.html` is deployed **unmodified** to both this repo and the public
[`hanyunfan/hermes`](https://github.com/hanyunfan/hermes) repo. The only thing
that genuinely differs between them is the write API, so the file detects it
from `location.hostname` via the `SITES` table instead of being re-adapted per
site:

| Origin | Upload target | Token page |
|--------|---------------|------------|
| `*.gtie.dell.com` | `https://github.gtie.dell.com/api/v3` → `Frank-Han1/devin` | `github.gtie.dell.com/settings/tokens` |
| anything else (incl. `localhost`) | `https://api.github.com` → `hanyunfan/hermes` | `github.com/settings/tokens/new` |

This means the file can be copied verbatim in **either** direction whenever one
side gets a fix — which is the whole point. To add a third deployment, add a row
to `SITES`; don't fork the file.

Note that GitHub Actions is disabled on the Dell Enterprise instance (0
workflows, 0 runs), so `sync-machines.yml` never fires there and the dashboard
always rewrites `machines.json` from the browser after an upload. On a site
where the workflow *does* run this is simply idempotent and saves the 10–30s
wait, so it is not conditional on the detected site.

## Finding a machine

The list grows one entry per `display_name` per machine, so it gets long fast.
Three controls sit next to the dropdown:

| Control | Behaviour |
|---------|-----------|
| **filter box** | Substring match, case-insensitive. Space-separated terms are **ANDed**, so `mi355 overheat` narrows to the runs matching both. Matches the name, `gpu_type`, `cpu_type` and the displayed date — `epyc`, `rtx_pro` and `2026-08` all work. |
| **count** | `matched/total`, so you can see at a glance whether the filter is too tight. Turns red at zero. |
| **sort** | `↓ newest data` (default), `A–Z by name`, or `group by GPU` (uses `<optgroup>` with per-group counts). Persisted in `localStorage`. |

Keyboard: **`/`** focuses the filter from anywhere, **Esc** clears it, and
**Enter** selects the machine when the filter has narrowed to exactly one.

Each entry reads `name · GPU xN · latest date`, e.g.
`XE9785L_MI355X_overheating_cpu_debug · Instinct_MI355_OAM x8 · 2026-06-15`.

Two details worth knowing:

- **Filtering never changes which machine is displayed.** The selected machine
  stays in the list even when it fails the filter, so typing can't silently
  swap the charts out from under you.
- **A leading `metrics_` in a `display_name` is stripped for display and
  sorting.** A few machines were collected with the filename prefix baked into
  the name (`metrics_XE7740_RTXPro6000_llama2_inference`); left alone, those
  sort under *m*, nowhere near their siblings. The underlying value is
  untouched, since that is what `setMachine()` matches against.

The date comes from `latest_date` in `machines.json`, which
`sync_machines.py` records from the newest data filename per machine — no
extra requests. Entries written before that field existed simply show no date
and sort last.

## Uploading a JSON file from the dashboard

The **⬆ Upload JSON** button on the top bar pushes a `metrics_*.json` file to the `Frank-Han1/devin` repo via the Dell Enterprise [Contents API](https://docs.github.com/en/rest/repos/contents) (`https://github.gtie.dell.com/api/v3`). The flow is:

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

1. Visit <https://github.gtie.dell.com/settings/tokens> (or **Settings → Developer settings → Personal access tokens**)
2. Pick **Fine-grained token** (recommended) or **Tokens (classic)**
3. Resource owner: your account. Repository access: **Only select repositories → Frank-Han1/devin**
4. Permissions → **Contents: Read and write** (classic: the `repo` scope)
5. Generate, copy the token (you'll only see it once)
6. In the dashboard, click **⬆ Upload JSON** → a prompt asks for the token. Paste it.
7. The token is stored in your browser's `localStorage` under `systemMonitorGithubPAT`. It is **never** sent anywhere except `github.gtie.dell.com`.

To clear the token: open DevTools → Application → Local Storage → delete the `systemMonitorGithubPAT` key, or just call `localStorage.removeItem('systemMonitorGithubPAT')` in the console.

### What happens if the PAT is wrong / expired

The dashboard clears it from localStorage and asks for a new one. Old token isn't recoverable — generate a new one in the GitHub settings.

### Why no PAT-prompt UI outside the upload button

The read paths (viewing machines, charts) are same-origin fetches served by GitHub Pages, so no token is required to view the dashboard. Only writes (uploads) need a token. So you can hand the dashboard URL to anyone without giving them a token.

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
| `gpu_temp_max_c` | float[] or null | Absolute throttle temperature per GPU (°C), probed once from `nvidia-smi -q`. Null on AMD and where the driver reports only `T.Limit` offsets. The dashboard's throttle line falls back to 100 °C when absent. |
| `gpu` | array or null | Per-GPU stats (see below); null if no GPU |

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

### `--cpu-debug` fields (optional)

Only present when the collector ran with `--cpu-debug`. Every field above keeps
its name, order, type and units, so **the schema is a strict superset** — a
dashboard or script written against the base format reads these files unchanged,
and these five keys are simply absent otherwise.

| Field | Type | Description |
|-------|------|-------------|
| `cpu_debug` | `true` | Gate flag. The dashboard reveals the CPU charts only when a loaded sample has this. |
| `cpu_core_freq_mhz` | float[] | Per **logical** core frequency (MHz), indexed by `psutil.cpu_freq(percpu=True)` order. `[]` if `cpufreq` sysfs is unavailable. |
| `cpu_therm_temp_c` | (float\|null)[] | Per-sensor temperature (°C), indexed by `cpu_therm_raw` **dump order after filtering** to `Core *` / `Tccd*` / `Tdie` / `Tctl` / `Package*`. |
| `cpu_package_temp_c` | float or null | Socket temperature (°C), picked `Tdie` > `Tctl` > `Package*`. |
| `cpu_therm_raw` | object | Unfiltered `psutil.sensors_temperatures()` dump: `{chip: [{label, current, high, critical}]}`. Includes non-CPU chips (`nvme`, `acpitz`, …). |

> **Index contract**: `cpu_therm_temp_c` is indexed by *filtered* sensor order
> while `cpu_therm_raw` is *unfiltered*. Anything reconstructing the array from
> raw must apply the same filter — see `isCpuThermLabel()` in `index.html`,
> which mirrors `get_cpu_therm_temp_c()` in `collector.py`. Skipping the filter
> shifts every label by however many NVMe/ACPI sensors the machine exposes.
> `selfcheck.js` asserts the two stay in agreement.
>
> Note `cpu_core_freq_mhz` is per **logical** core and `cpu_therm_temp_c` is per
> **sensor** — the two arrays have different lengths by design.
>
> `DESIGN-cpu-debug.md` also specifies a `cpu_core_temp_c` field. It was never
> implemented (it would have been Intel-only); the three fields above replaced
> it.

## Project Files

| File | Purpose |
|------|---------|
| `collector.py` | Daemon — samples and writes metrics to `data/`. Also `--cpu-debug` and `--tui`. |
| `index.html` | Dashboard — Chart.js SPA served via GitHub Pages. Deployed unmodified to both sites. |
| `selfcheck.js` | `node selfcheck.js` — asserts the dashboard's site detection, CPU-sensor filter parity with `collector.py`, and chart gating against the real `data/` files |
| `selfcheck_tui.py` | `python3 selfcheck_tui.py` — asserts the `--tui` rendering helpers, sample folding and key decoding, plus a pty smoke test of the curses UI |
| `selfcheck_bootstrap.py` | `python3 selfcheck_bootstrap.py` — asserts the psutil venv bootstrap's error paths (offline, builds no venv) |
| `server.py` | Optional local HTTP server (dev only, port 8765) |
| `sync_machines.py` | Rebuilds `machines.json` from data files (tolerates corrupt/placeholder files). `build()` is the single definition of an entry's shape. |
| `gen_machines.py`, `regen_machines.py` | Thin aliases for `sync_machines.build()` — kept as entry points, no longer copies |
| `machines.json` | Auto-generated machine list incl. `latest_date` |
| `DESIGN-cpu-debug.md` | Design notes for the `--cpu-debug` fields |
| `DESIGN-tui.md` | Design notes for the `--tui` terminal UI |
| `.github/workflows/sync-machines.yml` | GitHub Actions: auto-syncs machines.json on data changes (**never runs on the Dell instance — Actions is disabled**) |
| `data/` | JSON Lines data files (one per machine per UTC date) |

## Verifying a change

```bash
node selfcheck.js        # dashboard logic (no browser, no network needed)
python3 server.py        # then open http://localhost:8765 for a visual check
```

`selfcheck.js` extracts the inline `<script>` from `index.html`, stubs the
handful of browser APIs it touches, and runs the CPU-debug chart logic against
the real files in `data/`. It catches the failures that are otherwise invisible
until someone opens the page: the sensor filter drifting out of sync with the
collector, dual-socket sensors collapsing into one line, the chart visibility
gate disagreeing between the Calendar and Day views, and the Chart.js
decimation requirements being broken by a stray `new Date()`.

## Troubleshooting

**"No data for this range"**: Check that the collector daemon is running (`ps aux | grep collector`), and that data has been pushed to GitHub.

**GPU charts show "N/A"**: The `machines.json` may be stale. Push a new data file — GitHub Actions will automatically regenerate `machines.json`. Or manually run `python3 sync_machines.py`.

**Old data in browser**: GitHub Pages can cache aggressively. Hard-refresh with `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac), or open DevTools → Network → disable cache.

**PCIe/NVLink chart shows no data**: This is expected if the collector was started with `interval < 10s`. Restart with `python3 collector.py 10 <display_name>`. The red WARNING message confirms this. (Note there is no `--interval` flag — the interval is the first positional argument, and `--interval 10` would fail with a `ValueError`.)

**CPU frequency / thermal charts don't appear**: They only unhide when a loaded sample has `cpu_debug: true`, i.e. the collector ran with `--cpu-debug`. If it did and they're still hidden, the machine has no readable sensors — check `python3 -c "import psutil; print(psutil.sensors_temperatures())"` and `psutil.cpu_freq(percpu=True)`. Both need kernel support (`coretemp`/`k10temp` hwmon, `cpufreq` sysfs) that is often absent in VMs and containers.

**Dropdown stuck on "— Error loading machines —"**: `machines.json` failed to fetch. On the Dell network this is almost always because a read was pointed at an external host — reads must stay same-origin relative. See [Data source](#data-source).

**system_power_w is null**: Confirm `ipmitool dcmi power reading` works on that machine and that the BMC has DCMI permissions.

**Multiple collectors on same display_name**: Only one collector per `display_name` should run, otherwise data files will interleave and corrupt each other.
