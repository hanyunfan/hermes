#!/usr/bin/env python3
"""Sync newly-completed ComfyUI mp4 files into a project's output/clips/.

Run periodically (or after each generation) to make sure every shot that
ComfyUI successfully produced an mp4 for ends up in the project's clip
directory, even if the runner crashed before save_clip() could write.

The mapping is inferred from history: we ask ComfyUI's /history endpoint
for finished prompts whose output is a SaveVideo node, then match the
resulting ``video/MiniMax_H3_NNNNN_.mp4`` filename back to a shot_id by
reading the on-disk shot yaml files and matching their seed/prompt.

In practice the simpler heuristic is good enough: a job in
``state/jobs/*.json`` with status=COMPLETED plus an output_path pointing at
a file under ``ComfyUI/output/video/`` should have its mp4 mirrored to
``output/clips/<shot_id>.mp4`` so the rest of the framework can find it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Make src importable when running as a plain script
ROOT = Path("/home/frank/hermes/ai-video-director")
sys.path.insert(0, str(ROOT / "src"))

from video_director.jobs.manager import StateManager  # noqa: E402
from video_director.cli.common import make_project_manager  # noqa: E402


def sync_clips(project_id: str, comfyui_video_dir: Path, dry_run: bool = False) -> int:
    """Mirror mp4s from ComfyUI output dir into project's output/clips/.

    Strategy:
      1. For every job with status=COMPLETED and a non-empty output_path
         that still exists on disk, copy it.
      2. For every job with status=COMPLETED but an empty/missing output_path,
         look in comfyui_video_dir for an mp4 whose mtime is between the
         job's started_at and finished_at (within a generous window) and
         whose size > 100KB (skip empty/error mp4s).

    Both branches dest to ``output/clips/<shot_id>.mp4``.
    """
    import datetime as dt

    pm = make_project_manager(ROOT)
    paths = pm.paths_for_id(project_id)
    paths.ensure_all()
    state = StateManager(paths)

    moved = 0
    seen_shots = 0

    def _parse_iso(s: str) -> dt.datetime | None:
        if not s:
            return None
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    # Index ComfyUI mp4s by mtime (so we don't have to glob each time)
    comfy_files: list[tuple[dt.datetime, Path]] = []
    if comfyui_video_dir.exists():
        for f in comfyui_video_dir.glob("*.mp4"):
            try:
                mtime = dt.datetime.fromtimestamp(f.stat().st_mtime, tz=dt.timezone.utc)
            except OSError:
                continue
            comfy_files.append((mtime, f))
    comfy_files.sort(key=lambda x: x[0])

    for job in state.iter_jobs():
        seen_shots += 1
        if job.status.value != "completed":
            continue
        dest = paths.output_clips_dir / f"{job.shot_id}.mp4"
        if dest.exists():
            continue

        # Branch 1: output_path set and points at an existing file
        if job.output_path:
            src = Path(job.output_path)
            if src.exists() and src.is_file():
                if dry_run:
                    print(f"[dry-run] would copy {src} -> {dest}")
                else:
                    shutil.copy2(src, dest)
                    print(f"[moved] {src.name} -> {dest}")
                moved += 1
                continue

        # Branch 2: look up an mp4 by mtime window
        started = _parse_iso(job.started_at)
        finished = _parse_iso(job.finished_at)
        if started is None:
            continue
        # Window: [started - 5min, finished + 5min] (ComfyUI writes video right
        # after diffusion completes; allow slack for slow writes + polls).
        window_lo = started - dt.timedelta(minutes=5)
        window_hi = (finished or started) + dt.timedelta(minutes=10)
        candidates = [
            (mtime, f)
            for mtime, f in comfy_files
            if window_lo <= mtime <= window_hi and f.stat().st_size > 100_000
        ]
        if not candidates:
            continue
        # Pick the file closest to (finished or started)
        anchor = finished or started
        best_mtime, best_f = min(candidates, key=lambda mf: abs((mf[0] - anchor).total_seconds()))
        if dry_run:
            print(f"[dry-run] would copy {best_f} (mtime {best_mtime.isoformat()}) -> {dest}")
        else:
            shutil.copy2(best_f, dest)
            print(f"[moved] {best_f.name} (mtime {best_mtime.isoformat()}) -> {dest}")
        moved += 1

    print(f"=== sync_clips: {seen_shots} jobs scanned, {moved} mp4 moved "
          f"({'dry-run' if dry_run else 'live'}) ===")
    if not dry_run:
        state.recompute_counters()
    return moved


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", help="project id (under projects/<id>/)")
    p.add_argument(
        "--comfyui-video-dir",
        default="/home/frank/ComfyUI/output/video",
        help="directory where ComfyUI writes MiniMax_H3_NNNNN_.mp4",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sync_clips(args.project, Path(args.comfyui_video_dir), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
