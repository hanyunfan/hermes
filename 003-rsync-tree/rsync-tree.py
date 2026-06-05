#!/usr/bin/env python3
#=============================================================================
# rsync-tree.py — Event-driven parallel rsync tree (Rich TUI)
#
# Each node: waiting → active → ready (as new source)
# Main loop: drain completed jobs → pair free ready sources with waiting nodes
# Result: #parallel_rsyncs grows as nodes finish; each at full 100MB/s
#
# Usage:
#   ./rsync-tree.py --dry-run
#   ./rsync-tree.py --tui --dry-run
#   ./rsync-tree.py --nodes 'node[01-18]'
#   ./rsync-tree.py --source node12 --nodes 'node[01-18]'
#   ./rsync-tree.py --dir /data/shared
#=============================================================================

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import shlex
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# ────────────────────────── Pattern expander ──────────────────────────

def expand_nodes(pattern: str) -> list[str]:
    """Expand patterns like 'node[01-18]', 'node0[01-18]', 'compute[0-7]'."""
    if "," in pattern:
        return [n.strip() for n in pattern.split(",") if n.strip()]

    m = re.match(r"^(.+)\[(.+)\]$", pattern)
    if m:
        prefix, range_part = m.group(1), m.group(2)
        rm = re.match(r"^(0*[0-9]+)[\.\-]+(0*[0-9]+)$", range_part)
        if rm:
            start, end = rm.group(1), rm.group(2)
            pad = 0
            if start.startswith("0"):
                pad = len(start)
            else:
                pad = max(len(start), len(end))
            return [f"{prefix}{i:0{pad}d}" for i in range(int(start), int(end) + 1)]

    return [pattern]


# ────────────────────────── State ──────────────────────────

class JobStatus(str, Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    src: str
    tgt: str
    status: JobStatus = JobStatus.WAITING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    bytes_transferred: int = 0
    total_bytes: int = 0
    progress_pct: float = 0.0
    speed_mbs: float = 0.0
    error: Optional[str] = None
    retries: int = 0

    @property
    def key(self) -> str:
        return f"{self.src}→{self.tgt}"

    @property
    def duration_s(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.monotonic()
        return end - self.started_at


@dataclass
class Controller:
    """Shared state across async tasks; mutated by jobs, read by TUI."""
    source_node: str
    all_nodes: list[str]
    src_dir: str
    dry_run: bool
    ssh_args: list[str]
    max_parallel: int = 0   # 0 = no cap

    jobs: dict[str, Job] = field(default_factory=dict)
    events: deque[tuple[float, str, str]] = field(default_factory=lambda: deque(maxlen=200))
    topology: dict[str, list[str]] = field(default_factory=dict)   # src -> [tgt,...] (children)
    iter_count: int = 0
    started_at: float = field(default_factory=time.monotonic)
    paused: bool = False
    failed_count: int = 0
    done_count: int = 0
    user_quit: bool = False
    max_retries: int = 3

    def log(self, level: str, msg: str) -> None:
        self.events.append((time.monotonic(), level, msg))


# ────────────────────────── Rsync progress parsing ──────────────────────────

# Matches: "    1,234,567  34%   12.34MB/s    0:01:23  (xfr#5, to-chk=10/15)"
# Or:     "\rsync: total: 100% (xx/yy)"
PROGRESS_RE = re.compile(
    r"\s*([\d,]+)\s+(\d+)%\s+([\d.]+)([KMG]?B)/s"
)
TOTAL_BYTES_RE = re.compile(r"total size is ([\d,]+)")


def _parse_rate(value: float, unit: str) -> float:
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}.get(unit, 1)
    return value * mult / (1024 * 1024)  # → MB/s


def parse_progress_line(line: str) -> Optional[tuple[int, float, float]]:
    """Return (bytes_done, percent, speed_mbs) or None."""
    m = PROGRESS_RE.search(line)
    if not m:
        return None
    bytes_done = int(m.group(1).replace(",", ""))
    pct = float(m.group(2))
    speed = _parse_rate(float(m.group(3)), m.group(4))
    return bytes_done, pct, speed


# ────────────────────────── Async rsync runner ──────────────────────────

async def run_one_job(ctrl: Controller, job: Job) -> None:
    """Execute a single rsync; updates job state from subprocess output."""
    log_path = Path(f"/tmp/rsync-{job.src}-{job.tgt}.log")
    log_f = log_path.open("w")

    if ctrl.dry_run:
        # Simulate a job: 1.5s ramp 0%→100%, with progress
        job.status = JobStatus.ACTIVE
        job.started_at = time.monotonic()
        total = 500_000_000_000  # 500 GB fake
        job.total_bytes = total
        ctrl.log("INFO", f"[{job.src}] → [{job.tgt}] starting (dry-run)")
        try:
            steps = 30
            for i in range(steps + 1):
                if ctrl.user_quit:
                    return
                while ctrl.paused and not ctrl.user_quit:
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.05)
                job.progress_pct = i * (100.0 / steps)
                job.bytes_transferred = int(total * job.progress_pct / 100)
                # Speed: ramp 0→100 MB/s, hold, ramp down
                if i < 10:
                    job.speed_mbs = i * 10.0
                elif i > 20:
                    job.speed_mbs = (30 - i) * 10.0
                else:
                    job.speed_mbs = 100.0 + random.uniform(-5, 5)
                log_f.write(f"{job.bytes_transferred:>12}  {job.progress_pct:5.1f}%  {job.speed_mbs:6.1f}MB/s\n")
            job.progress_pct = 100.0
            job.bytes_transferred = total
            job.status = JobStatus.DONE
            job.finished_at = time.monotonic()
            ctrl.done_count += 1
            ctrl.log("OK", f"[{job.src}] → [{job.tgt}] ✓ done in {job.duration_s:.1f}s (dry-run)")
        finally:
            log_f.close()
        return

    # Real run
    ssh_args = " ".join(shlex.quote(a) for a in ctrl.ssh_args)
    remote_cmd = (
        f"rsync -av --inplace --info=progress2 {shlex.quote(ctrl.src_dir + '/')} "
        f"{shlex.quote(job.tgt)}:{shlex.quote(ctrl.src_dir + '/')}"
    )
    ssh_cmd = ["ssh", *ctrl.ssh_args, job.src, remote_cmd]

    job.status = JobStatus.ACTIVE
    job.started_at = time.monotonic()
    ctrl.log("INFO", f"[{job.src}] → [{job.tgt}] starting")

    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            log_f.write(line + "\n")
            parsed = parse_progress_line(line)
            if parsed:
                bytes_done, pct, speed_mbs = parsed
                job.bytes_transferred = bytes_done
                job.progress_pct = pct
                job.speed_mbs = speed_mbs
            m = TOTAL_BYTES_RE.search(line)
            if m:
                job.total_bytes = int(m.group(1).replace(",", ""))

        rc = await proc.wait()
        if rc == 0:
            job.status = JobStatus.DONE
            job.progress_pct = 100.0
            job.finished_at = time.monotonic()
            ctrl.done_count += 1
            ctrl.log("OK", f"[{job.src}] → [{job.tgt}] ✓ done in {job.duration_s:.1f}s")
        else:
            job.status = JobStatus.FAILED
            job.finished_at = time.monotonic()
            job.error = f"rsync exit {rc}"
            ctrl.failed_count += 1
            ctrl.log("ERR", f"[{job.src}] → [{job.tgt}] ✗ exit {rc}")
    finally:
        log_f.close()


# ────────────────────────── Main loop ──────────────────────────

async def scheduler(ctrl: Controller) -> None:
    """Drain completed jobs, pair free ready sources with waiting nodes."""
    waiting: deque[str] = deque(n for n in ctrl.all_nodes if n != ctrl.source_node)
    ready: set[str] = {ctrl.source_node}
    active: dict[str, Job] = {}   # key → Job
    tasks: dict[str, asyncio.Task] = {}   # key → Task

    # Initialize topology
    for n in ctrl.all_nodes:
        ctrl.topology[n] = []

    while True:
        if ctrl.user_quit:
            break

        ctrl.iter_count += 1

        if not ctrl.paused:
            # 1. Drain completed
            for key in list(active.keys()):
                job = active[key]
                if job.status in (JobStatus.DONE, JobStatus.FAILED):
                    del active[key]
                    if key in tasks:
                        del tasks[key]
                    if job.status == JobStatus.DONE:
                        ready.add(job.src)
                        ready.add(job.tgt)
                    else:
                        # Failed: retry target up to N times
                        if job.retries < ctrl.max_retries:
                            job.retries += 1
                            job.status = JobStatus.WAITING
                            job.error = None
                            waiting.appendleft(job.tgt)
                            ctrl.log("WARN", f"[{job.tgt}] returned to queue (retry {job.retries}/{ctrl.max_retries})")
                        else:
                            ctrl.log("ERR", f"[{job.tgt}] giving up after {job.max_retries} retries")

            # 2. Pair free ready sources with waiting nodes
            for src in list(ready):
                # Don't reuse src if it has an active job
                if any(j.src == src for j in active.values()):
                    continue
                # Cap parallelism
                if ctrl.max_parallel and len(active) >= ctrl.max_parallel:
                    break
                if not waiting:
                    break
                tgt = waiting.popleft()
                job = Job(src=src, tgt=tgt)
                ctrl.jobs[job.key] = job
                ctrl.topology[src].append(tgt)
                active[job.key] = job
                tasks[job.key] = asyncio.create_task(run_one_job(ctrl, job))
                ready.discard(src)

        # Termination
        if not active and not waiting and len(ready) >= len(ctrl.all_nodes):
            break

        await asyncio.sleep(0.2)

    # Wait for any stragglers (shouldn't be any by the time we exit, but safety)
    if tasks:
        await asyncio.gather(*tasks.values(), return_exceptions=True)


# ────────────────────────── Plain (non-TUI) runner ──────────────────────────

async def run_plain(ctrl: Controller) -> None:
    """Run scheduler with simple line-based output, no Live UI."""
    print(f"Source: {ctrl.source_node}  Nodes: {len(ctrl.all_nodes)}  "
          f"Dir: {ctrl.src_dir}  Dry: {ctrl.dry_run}")
    print("─" * 60)

    scheduler_task = asyncio.create_task(scheduler(ctrl))

    try:
        while not scheduler_task.done():
            await asyncio.sleep(0.5)
            # Render a one-line summary
            active = [j for j in ctrl.jobs.values() if j.status == JobStatus.ACTIVE]
            done = [j for j in ctrl.jobs.values() if j.status == JobStatus.DONE]
            failed = [j for j in ctrl.jobs.values() if j.status == JobStatus.FAILED]
            summary = (
                f"[iter {ctrl.iter_count:>3}] "
                f"active={len(active):>2}  done={len(done):>2}/{len(ctrl.all_nodes) - 1}  "
                f"failed={len(failed):>2}  t={time.monotonic() - ctrl.started_at:>6.1f}s"
            )
            if active:
                parts = [f"{j.src}→{j.tgt} {j.progress_pct:5.1f}% {j.speed_mbs:5.1f}MB/s"
                         for j in active]
                summary += "  |  " + "  ".join(parts)
            print(summary, flush=True)
    except KeyboardInterrupt:
        ctrl.user_quit = True
        print("\nInterrupted, waiting for scheduler to drain...")

    await scheduler_task
    elapsed = time.monotonic() - ctrl.started_at
    print("─" * 60)
    succeeded = ctrl.done_count
    synced_nodes = sum(1 for j in ctrl.jobs.values() if j.status == JobStatus.DONE)
    target_nodes = len(ctrl.all_nodes) - 1   # exclude source
    print(f"Done. {succeeded} jobs succeeded, "
          f"{ctrl.failed_count} failed; "
          f"{succeeded}/{target_nodes} target nodes synced. "
          f"Total: {elapsed:.1f}s")


# ────────────────────────── Rich TUI ──────────────────────────

def _fmt_speed(mbs: float) -> Text:
    if mbs >= 100:
        return Text(f"{mbs:5.1f} MB/s", style="bold green")
    elif mbs >= 50:
        return Text(f"{mbs:5.1f} MB/s", style="green")
    elif mbs > 0:
        return Text(f"{mbs:5.1f} MB/s", style="yellow")
    return Text("  0.0 MB/s", style="dim")


def _fmt_status(status: JobStatus) -> Text:
    return {
        JobStatus.WAITING: Text("WAIT ", style="dim yellow"),
        JobStatus.ACTIVE:  Text("RUN  ", style="bold cyan"),
        JobStatus.DONE:    Text("DONE ", style="bold green"),
        JobStatus.FAILED:  Text("FAIL ", style="bold red"),
    }[status]


def render_topology(ctrl: Controller) -> Panel:
    """ASCII tree showing fan-out from source."""
    lines: list[Text] = []
    src = ctrl.source_node
    lines.append(Text(f"Source: ", style="dim") +
                 Text(src, style="bold cyan"))

    def render_subtree(node: str, prefix: str, is_last: bool) -> None:
        children = list(ctrl.topology.get(node, []))
        if not children:
            return
        new_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)
            connector = "└─→ " if is_last_child else "├─→ "
            job = ctrl.jobs.get(f"{node}→{child}")
            status_text = _fmt_status(job.status) if job else Text("     ", style="dim")
            child_name_style = "bold green" if (job and job.status == JobStatus.DONE) else \
                               "bold red" if (job and job.status == JobStatus.FAILED) else \
                               "white"
            line = Text(prefix, style="dim")
            line += Text(connector, style="dim")
            line += status_text
            line += Text(child, style=child_name_style)
            lines.append(line)
            render_subtree(child, new_prefix, is_last_child)

    render_subtree(src, "", True)
    return Panel(Group(*lines), title="[bold]Topology[/bold]", border_style="blue")


def render_jobs_table(ctrl: Controller) -> Panel:
    """Per-job live progress."""
    table = Table(expand=True, show_header=True, header_style="bold magenta",
                  border_style="blue")
    table.add_column("Status", width=6)
    table.add_column("Route", style="white", no_wrap=True)
    table.add_column("Progress", min_width=18)
    table.add_column("%", width=6, justify="right")
    table.add_column("Speed", width=12, justify="right")
    table.add_column("Time", width=7, justify="right")

    # Sort: active first, then waiting, done, failed
    order = {JobStatus.ACTIVE: 0, JobStatus.WAITING: 1,
             JobStatus.DONE: 2, JobStatus.FAILED: 3}
    jobs_sorted = sorted(ctrl.jobs.values(), key=lambda j: (order[j.status], j.started_at or 0))

    for j in jobs_sorted:
        bar_width = 18
        filled = int(bar_width * j.progress_pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        color = {"waiting": "yellow", "active": "cyan",
                 "done": "green", "failed": "red"}[j.status.value]
        bar_text = Text(bar, style=color)

        retry_str = ""
        table.add_row(
            _fmt_status(j.status),
            f"{j.src}→{j.tgt}",
            bar_text,
            f"{j.progress_pct:5.1f}" if j.status != JobStatus.WAITING else "  0.0",
            _fmt_speed(j.speed_mbs) if j.status == JobStatus.ACTIVE else
            Text(f"{j.duration_s:5.1f}s", style="dim") if j.status == JobStatus.DONE else
            Text("", style="dim"),
            f"{j.duration_s:5.1f}s" if j.status in (JobStatus.ACTIVE, JobStatus.DONE) else "",
        )

    if not jobs_sorted:
        table.add_row(Text("—", style="dim"), Text("(no jobs yet)", style="dim"),
                      "", "", "", "")

    return Panel(table, title="[bold]Jobs[/bold]", border_style="blue")


def render_events(ctrl: Controller) -> Panel:
    """Recent event log."""
    lines: list[Text] = []
    for ts, level, msg in list(ctrl.events)[-12:]:
        elapsed = ts - ctrl.started_at
        time_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        level_style = {"OK": "green", "ERR": "red", "WARN": "yellow", "INFO": "cyan"}.get(level, "white")
        line = Text(f"{time_str} ", style="dim") + Text(f"{level:>4} ", style=level_style) + Text(msg)
        lines.append(line)
    if not lines:
        lines.append(Text("(no events yet)", style="dim"))
    return Panel(Group(*lines), title="[bold]Events[/bold]", border_style="blue")


def render_header(ctrl: Controller) -> Panel:
    """Top status bar."""
    elapsed = time.monotonic() - ctrl.started_at
    elapsed_str = f"{int(elapsed // 3600):02d}:{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
    active = sum(1 for j in ctrl.jobs.values() if j.status == JobStatus.ACTIVE)
    done = sum(1 for j in ctrl.jobs.values() if j.status == JobStatus.DONE)
    failed = sum(1 for j in ctrl.jobs.values() if j.status == JobStatus.FAILED)
    waiting = len([n for n in ctrl.all_nodes
                   if n != ctrl.source_node
                   and not any(j.tgt == n and j.status in (JobStatus.ACTIVE, JobStatus.DONE)
                               for j in ctrl.jobs.values())])
    dry_tag = Text(" [DRY-RUN] ", style="bold yellow on grey15") if ctrl.dry_run else Text("")
    pause_tag = Text(" [PAUSED] ", style="bold white on red") if ctrl.paused else Text("")

    title = Text()
    title.append("rsync-tree", style="bold cyan")
    title.append(dry_tag)
    title.append(pause_tag)
    title.append(f"  src={ctrl.source_node}  nodes={len(ctrl.all_nodes)}  "
                 f"iter={ctrl.iter_count}  t={elapsed_str}",
                 style="white")

    stats = Text()
    stats.append(f"●{active} active", style="cyan")
    stats.append(f"  ✓{done} done", style="green")
    stats.append(f"  ✗{failed} failed", style="red" if failed else "dim")
    stats.append(f"  ⏳{waiting} waiting", style="yellow")

    body = Group(title, stats)
    return Panel(body, border_style="cyan")


def render_help(ctrl: Controller) -> Panel:
    text = Text()
    text.append("[q]", style="bold cyan") + Text(" quit  ")
    text.append("[p]", style="bold cyan") + Text(" pause/resume  ")
    text.append("[+]", style="bold cyan") + Text(" +1 parallel  ")
    text.append("[-]", style="bold cyan") + Text(" -1 parallel  ")
    text.append("[r]", style="bold cyan") + Text(" reset retries  ")
    text.append("[l]", style="bold cyan") + Text(" toggle events pane")
    return Panel(text, border_style="grey50")


def build_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    layout["left"].split_column(
        Layout(name="topology", ratio=2),
        Layout(name="events", ratio=1),
    )
    return layout


def render_full(ctrl: Controller) -> Layout:
    layout = build_layout()
    layout["header"].update(render_header(ctrl))
    layout["topology"].update(render_topology(ctrl))
    layout["events"].update(render_events(ctrl))
    layout["right"].update(render_jobs_table(ctrl))
    layout["footer"].update(render_help(ctrl))
    return layout


async def run_tui(ctrl: Controller) -> None:
    """Run with Rich Live TUI; respond to keypresses."""
    console = Console()
    layout = build_layout()

    # Key listener: convert input() in another thread to events
    key_queue: asyncio.Queue[str] = asyncio.Queue()

    def key_reader() -> None:
        import select
        import termios
        import tty
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while not ctrl.user_quit:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        ch = sys.stdin.read(1).lower()
                        if ch:
                            asyncio.run_coroutine_threadsafe(key_queue.put(ch), loop)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    import threading
    reader_thread = threading.Thread(target=key_reader, daemon=True)
    reader_thread.start()

    scheduler_task = asyncio.create_task(scheduler(ctrl))

    try:
        with Live(layout, console=console, refresh_per_second=10, screen=True) as live:
            while not scheduler_task.done():
                # Drain key events
                try:
                    while True:
                        key = key_queue.get_nowait()
                        if key == "q":
                            ctrl.user_quit = True
                        elif key == "p":
                            ctrl.paused = not ctrl.paused
                            ctrl.log("INFO", f"{'PAUSED' if ctrl.paused else 'RESUMED'}")
                        elif key == "+" or key == "=":
                            ctrl.max_parallel = max(0, ctrl.max_parallel + 1)
                            ctrl.log("INFO", f"max_parallel = {ctrl.max_parallel or 'unlimited'}")
                        elif key == "-":
                            ctrl.max_parallel = max(0, ctrl.max_parallel - 1)
                            ctrl.log("INFO", f"max_parallel = {ctrl.max_parallel or 'unlimited'}")
                        elif key == "r":
                            for j in ctrl.jobs.values():
                                j.retries = 0
                            ctrl.log("INFO", "retries reset")
                except asyncio.QueueEmpty:
                    pass

                live.update(render_full(ctrl))
                await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        ctrl.user_quit = True

    ctrl.user_quit = True
    await scheduler_task


# ────────────────────────── CLI ──────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Event-driven parallel rsync tree with optional Rich TUI",
    )
    p.add_argument("--source", default="node12", help="source node (default: node12)")
    p.add_argument("--nodes", default="node[01-18]",
                   help="node pattern (default: node[01-18])")
    p.add_argument("--dir", default="/mnt/data", help="source directory (default: /mnt/data)")
    p.add_argument("--ssh-args", default="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -o BatchMode=yes",
                   help="SSH args (default: safer non-interactive)")
    p.add_argument("--dry-run", action="store_true", help="simulate without real rsync")
    p.add_argument("--tui", action="store_true", help="render Rich TUI (requires `rich`)")
    p.add_argument("--max-parallel", type=int, default=0, help="cap on concurrent rsyncs (0=unlimited)")
    p.add_argument("--max-retries", type=int, default=3, help="retries per target before giving up")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    all_nodes = expand_nodes(args.nodes)
    if not all_nodes:
        print("ERROR: no nodes after expansion", file=sys.stderr)
        return 1
    if args.source not in all_nodes:
        print(f"ERROR: source {args.source} not in node list {all_nodes}", file=sys.stderr)
        return 1

    ctrl = Controller(
        source_node=args.source,
        all_nodes=all_nodes,
        src_dir=args.dir,
        dry_run=args.dry_run,
        ssh_args=args.ssh_args.split(),
        max_parallel=args.max_parallel,
        max_retries=args.max_retries,
    )

    if args.tui and not RICH_AVAILABLE:
        print("ERROR: --tui requires the `rich` package (pip install rich)", file=sys.stderr)
        return 1

    if args.tui:
        asyncio.run(run_tui(ctrl))
    else:
        asyncio.run(run_plain(ctrl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
