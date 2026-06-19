# TUI Mode for collector.py — Design Doc

> Status: implemented in commit `<pending>`
> Date: 2026-06-18
> Author: Claude (drafted) + Frank (direction)

## Goal

Add an opt-in `--tui` flag to `collector.py` that runs an interactive
top-style TUI on the local terminal instead of writing JSON to disk.
Look-and-feel mirrors [Syllo/nvtop](https://github.com/Syllo/nvtop):
multiple labeled bars (CPU, RAM, GPU, NET) refreshed every interval,
with a single-line footer for key bindings.

## Why pure-ANSI instead of curses/blessed

- **No new dependency**: collector.py ships with stdlib only. Adding
  `curses` or `blessed` would force every machine (CI, GH Pages
  builder, simple bare-metal) to install extras.
- **Works in any TTY**: ANSI escape sequences are interpreted by
  every reasonable terminal emulator (iTerm2, gnome-terminal,
  Windows Terminal, tmux/screen, VSCode integrated terminal).
- **Smaller code path**: ~200 lines vs curses/blessed which would
  be 500+ lines of abstraction over the same primitives.

## UI layout (≈ 80×24 viewport)

```
╭─ frank-XPS-8960 ───────── 2026-06-18 14:30:00 ────── ⟳ 2s ─╮
│                                                             │
│  CPU  i7-14700K  28c/28t  ███████████░░░░░░░  35%  3.4GHz  │
│  MEM  DDR5 62GB          ████████░░░░░░░░░░  52%  16/62GB  │
│  SYS  342W   CPU=45W  GPU0=120W GPU1=118W ...               │
│                                                             │
│  GPU0 RTX 4090  ████████░░░░ 78%  72°C  1.8GHz  380W/450W  │
│  GPU1 RTX 4090  ████░░░░░░░░ 41%  58°C  1.2GHz  185W/450W  │
│  ...                                                        │
│                                                             │
│  NET  eth0 RX=124MB/s  TX=89MB/s                            │
│                                                             │
│  q: quit   space: pause   r: refresh now   ?: help          │
╰─────────────────────────────────────────────────────────────╯
```

### Sections (top → bottom)

1. **Header bar**: hostname, current UTC time, refresh interval
2. **CPU row**: name + core/thread count + bar + % + freq (if available)
3. **MEM row**: type + total + bar + % + used/total
4. **SYS row**: system power + per-component breakdown
5. **GPU rows** (1 per GPU): name + bar + % + temp + freq + power/limit
6. **NET row**: per-interface RX/TX
7. **Footer**: key bindings

### Bar rendering

A bar is a fixed-width sequence of `█` (filled) and `░` (empty)
characters. Width 20 chars, color: green <60%, yellow 60–85%, red >85%.
Color is per-bar (whole bar one color) — using the same `bar(pct)` helper
in every row keeps the layout consistent.

## Code shape

### New functions in collector.py

```python
# ── ANSI helpers ──
def _ansi(code): return f"\033[{code}m"
def _cursor_home():   sys.stdout.write("\033[H")
def _hide_cursor():   sys.stdout.write("\033[?25l")
def _show_cursor():   sys.stdout.write("\033[?25h")
def _clear_screen():  sys.stdout.write("\033[2J")
def _clear_line():    sys.stdout.write("\033[K")
def _alt_screen_on(): sys.stdout.write("\033[?1049h")
def _alt_screen_off():sys.stdout.write("\033[?1049l")

def _bar(pct, width=20):
    filled = max(0, min(width, int(round((pct or 0) * width / 100))))
    color = "31" if pct >= 85 else "33" if pct >= 60 else "32"  # red/yel/grn
    return f"\033[{color}m" + "█" * filled + "\033[37m" + "░" * (width - filled) + "\033[0m"

def _fmt_bytes_mb(mb):
    if mb is None: return "?"
    if mb >= 1024: return f"{mb/1024:.1f}G"
    return f"{mb:.0f}M"

# ── Render one frame ──
def _tui_render(stats, interval, paused=False):
    out = []
    out.append("╭─ " + stats["hostname"] + " ─" + ...)
    out.append("│  CPU  " + ...)
    ...
    sys.stdout.write("\n".join(out) + "\033[J")  # \033[J clears from cursor to end

# ── Main TUI loop ──
def tui(interval=2, _display_name=None, cpu_debug=False):
    global display_name
    display_name = _display_name
    _alt_screen_on(); _hide_cursor()
    try:
        while True:
            stats = collect(cpu_debug=cpu_debug)
            _tui_render(stats, interval)
            # Non-blocking key read
            ...
            time.sleep(interval)
    finally:
        _show_cursor(); _alt_screen_off()
```

### CLI changes

```python
if __name__ == "__main__":
    ...
    if "--tui" in args:
        args.remove("--tui")
        if len(args) < 2:
            print("Usage: python3 collector.py --tui <interval> <display_name> [--cpu-debug]")
            sys.exit(1)
        tui(int(args[0]), args[1], cpu_debug=cpu_debug)
    else:
        # legacy daemon mode
        daemon(int(args[0]), args[1], cpu_debug=cpu_debug)
```

## Edge cases

1. **No GPU**: skip GPU rows, leave section blank
2. **No network data**: skip NET row
3. **No system_power_w**: hide SYS row
4. **CPU freq unavailable**: show "?" for freq
5. **Terminal <80 cols**: wrap lines (don't truncate — nvtop also wraps)
6. **TTY detection**: if `sys.stdout.isatty()` is False, fall back to
   single-stamp print + exit. (No point rendering to a pipe.)
7. **Resize**: SIGWINCH handler rebuilds the header; rest of layout
   is width-independent via wrap.

## Testing plan

```bash
# 1. Local smoke (Intel i7-14700K + 0 GPU, no network)
python3 collector.py --tui 2 test_machine
# Expected: TUI appears, refreshes every 2s, q quits cleanly

# 2. With --cpu-debug
python3 collector.py --tui 2 test_machine --cpu-debug
# Expected: same UI, no extra output (debug data is JSON-only)

# 3. Non-TTY (piped to file)
python3 collector.py --tui 2 test_machine | head
# Expected: clear error message, exit 1

# 4. Remote machine (post-push)
ssh node004 "python3 /home/frank/hermes/system-monitor/collector.py --tui 2 node004"
# Expected: GPU rows visible, system_power visible
```

## Diff estimate

- ~200 lines added (mostly render + helpers)
- ~10 lines changed in `__main__`
- 0 lines changed in collect() — TUI reuses everything
