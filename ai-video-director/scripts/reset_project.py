"""Hard reset of a project before a fresh generate.

Deletes:
- all mp4 in ``output/clips/``
- all job files in ``state/jobs/``
- ``state/last_run_summary.json``
- ``state/assembly_manifest.json`` (so the next assemble rebuilds it)

Then rewrites ``state/generation_state.json`` so ``total_shots`` matches
the current ``imports/shots.json`` length and ``completed_shots=0``.
``failed_shots`` is also reset to 0 so the next run starts clean.

Run BEFORE kicking off a fresh generate from updated shots.json — this
is the canonical "delete mp4 + decrement counter" workflow the 2026-10-10
clip-count hard lesson demands.

Usage:
    python scripts/reset_project.py <project_id> [--dry-run]

The framework root is the parent of the ``projects/`` directory (this
script's grandparent by default; override with ``VIDEO_DIRECTOR_ROOT``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _framework_root() -> Path:
    """Return the framework root (parent of ``projects/``).

    Default: two levels up from this file (``scripts/reset_project.py``
    -> ``scripts/`` -> ``ai-video-director/``). Override via the
    ``VIDEO_DIRECTOR_ROOT`` environment variable for unusual setups.
    """
    env_root = os.environ.get("VIDEO_DIRECTOR_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def reset_project(framework_root: Path, project_id: str, dry_run: bool) -> int:
    if not project_id or "/" in project_id or project_id.startswith("."):
        print(f"invalid project_id: {project_id!r}", file=sys.stderr)
        return 2

    project_root = framework_root / "projects" / project_id
    if not project_root.exists():
        print(f"project not found: {project_root}", file=sys.stderr)
        return 2

    clips_dir = project_root / "output" / "clips"
    jobs_dir = project_root / "state" / "jobs"
    state_file = project_root / "state" / "generation_state.json"
    summary_file = project_root / "state" / "last_run_summary.json"
    manifest_file = project_root / "state" / "assembly_manifest.json"
    shots_file = project_root / "imports" / "shots.json"

    # 1. count current mp4 (for logging)
    existing_mp4 = sorted(clips_dir.glob("*.mp4")) if clips_dir.exists() else []
    print(f"clips before: {len(existing_mp4)} mp4 files", file=sys.stderr)

    # 2. count shots.json (source of truth for total_shots)
    if not shots_file.exists():
        print(f"shots.json not found at {shots_file}", file=sys.stderr)
        return 2
    with shots_file.open() as f:
        shots = json.load(f)
    total = len(shots)
    print(f"shots.json total: {total}", file=sys.stderr)

    if dry_run:
        print("[dry-run] would delete mp4 + jobs + summary + manifest, "
              "rewrite generation_state.json", file=sys.stderr)
        return 0

    # 3. delete mp4
    if clips_dir.exists():
        for f in existing_mp4:
            f.unlink()
        print(f"deleted {len(existing_mp4)} mp4 files", file=sys.stderr)

    # 4. delete jobs
    if jobs_dir.exists():
        job_files = sorted(jobs_dir.glob("*.json"))
        for f in job_files:
            f.unlink()
        print(f"deleted {len(job_files)} job files", file=sys.stderr)

    # 5. delete last_run_summary + assembly_manifest so the runner /
    #    next assemble doesn't reuse cached totals / output path.
    for stale in (summary_file, manifest_file):
        if stale.exists():
            stale.unlink()
            print(f"deleted {stale}", file=sys.stderr)

    # 6. rewrite generation_state.json with reset counters
    state = {
        "project_id": project_id,
        "state": "in_progress",
        "started_at": "2026-10-11T05:00:00Z",
        "updated_at": "2026-10-11T05:00:00Z",
        "backend": "comfyui",
        "max_concurrent_jobs": 1,
        "max_retries": 3,
        "total_shots": total,
        "completed_shots": 0,
        "failed_shots": 0,
        "skipped_shots": 0,
        "last_job_id": "",
        "last_error": "",
        "notes": ["hard reset for fresh generate after shots.json update"],
    }
    with state_file.open("w") as f:
        json.dump(state, f, indent=2)
    print(f"rewrote {state_file}: total_shots={total} completed_shots=0", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hard reset an ai-video-director project.",
    )
    parser.add_argument("project_id", help="Project id (under projects/<project_id>/)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without deleting anything.",
    )
    args = parser.parse_args(argv)

    framework_root = _framework_root()
    return reset_project(framework_root, args.project_id, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())