"""Hard reset of new_grok_story:
- delete all mp4 in output/clips/
- delete all job files in state/jobs/
- rewrite generation_state.json with current shot count and 0 completed
- also delete last_run_summary.json so the runner doesn't reuse it

Run BEFORE kicking off a fresh generate from updated shots.json.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path("projects/new_grok_story")


def main() -> int:
    clips_dir = ROOT / "output" / "clips"
    jobs_dir = ROOT / "state" / "jobs"
    state_file = ROOT / "state" / "generation_state.json"
    summary_file = ROOT / "state" / "last_run_summary.json"

    # 1. count current mp4 (for logging)
    existing_mp4 = sorted(clips_dir.glob("*.mp4")) if clips_dir.exists() else []
    print(f"clips before: {len(existing_mp4)} mp4 files", file=sys.stderr)

    # 2. delete mp4
    if clips_dir.exists():
        for f in existing_mp4:
            f.unlink()
        print(f"deleted {len(existing_mp4)} mp4 files", file=sys.stderr)

    # 3. delete jobs
    if jobs_dir.exists():
        job_files = sorted(jobs_dir.glob("*.json"))
        for f in job_files:
            f.unlink()
        print(f"deleted {len(job_files)} job files", file=sys.stderr)

    # 4. delete last_run_summary so runner doesn't re-use cached totals
    if summary_file.exists():
        summary_file.unlink()
        print(f"deleted {summary_file}", file=sys.stderr)

    # 5. count shots in current shots.json
    with open(ROOT / "imports" / "shots.json") as f:
        shots = json.load(f)
    total = len(shots)
    print(f"shots.json total: {total}", file=sys.stderr)

    # 6. rewrite state
    state = {
        "project_id": "new_grok_story",
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
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    print(f"rewrote {state_file}: total_shots={total} completed_shots=0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())