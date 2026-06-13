# Design: CPU Debug Mode (per-core temp + frequency)

> Status: **Design draft — awaiting user approval before implementation.**
> Author: frank's assistant, 2026-06-12

## Goal

Add an **opt-in "CPU debug" mode** to `collector.py` that, when enabled, records
per-core CPU temperature and per-core CPU frequency, and surfaces them as
**two new hidden-by-default charts** on the dashboard.

Hard constraints (from user):

- **Default behaviour must be unchanged** — current collector users see no
  output, no JSON-shape change, no UI change.
- **Enabled by a flag**, currently planned as a 3rd positional CLI arg
  (`--cpu-debug`) so it doesn't break existing systemd invocations
  (`python3 collector.py 10 XE9785L_MI355X` keeps working).
- The two new charts are **always present in the HTML** but `display:none` —
  they only become visible when the loaded data file actually carries the
  per-core fields, so old data is unaffected.

## Data sources (verified on the dev machine, 2026-06-12)

| Source | API | Works without sudo? | Coverage |
|--------|-----|---------------------|----------|
| Per-core temperature | `psutil.sensors_temperatures()` | Yes (psutil ≥ 5.5) | `coretemp` (Intel) / `k10temp` (AMD Zen) — physical cores |
| Per-core frequency  | `psutil.cpu_freq(percpu=True)` | Yes (reads `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq`) | All logical cores |

Verified on the dev box (`Intel i7-14700K, 28 logical / 20 physical cores`):

- `sensors_temperatures()['coretemp']` returns 20 entries labelled
  `Core 0, Core 4, Core 8, Core 12, ...` — physical-core IDs, not
  contiguous.
- `cpu_freq(percpu=True)` returns 28 entries — one per logical core,
  matching `psutil.cpu_count(logical=True)`.

This means the two new fields have **different cardinalities** (physical vs
logical) — see "Why two separate arrays" below.

## Why two separate arrays, not one merged "core[]" array

`cpu_freq` reports one entry per **logical** core (HT siblings share or
differ). `sensors_temperatures` reports one entry per **physical** core
(coretemp labels are physical-core indices). On an HT-enabled CPU the two
lists have different lengths and different IDs.

- Merging them under a single `cpu_cores` array would force an arbitrary
  mapping (e.g. logical 0+1 → physical 0) and a 1:N relationship that the
  chart code would have to special-case.
- Keeping them as **two separate, flat, dense arrays** in the JSON makes the
  frontend trivial: one chart per array, one dataset per index. The user
  can correlate the two by index when needed.

So the JSON adds:

```json
{
  "cpu_debug": true,            // <-- new flag, surfaces the charts
  "cpu_core_temp_c":  [37.0, 40.0, 42.0, ...],  // physical cores, null on AMD Zen1
  "cpu_core_freq_mhz": [4615.9, 800.0, 800.0, ...] // logical cores
}
```

When `cpu_debug` is `false` (or absent), **neither key is written** and the
charts stay hidden.

## Collector changes (collector.py)

### 1. CLI

```python
def usage():
    print("Usage: python3 collector.py <interval> <display_name> [--cpu-debug]")

if __name__ == "__main__":
    _probe_gpu()
    args = sys.argv[1:]
    cpu_debug = "--cpu-debug" in args
    if cpu_debug:
        args.remove("--cpu-debug")
    if len(args) < 2:
        usage(); sys.exit(1)
    interval, name = int(args[0]), args[1]
    daemon(interval, name, cpu_debug=cpu_debug)
```

`daemon()` signature gains `cpu_debug: bool`, defaulting to `False` so
`daemon(10, "name")` keeps working.

### 2. Module-level flag + probe

```python
CPU_DEBUG = False

def get_cpu_core_temp():
    """Return list[float|None] indexed by physical core id, or [] on failure.
    Length equals number of physical cores that have a sensor entry.
    """
    try:
        s = psutil.sensors_temperatures(fahrenheit=False).get("coretemp", [])
        if not s:
            # AMD Zen path — k10temp only exposes Tctl/Tdie, not per-core.
            return []
        out = []
        for t in s:
            if t.label and t.label.startswith("Core "):
                # parse "Core 0", "Core 12", etc.
                try:
                    idx = int(t.label.split()[1])
                except (ValueError, IndexError):
                    continue
                # dense-pack at physical index, None for gaps
                while len(out) <= idx:
                    out.append(None)
                out[idx] = t.current
        return out
    except Exception as e:
        if _CPU_DEBUG_VERBOSE:
            print(f"[cpu_debug] temp probe failed: {e}")
        return []

def get_cpu_core_freq():
    """Return list[float] indexed by logical core id, [] on failure.
    Length equals psutil.cpu_count(logical=True).
    """
    try:
        f = psutil.cpu_freq(percpu=True)
        if not f:
            return []
        return [round(c.current, 1) for c in f]
    except Exception as e:
        if _CPU_DEBUG_VERBOSE:
            print(f"[cpu_debug] freq probe failed: {e}")
        return []
```

These are **safe to call when `cpu_debug=False`** — they return `[]` and
the cost is one psutil syscall (negligible vs the existing 10s interval).

### 3. `collect()` writes the new fields only when enabled

```python
def collect(enable_nvlink=True, cpu_debug=False):
    # ... existing code unchanged ...
    stats = { ... existing fields ... }
    if cpu_debug:
        stats["cpu_debug"]  = True
        stats["cpu_core_temp_c"]  = get_cpu_core_temp()   # per physical core
        stats["cpu_core_freq_mhz"] = get_cpu_core_freq()  # per logical core
    return stats
```

When `cpu_debug=False` (default) the JSON line is **byte-identical** to
today's output.

### 4. Daemon plumbs the flag

```python
def daemon(interval=10, _display_name=None, cpu_debug=False):
    # ... existing code ...
    if cpu_debug:
        print("CPU debug mode ENABLED — per-core temp + freq will be recorded")
    while True:
        try:
            stats = collect(enable_nvlink=enable_nvlink, cpu_debug=cpu_debug)
            # ... rest unchanged ...
            if cpu_debug:
                debug_str = ""
                temps = stats.get("cpu_core_temp_c") or []
                freqs = stats.get("cpu_core_freq_mhz") or []
                if temps:
                    debug_str += f" Tcore=[{','.join(f'{t:.0f}' if t is not None else '-' for t in temps)}]"
                if freqs:
                    debug_str += f" Fcore=[{','.join(f'{f:.0f}' for f in freqs)}]"
                print(f"{debug_str}", end="")  # append to the existing log line
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(interval)
```

## Frontend changes (index.html)

### 1. Two new chart cards, hidden by default

In the `.charts` grid, after the existing `temp-chart-card`:

```html
<div class="chart-card" id="cpu-core-temp-chart-card" style="display:none">
  <h3>CPU Core Temperature (°C, per physical core)</h3>
  <div class="chart-wrapper"><canvas id="chart-cpu-core-temp"></canvas></div>
</div>
<div class="chart-card" id="cpu-core-freq-chart-card" style="display:none">
  <h3>CPU Core Frequency (MHz, per logical core)</h3>
  <div class="chart-wrapper"><canvas id="chart-cpu-core-freq"></canvas></div>
</div>
```

### 2. Two new chart builders (mirror `buildTempChart`)

```js
function buildCpuCoreTempChart(canvasId) {
  // Up to 64 datasets — physical cores typically ≤ 32, allow headroom
  const datasets = Array.from({ length: 64 }, (_, i) => {
    const color = CORE_COLORS[i % CORE_COLORS.length];
    return { label: 'P' + i, data: [], borderColor: '#' + color,
             backgroundColor: 'transparent', borderWidth: 1,
             hidden: true, pointRadius: 0 };
  });
  const chart = new Chart(document.getElementById(canvasId), {
    type: 'line',
    data: { datasets },
    options: {
      ...chartOptions(),
      scales: {
        ...chartOptions().scales,
        y: { min: 0, max: 100, grid: { color: '#252a3a' }, ticks: { color: '#666' } }
      }
    }
  });
  return chart;
}

function buildCpuCoreFreqChart(canvasId) {
  // Up to 128 datasets — logical cores typically ≤ 64 with HT
  const datasets = Array.from({ length: 128 }, (_, i) => {
    const color = CORE_COLORS[i % CORE_COLORS.length];
    return { label: 'L' + i, data: [], borderColor: '#' + color,
             backgroundColor: 'transparent', borderWidth: 1,
             hidden: true, pointRadius: 0 };
  });
  const chart = new Chart(document.getElementById(canvasId), {
    type: 'line',
    data: { datasets },
    options: {
      ...chartOptions(),
      scales: {
        ...chartOptions().scales,
        y: { min: 0, grid: { color: '#252a3a' }, ticks: { color: '#666' } }
      }
    }
  });
  return chart;
}

// New colour palette — 16 distinct, high-contrast on dark background.
// (Distinct from GPU_COLORS to avoid colour-collision on machines with 8 GPUs.)
const CORE_COLORS = [
  '4fc3f7','ba68c8','81c784','ffb74d','ef9a9a','ffee58','80cbc4','ce93d8',
  '90a4ae','a1887f','bcaaa4','dce775','aed581','fff176','ff8a65','b39ddb'
];
```

### 3. Two new updaters (mirror `updateTempChart`)

```js
function updateCpuCoreTempChart(allData) {
  // Discover max populated index across all samples
  let maxIdx = -1;
  for (const d of allData) {
    const arr = d.cpu_core_temp_c || [];
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i] != null) { maxIdx = Math.max(maxIdx, i); break; }
    }
  }
  if (maxIdx < 0) return; // no data — keep hidden

  const datasets = charts['cpu-core-temp'].data.datasets;
  for (let i = 0; i <= maxIdx; i++) {
    datasets[i].hidden = false;
    datasets[i].data = allData.map(d => {
      const t = (d.cpu_core_temp_c || [])[i];
      return t != null ? { x: new Date(d.timestamp), y: t } : { x: new Date(d.timestamp), y: null };
    });
  }
  // Auto-scale y to 1.1x observed max, floor 80°C
  const allT = allData.flatMap(d => (d.cpu_core_temp_c || []).filter(t => t != null));
  const max = allT.length ? Math.max(...allT) : 0;
  charts['cpu-core-temp'].options.scales.y.max = Math.max(80, Math.ceil(max * 1.1 / 10) * 10);
  charts['cpu-core-temp'].update();
}

function updateCpuCoreFreqChart(allData) {
  let maxIdx = -1;
  for (const d of allData) {
    const arr = d.cpu_core_freq_mhz || [];
    if (arr.length) maxIdx = Math.max(maxIdx, arr.length - 1);
  }
  if (maxIdx < 0) return;

  const datasets = charts['cpu-core-freq'].data.datasets;
  for (let i = 0; i <= maxIdx; i++) {
    datasets[i].hidden = false;
    datasets[i].data = allData.map(d => {
      const f = (d.cpu_core_freq_mhz || [])[i];
      return f != null ? { x: new Date(d.timestamp), y: f } : { x: new Date(d.timestamp), y: null };
    });
  }
  const allF = allData.flatMap(d => d.cpu_core_freq_mhz || []);
  const max = allF.length ? Math.max(...allF) : 0;
  charts['cpu-core-freq'].options.scales.y.max = Math.max(2000, Math.ceil(max * 1.1 / 100) * 100);
  charts['cpu-core-freq'].update();
}
```

### 4. Visibility logic in `loadDayData`

After the existing chart-update calls, add:

```js
// Show CPU debug charts only if any sample carries the cpu_debug flag
const hasCpuDebug = allData.some(d => d.cpu_debug === true);
document.getElementById('cpu-core-temp-chart-card').style.display = hasCpuDebug ? '' : 'none';
document.getElementById('cpu-core-freq-chart-card').style.display = hasCpuDebug ? '' : 'none';
if (hasCpuDebug) {
  updateCpuCoreTempChart(allData);
  updateCpuCoreFreqChart(allData);
}
```

**Old data (no `cpu_debug` key) → charts stay hidden.** No migration
needed. **New data without `--cpu-debug` flag → charts stay hidden.** Only
data collected with the flag surfaces the charts.

### 5. Dataset-index bound guard

The build functions pre-allocate 64 / 128 dataset slots but mark all
`hidden:true`. `update*Chart` flips them to `hidden:false` only for the
indices that actually have data. This matches the existing `buildTempChart`
pattern (pre-allocate 8, show only `gpuCount`).

## What I will NOT change

- `machines.json` — no per-machine metadata needed; the new fields are
  self-describing.
- `sync_machines.py` — it only inspects `gpu_count`/`gpu_type`; it
  silently ignores unknown fields.
- The systemd service file — users opt in by editing the `ExecStart=` line
  to add `--cpu-debug`. **No file change needed**; documented in README.
- `server.py` — no changes.
- The `systemMonitorGithubPAT` upload flow — no changes.
- Existing chart builders / updaters — only **add** new functions, don't
  edit old ones.

## Backwards-compatibility matrix

| Scenario | Collector CLI | JSON new fields? | Charts visible? |
|----------|---------------|------------------|-----------------|
| Existing user, no service file change | `python3 collector.py 10 name` | ❌ none | ❌ hidden |
| Existing user, adds `--cpu-debug` | `python3 collector.py 10 name --cpu-debug` | ✅ `cpu_debug=true` + two arrays | ✅ visible |
| Old data file (pre-feature) | (no CLI change) | (no key in JSON) | ❌ hidden (because `d.cpu_debug !== true`) |
| Mixed old + new data on the same day | `append_to_file` — both kinds coexist | mixed | visible only for the new samples |

## Test plan

1. **CLI**: `python3 collector.py 10 test_$(date +%s) --cpu-debug` runs for
   ~30s, produces a JSON line. Verify it has `cpu_debug: true`,
   `cpu_core_temp_c: [20+ floats, some null]`, `cpu_core_freq_mhz: [28 floats]`.
2. **Default unchanged**: `python3 collector.py 10 test_$(date +%s)` produces
   a JSON line with **no** new keys (byte-for-byte shape match against a
   pre-change baseline).
3. **Dashboard load**: open the local server with the new file selected;
   verify the two new chart cards become visible and render lines.
4. **Old data**: select a date that predates the change; verify the two
   new cards stay `display:none`.
5. **AMD Zen fallback**: on a machine where `coretemp` is absent
   (k10temp-only), verify `cpu_core_temp_c` is `[]` (no crash), the
   freq chart still renders.

## Estimated diff size

| File | Lines added | Lines changed | Net |
|------|-------------|---------------|-----|
| `collector.py` | ~70 | ~10 | +60 |
| `index.html` | ~100 | ~5 | +95 |
| `README.md` | ~25 | ~2 | +23 |
| `DESIGN-cpu-debug.md` | (this file) | — | +200 |
| **Total** | **~395** | **~17** | **+378** |

## Open questions for the user (none blocking)

- Y-axis for frequency: floor `2000 MHz`? (vs the typical 800 MHz idle
  floor, this lets the chart zoom into the active range). **Default 2000
  MHz, editable later.**
- Should we add a small "min/avg/max" stat card for `cpu_core_temp_c`?
  **No, keep this PR tight** — only the two charts and the CLI flag.
  Stats cards can come in a follow-up.

## Implementation order (once approved)

1. `collector.py` — add `get_cpu_core_temp`, `get_cpu_core_freq`,
   `--cpu-debug` flag, plumb through `daemon()` and `collect()`.
2. `index.html` — add two hidden chart cards, two `build*` functions,
   two `update*` functions, visibility branch in `loadDayData`.
3. `README.md` — add a one-paragraph section under Features, add
   `--cpu-debug` to the CLI examples.
4. Manual test on the dev box, then push.
