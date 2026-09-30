"""``retry`` command: clear state for one or more shots and re-run generation."""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from ..jobs import GenerationRunner, RunnerConfig
from .cmd_generate import _build_runner_config
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    config = _build_runner_config(args)
    try:
        paths = pm.paths_for_id(args.project)
        pm.load_project(paths.root)
        from ..jobs import StateManager
        sm = StateManager(paths)
        shot_ids: list[str] = []
        if args.shot:
            shot_ids = [s.strip() for s in args.shot.split(",") if s.strip()]
            for sid in shot_ids:
                removed = sm.clear_jobs_for_shot(sid, project_id=args.project)
                print(f"     cleared {removed} file(s) for shot {sid}")
        elif args.reset_all:
            removed = sm.clear_all()
            print(f"     cleared {removed} state file(s)")
        else:
            from ..core.errors import ValidationError
            raise ValidationError("retry needs --shot <id[,id...]> or --reset-all")
        runner = GenerationRunner(paths, project_manager=pm, config=config)
        only = shot_ids if args.shot else None
        summary = runner.run(only_shots=only, reset=False)
    except Exception as e:
        return print_error(e)
    print(
        f"[done] retry completed={summary.completed} failed={summary.failed} "
        f"skipped={summary.skipped}"
    )
    return 0 if summary.failed == 0 else 6