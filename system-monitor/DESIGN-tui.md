# TUI Mode for collector.py — Design Doc (v3)

> Status: v3 implemented, replaces the v2 hand-rolled ANSI renderer.
> Date: 2026-06-19 (v1, v2) → 2026-09-02 (v3)

## Goal

An interactive, nvitop-inspired dashboard on the local TTY instead of writing
JSON. It must fill the screen with distinct areas, show everything `collect()`
gathers, and stay responsive to keys regardless of the sample interval.

## Why v2 was rewritten

v2 looked broken in practice, for four compounding reasons:

1. **It sampled exactly once.** Its sleep loop was

   ```python
   while slept < interval:
       key = _read_key_nonblocking(slice_s)
       if not key: continue     # skips the slept += below
       ...
       slept += slice_s
   ```

   `slept` only advanced when a key arrived, so with no input the loop spun
   forever and `collect()` never ran again. Every sparkline held one sample,
   which is what "most places are empty" was.

2. **Keys never worked.** Nothing ever put the terminal into cbreak/raw mode —
   there was no `termios` or `tty.setcbreak` call in the file — so stdin stayed
   line-buffered and `select()` reported nothing until Enter. Pause, refresh and
   scroll were all unreachable.

3. **Sampling blocked the UI.** `collect()` runs on the caller's thread and
   takes 0.5s (`cpu_percent`) to ~10s (`nvidia-smi dmon`). Even with 1 and 2
   fixed, input could not be serviced while a sample was in flight.

4. **The GPU row was malformed.** A ternary wrapped an entire f-string, so the
   row rendered as `GPU0 RTX_PRO_2000_B ░░░ 0% ? ?W`.

A separate collector bug made the GPU columns useless on consumer boards:
`nvidia-smi` returns `[N/A]` for `temperature.gpu.tlimit`, and `float()` on
that raised, so the whole `gpu_power` record was replaced by `{"error": ...}`.
Fixed by `_smi_float()`, which is a data-quality fix for daemon mode too, not
just the TUI.

## v3: curses

`curses` is stdlib and owns exactly the machinery v2 got wrong — cbreak,
noecho, timed `getch`, resize, colour — so the hand-rolled ANSI writer, the
escape parser and the sleep loop are all deleted (689 lines replaced by ~750,
most of the growth being panels and comments).

### Threading

```
_Sampler (daemon thread)          curses loop (main thread)
  collect()  ── Queue ──────────►  drain queue, fold into ring buffers
  wait(interval) or wake Event     getch(timeout=100ms), redraw at ~10fps
```

Keys are serviced within `_TICK_MS` (100ms) no matter how long a sample takes
or how large the interval is. `r` fires the sampler's wake Event; it cannot
interrupt a collect already running, so the header shows `◌ sampling` with the
elapsed cost (`took 1.5s`) rather than appearing to ignore the keypress.

### Screen areas

```
 system-monitor  HOST [display_name]        ● live  16:45:13Z  every 3s  next 0.4s  n=6
── SYSTEM ──────────────────────────────────────────────────────────────────────
 CPU Ultra 7 265H     ░░░░░░░░░░░░░░░   0.3%  16C/16T  3.69GHz  47°C
 MEM                  ██░░░░░░░░░░░░░   9.8%  1.5G / 15.3G
 PWR system 210W  cpu 30W  gpu 170W                  ← names what is missing and why
── GPU  2x MI355X  (AMD) ───────────────────────────────────────────────────────
 ID UTIL          MEMORY            TEMP    POWER      PCIE R+T   NVLINK
 0  ████░░░  42%  ███░░░  3.1/8.0G   58°C   45/ 90W    1.2GB/s    0.9GB/s
── CPU CORES  (--cpu-debug) ────────────────────────────────────────────────────
 temp   24 sensors   min  41.0   avg  52.4   max  61.0°C
 clock  32 cores     min  1200   avg  3400   max  4800 MHz
── NETWORK ─────────────────────────────────────────────────────────────────────
 ib0          rx  124.0MB/s     tx   89.0MB/s
── HISTORY ─────────────────────────────────────────────────────────────────────
 CPU %        0.3% ▁▂▃▅▆▇█▆▅▃▂▁
 GPU0 pwr      45W ▂▃▄▅▆▇█▇▆▅▄▃
 window        25s └──────────┘
── LOG ─────────────────────────────────────────────────────────────────────────
 16:45:05 cpu   0.0%  mem   9.8%  gpu0    0%   43°C   11.6W  (1.5s)
 q quit   space pause   r refresh   ↑↓/PgUp/PgDn scroll   g newest   ? help
```

Fixed-height panels are drawn first; the remainder splits between HISTORY and
LOG, with LOG guaranteed 3 rows. Series that have never produced a reading are
dropped, so a laptop with no BMC does not show permanently blank power rows;
when rows still do not fit, the panel prints `+N series hidden`.

### Layout decisions that were not obvious

- **Sparklines pad on the right**, growing left-to-right. Padding on the left is
  the conventional "newest at the right edge", but at a 10s interval a 110-wide
  row then takes 18 minutes to look like anything but a blank line.
- **Percentages pin to 0-100**, rates and power pin their floor to 0. Autoscaling
  both ends amplifies a series' own noise: idle memory drifting 9.8% → 9.9%
  rendered as a full-height mountain range.
- **The current value sits between the label and the sparkline**, not at the far
  right edge a hundred columns from its label.
- **The GPU table derives its header and cells from one dict of x-offsets**, so
  the two cannot drift apart.
- **The header degrades**: the right-hand block has five variants from richest to
  poorest. A fixed layout drew the status pill on top of the hostname at 80 cols.
- **A flat series renders as the lowest block, never blank**, so "idle" and "no
  data" stay distinguishable; `None` samples stay visible as gaps.

### Repaint correctness

The first sample always has `network: []` — throughput needs two readings — so
NETWORK appears on sample two and shifts every panel below it down three rows.
`_layout_sig()` hashes the frame's *shape* (size, GPU count, interface count,
cpu-debug presence, help state) and forces `clearok(True)` when it changes,
rather than trusting a differential update against a frame of a different
shape.

### Keys

| Key | Action |
|---|---|
| `q` | quit |
| `space` | pause / resume sampling (the thread stays alive) |
| `r` | sample now, without waiting out the interval |
| `↑ ↓` / `k j` | scroll the log one line |
| `PgUp` `PgDn` | scroll the log one page |
| `g` / `G` | jump back to the newest log line |
| `?` / `h` | toggle the help overlay (v2 advertised this as a TODO) |

`ESC` is deliberately **not** quit. Terminals send SS3 (`\033OA`) in
application-keypad mode and CSI (`\033[A`) otherwise; `_read_key()` decodes
both, and mapping a bare ESC to quit would mean an untranslated arrow key kills
the dashboard. A lone ESC is ignored.

## Edge cases

| Case | Behaviour |
|---|---|
| No GPU | GPU panel prints why (`nvidia-smi and amd-smi both unavailable`) |
| A GPU query errors | that row shows the error; its series keep a gap, aggregates skip it |
| No BMC / no sudo | PWR names the missing rail and the reason; no blank sparkline rows |
| No `--cpu-debug` | CPU CORES panel absent; present-but-sensorless shows only the clock line |
| Terminal < 50x8 | single "terminal too small" line instead of a corrupt frame |
| Resize | `KEY_RESIZE` + signature change force a clean re-layout |
| Not a TTY | clean error, exit 1 |
| No curses (non-POSIX) | clean error, exit 1; daemon mode still imports |

Note `$LINES`/`$COLUMNS`, if exported, override the real terminal size — that is
ncurses' documented behaviour, and it pins the layout so resizing appears to do
nothing. Unset them if you hit that.

## Verification

`selfcheck_tui.py` — offline, stdlib only, ~6s:

- `_smi_float` tolerating `[N/A]`
- ring buffer capacity and gap-skipping `last()`
- sparkline direction, gaps, flat series, pinned vs autoscaled range
- bar clamping, byte/frequency/rate formatters
- GPU temperature found in either backend's field
- sample folding: per-GPU history, link and power aggregation, errored GPUs
- log scroll pinning
- layout signature changing when a panel appears or the terminal resizes
- SS3 and CSI arrow decoding
- a pty smoke test: the curses UI paints its panels, and `q` exits 0

Interactive behaviour (pause actually halting sampling, `r` sampling early,
both arrow encodings, resize) was verified separately by driving the UI in a
pty through a terminal emulator and asserting on the rendered screen; that
harness needs a third-party emulator, so it is not committed.
