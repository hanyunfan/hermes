# TUI Mode for collector.py — Design Doc (v3)

> Status: v3 implemented, replaces the v2 hand-rolled ANSI renderer.
> Date: 2026-06-19 (v1, v2) → 2026-09-02 (v3)

## Goal

An interactive, nvitop-inspired dashboard on the local TTY. It must fill the
screen with distinct areas, show everything `collect()` gathers, stay
responsive to keys regardless of the sample interval, **and keep writing the
data files** — those are what gets uploaded to the dashboard site.

## Default mode, and why the no-TTY fallback matters

The dashboard is what you get with no flags; `--raw` selects the old
line-per-sample logging. Both write identical `data/metrics_*.json` records —
verified by comparing key sets between a dashboard-written and a raw-written
file — so the choice is purely about what you want to look at.

v1 and v2 displayed only, writing nothing. That was documented, but it makes
the dashboard useless for the actual workflow (collect, then upload the file),
and "why can't I find the JSON?" is the natural reaction. `_Sampler` now
appends each snapshot *before* attaching its display-only `_`-prefixed fields,
so the file shape cannot drift from raw mode. A failed write is surfaced in the
footer instead of swallowed, because silently losing the file you intend to
upload is the worst outcome available.

Making the dashboard the default puts a trap in front of the systemd unit: a
service has no TTY, and exiting 1 there under `Restart=always` is a silent
five-second crash loop that collects nothing. So `_pick_mode()` falls back to
raw when stdout is not a TTY, and the shipped unit passes `--raw` explicitly
anyway rather than resting on that fallback. An explicit `--tui` with no TTY
still errors, since that asked for something impossible.

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
`nvidia-smi` returns `[N/A]` for unsupported fields, and `float()` on that
raised, so the whole `gpu_power` record was replaced by `{"error": ...}`.
Fixed by `_smi_float()`, which is a data-quality fix for daemon mode too, not
just the TUI.

## GPU thermal limits

`temperature.gpu.tlimit` (`temp_limit` in the JSON) is the thermal **margin** —
degrees still available before throttling — not a ceiling. Both the TUI
colouring and the dashboard's reference line treated it as absolute, so a GPU
at 48°C reporting a 39°C margin was flagged critical and had its "limit" line
drawn below its own curve.

The absolute limit is now probed once at startup into `gpu_temp_max_c`, because
`nvidia-smi -q` spells it two different ways:

```
older / data-center       GPU Shutdown Temp             : 92 C   ← absolute
newer (Blackwell, ...)    GPU Shutdown T.Limit Temp     : -5 C   ← an OFFSET
                          GPU T.Limit Temp              : 44 C   ← margin
                          GPU Target Temperature        : 87 C   ← absolute
```

`_parse_nvidia_temp_max()` therefore ignores any label containing `T.Limit`,
prefers the absolute fields in throttle-relevance order (Slowdown → Shutdown →
Max Operating → Target), and otherwise reconstructs the limit as
`current + T.Limit`. On this laptop that derivation gives 43 + 44 = 87°C and
matches its reported `GPU Target Temperature` exactly, which is the cross-check
that the margin reading is right.

`_gpu_temp_level()` prefers this absolute limit (hot within 3°C, warn within
12°C), falls back to the margin, then to fixed 85/70°C thresholds for AMD. The
dashboard draws a flat line at the probed value, or a `(assumed)`-labelled
100°C when a file predates the field.

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

Two things slide rows wholesale, and both broke a differential update.

The first sample always has `network: []` — throughput needs two readings — so
NETWORK appears on sample two and shifts every panel below it down three rows.
Scrolling either pane slides a block by a line. Both are exactly what ncurses
optimises with insert/delete-line, and diffing across a shifted frame left
stale rows on screen: window `2-7 of 9` rendered `net tx` twice while omitting
the GPU0 series.

`_layout_sig()` therefore hashes size, GPU count, interface count, cpu-debug
presence, help state **and both scroll offsets**, forcing `clearok(True)` when
it changes. The cost is one full repaint per keypress.

### Keys

| Key | Action |
|---|---|
| `q` | quit |
| `space` | pause / resume sampling (the thread stays alive) |
| `r` | sample now, without waiting out the interval |
| `↑ ↓` / `k j` | scroll the HISTORY series |
| `Home` | back to the first HISTORY series |
| `PgUp` `PgDn` | scroll the LOG one page |
| `g` / `G` | reset both: newest log line, first series |
| `?` / `h` | toggle the help overlay (v2 advertised this as a TODO) |

HISTORY is scrollable because an 8-GPU box produces 4 series per GPU plus the
system ones — over 30 rows, of which a 24-row terminal shows six. Counting the
remainder (`+23 series hidden`) was not much use without a way to reach them,
so the panel title now carries the window (`3-8 of 33  ↑↓  ▲ ▼`) and the
offset is clamped in `_hist_window()` during the draw, which is the only place
that knows how many rows survived the terminal height.

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
