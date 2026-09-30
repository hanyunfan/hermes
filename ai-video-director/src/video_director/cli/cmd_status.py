"""``status`` command: print the current run state."""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from ..jobs import StateManager
from .common import json_dumps_safe, print_error


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
        sm = StateManager(paths)
        rs = sm.load_run_state()
        jobs = list(sm.iter_jobs())
        clips = list(sm.iter_clips())
    except Exception as e:
        return print_error(e)
    if args.json:
        print(json_dumps_safe({
            "run_state": rs.to_dict(),
            "jobs": [j.to_dict() for j in jobs],
            "clips": [c.to_dict() for c in clips],
        }))
        return 0
    print(f"project: {args.project}")
    print(f"  state: {rs.state.value}")
    print(f"  backend: {rs.backend or '(none yet)'}")
    print(f"  shots: total={rs.total_shots} completed={rs.completed_shots} "
          f"failed={rs.failed_shots} skipped={rs.skipped_shots}")
    print(f"  max_retries: {rs.max_retries}")
    print(f"  jobs recorded: {len(jobs)}")
    print(f"  clips recorded: {len(clips)}")
    return 0