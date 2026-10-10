"""``validate-imports`` command — check imports/*.json files.

This is the FIRST command in the Grok-driven pipeline:

  video-director validate-imports <project>

Reads projects/<id>/imports/*.json and runs every rule in
:mod:`video_director.imports.checker`. Prints a human-readable report
and exits non-zero if any errors were found.
"""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from ..imports import (
    ImportError,
    check_imports,
    load_imports,
)


def run(args, pm: ProjectManager) -> int:
    try:
        paths = pm.paths_for_id(args.project)
    except Exception as e:
        print(f"[project-not-found] {e}")
        return 2

    try:
        bundle = load_imports(paths.root)
    except ImportError as e:
        print(f"[error] {e}")
        return 3

    report = check_imports(bundle)
    print(report.render())

    # Show a brief summary of what was found
    n_chars = len(bundle.characters)
    n_scenes = len(bundle.scenes)
    n_shots = len(bundle.shots)
    n_dlg = len(bundle.dialogues)
    print(
        f"\n=== summary: {n_chars} characters, {n_scenes} scenes, "
        f"{n_shots} shots, {n_dlg} dialogues ==="
    )

    return 0 if report.ok else 4
