"""``generate`` command: run the generation runner over a project's shots."""

from __future__ import annotations

import argparse

from ..core.project_manager import ProjectManager
from ..jobs import GenerationRunner, RunnerConfig
from ..utils.io import write_yaml
from .common import print_error


def _build_runner_config(args: argparse.Namespace) -> RunnerConfig:
    return RunnerConfig(
        backend=getattr(args, "backend", "mock") or "mock",
        max_concurrent_jobs=int(getattr(args, "max_concurrent_jobs", 1) or 1),
        max_retries=int(getattr(args, "max_retries", 3) or 3),
        retry_with_new_seed=not getattr(args, "no_new_seed", False),
        force_regenerate=bool(getattr(args, "force", False)),
    )


def run(args, pm: ProjectManager) -> int:
    config = _build_runner_config(args)
    try:
        paths = pm.paths_for_id(args.project)
        pm.load_project(paths.root)
        runner = GenerationRunner(paths, project_manager=pm, config=config)
        only = getattr(args, "only", None)
        only_list = [s.strip() for s in only.split(",")] if only else None
        summary = runner.run(only_shots=only_list, reset=getattr(args, "reset", False))
    except Exception as e:
        return print_error(e)
    summary_path = paths.state_dir / "last_run_summary.json"
    write_yaml(summary_path, summary.to_dict())
    print(
        f"[done] backend={config.backend} total={summary.total} "
        f"completed={summary.completed} failed={summary.failed} "
        f"skipped={summary.skipped}"
    )
    print(f"       summary: {summary_path}")
    return 0 if summary.failed == 0 else 6