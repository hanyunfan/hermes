# TUI Mode for collector.py — Design Doc (v2)

> Status: v2 implemented, supersedes the v1 single-frame design.
> Date: 2026-06-19 (v1) → 2026-06-19 (v2)
> Author: Frank (direction) + Claude (drafted + implemented)

## Goal

Render an interactive nvtop-style terminal UI on the local TTY instead
of writing JSON. The UI must:

1. **Fill the screen** (no big white gaps at the bottom)
2. **Show real-time log strip** like nvtop's bottom event pane
3. **Mirror the dashboard** — every chart card in `index.html`
   should have a TUI counterpart (sparkline + current value)

## v1 → v2 changes

| v1 issue | v2 fix |
|---|---|
| 8 lines of content + blank rows below | 3-layer layout fills the terminal |
| Only current snapshot, no history | Sparklines over a 60-sample ring buffer per series |
| No event log | Bottom strip: last N samples as one-line summaries, scrollable with ↑↓ |
| 5 metrics shown | 11+ metrics — one sparkline per webpage chart (CPU util / MEM / GPU util / GPU mem / GPU power / GPU temp / Net RX / Net TX / PCIe+NVLink / CPU temp / CPU core freq) |

## Layout (3-layer, fits 80×24+ terminals)

```
╭─ frank-XPS-8960 ───── 14:24:42 ──── 2s ── 28c/56t ────────╮
│  ← L1: Top stat strip (3-4 rows, current snapshot + bars) │
│  CPU  i7-14700K   ░░░░░░░░░░░░░░░░░░░░   0.1%  1.8GHz    │
│  MEM  DDR5 31G    ██░░░░░░░░░░░░░░░░░░   8.5%  2.6G/31G  │
│  SYS  62W (CPU=9W)                                         │
│  GPU0 L4 AD104    ░░░░░░░░░░░░░░░░░░░░   0%  32°C  0W     │
│  ... GPU1 ...                                              │
│  NET  enp3s0 RX=0.0 TX=0.0 MB/s                            │
├────────────────────────────────────────────────────────────┤
│  ← L2: Sparkline grid (one row per metric, scrolls history)│
│  CPU  %        ▆▆▅▄▃▂▁▁▂▃▅▆▇▆▅   0.1% / 100%             │
│  MEM  %        ██▆▅▃▂▂▃▄▅▆▇▆▅▆   8.5%                    │
│  GPU0 util     ░▁▂▃▅▆▇▆▅▃▂▁▂▃▅▆   0% / 100%              │
│  GPU0 mem      ████████████████  4500M/24G                 │
│  GPU0 power    ▆▇▆▅▃▂▁▁▂▃▄▅▆▇▆   280W/350W               │
│  GPU0 temp     ▆▆▆▇▇▇▆▆▅▅▅▆▇▇▇   72°C / 95°C             │
│  NET  RX       ▃▄▅▆▇▆▅▄▃▂▁▂▃▄▅▆▆   124 MB/s              │
│  NET  TX       ▁▂▃▂▁▁▂▃▄▅▆▇▆▅▄▃   89 MB/s               │
│  PCIe+NVLink   ▂▃▄▃▂▁▁▂▃▄▅▆▇▆▅   1.2GB/s                 │
│  CPU temp °C   ▅▆▇▇▆▅▄▃▃▄▅▆▇▇▆   48°C k10temp.Tctl       │  ← only with --cpu-debug
│  CPU freq MHz  ▆▇▆▅▄▃▂▂▃▄▅▆▇▆▅   L0=4200MHz              │  ← only with --cpu-debug
├────────────────────────────────────────────────────────────┤
│  ← L3: Log strip (nvtop-style event pane, scrollable)     │
│  14:24:42  CPU=0.1% MEM=8.5% GPU0=0% T=32°C P=0W ...    │
│  14:24:40  CPU=2.3% MEM=8.5% GPU0=12% T=33°C P=15W ...   │
│  14:24:38  CPU=5.1% MEM=8.6% GPU0=24% T=34°C P=42W ...   │
│  ↑↓: scroll log     PgUp/PgDn: page     G: jump to latest │
├────────────────────────────────────────────────────────────┤
│  q quit  space pause  r refresh  ?: help                 │
╰────────────────────────────────────────────────────────────╯
```

## Code shape

### New module-level components

```python
import shutil     # terminal_size

# Unicode block-element sparkline characters, low → high.
_SPARK = "▁▂▃▄▅▆▇█"

class _RingBuf:
    """Fixed-size ring buffer of floats. .append(v) adds, .values() reads
    in insertion order. Used to feed sparklines with N most-recent samples."""
    def __init__(self, cap): self.cap = cap; self._d = collections.deque(maxlen=cap)
    def append(self, v):    self._d.append(v)
    def values(self):        return list(self._d)

def _sparkline(buf, width, vmin=None, vmax=None):
    """Render a sparkline of `width` chars from a _RingBuf.
    Auto-scales to [vmin, vmax] if not given (NaN-safe)."""
    vals = buf.values()
    if not vals: return " " * width
    if vmin is None: vmin = min(vals)
    if vmax is None: vmax = max(vals)
    span = max(1e-9, vmax - vmin)
    # Take the most recent `width` samples
    vals = vals[-width:]
    out = []
    for v in vals:
        idx = int((v - vmin) / span * (len(_SPARK) - 1))
        idx = max(0, min(len(_SPARK) - 1, idx))
        out.append(_SPARK[idx])
    # Pad left if we don't have enough history yet
    return (" " * (width - len(out))) + "".join(out)
```

### TUI state (lives in `tui()` local scope, passed to `_tui_render`)

```python
@dataclass-like dict
state = {
    "history": {           # _RingBuf per series, cap=120 (= 4 min @ 2s)
        "cpu_pct": _RingBuf(120),
        "mem_pct": _RingBuf(120),
        "gpu_util": [_RingBuf(120) for _ in range(8)],
        "gpu_mem":  [_RingBuf(120) for _ in range(8)],
        "gpu_pwr":  [_RingBuf(120) for _ in range(8)],
        "gpu_temp": [_RingBuf(120) for _ in range(8)],
        "net_rx":   _RingBuf(120),
        "net_tx":   _RingBuf(120),
        "pcie":     _RingBuf(120),
        "cpu_temp": _RingBuf(120),
        "cpu_freq": _RingBuf(120),
    },
    "log":       collections.deque(maxlen=200),  # scrollable event log
    "log_scroll": 0,                              # 0 = newest at bottom; +N = scrolled up N
    "paused":    False,
}
```

### Render function

```python
def _tui_render(state, interval):
    cols, rows = shutil.get_terminal_size((80, 24))
    # Allocate vertical space: top strip ≤ 6 rows, sparklines dynamic, log ≤ 8 rows
    LOG_ROWS = min(8, max(3, rows // 5))
    TOP_ROWS = min(8, max(4, (rows - LOG_ROWS) // 4))
    SPARK_ROWS = rows - TOP_ROWS - LOG_ROWS - 4   # 4 for separators + footer
    spark_w = cols - 32   # leave room for label + current value + units

    out = []
    out += _render_top(state, TOP_ROWS)            # current snapshot
    out += [_tui_separator(cols)]
    out += _render_sparks(state, SPARK_ROWS, spark_w)
    out += [_tui_separator(cols)]
    out += _render_log(state, LOG_ROWS, cols, log_scroll)
    out += [_tui_footer(state, cols)]
    sys.stdout.write("\033[H" + "\n".join(out) + "\033[J")
```

### Key bindings (extended)

| Key | Action |
|---|---|
| q / Q / Ctrl-C | quit (terminal restored) |
| space | pause/resume data collection |
| r | force-refresh (skip sleep, re-collect now) |
| ↑ / ↓ | scroll log strip up/down |
| PgUp / PgDn | page through log |
| G / g | jump log to newest |
| ? | toggle a help overlay (TODO if needed) |

### Terminal-size adaptivity

- ≥80×24: full layout (3 layers)
- <24 rows: collapse sparkline grid to 1 row per metric (or auto-truncate)
- <80 cols: shrink sparkline width, abbreviate labels ("CPUu" instead of "CPU util")

## Edge cases

1. **No GPU**: skip all GPU sparklines + GPU top rows
2. **No network**: skip NET sparkline, top NET row shows "—"
3. **No system_power_w**: skip SYS top row, no power sparkline
4. **No per-core data** (no `--cpu-debug`): skip CPU temp + CPU freq sparklines
5. **Terminal too small**: truncate rows from the bottom (log first, then sparklines)
6. **TTY shrinks during runtime**: `SIGWINCH` re-renders with new dims on next cycle
7. **History not yet full** (< width samples): sparkline left-pads with spaces

## Testing plan

```bash
# 1. Local smoke (Intel i7-14700K + L4 GPU no nvidia-smi, no --cpu-debug)
python3 collector.py --tui 2 test
# Expected: 3-layer TUI fills 80×24, ~5-7 sparklines visible, log strip scrolls

# 2. With --cpu-debug
python3 collector.py --tui 2 test --cpu-debug
# Expected: extra CPU temp + freq sparklines appear

# 3. Resize terminal mid-run
# resize the window narrower → sparkline width adjusts

# 4. Scroll log
# press ↓ a few times → log scrolls up, showing older samples

# 5. Non-TTY
python3 collector.py --tui 2 test | head
# Expected: clean error, exit 1

# 6. Pause + resume
# press space → log strip shows ⏸ PAUSED, no new data
# press space again → resumes
```

## Diff estimate (v1 → v2)

- ~200 lines removed (the old _tui_render + its hand-built layout)
- ~350 lines added (history buffers, sparkline helper, 3-layer layout, scroll)
- ~30 lines changed in tui() main loop (key handling for ↑↓ etc.)
- ~10 lines changed in __main__ (no behaviour change, just usage text)
