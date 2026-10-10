"""``build`` command — turn imports/*.json into framework yaml.

Pipeline:

  validate-imports (passes)
       ↓
  build  (this)
       ↓
  validate  (cross-checks)
       ↓
  generate --backend comfyui

Refuses to write if validation fails. Overwrites existing yaml without
prompting (imports/ is the source of truth).
"""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from ..imports import (
    ImportError,
    build_yaml_from_imports,
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
    if not report.ok:
        print(report.render())
        print("\n[error] build refuses to write yaml: fix imports/ and re-run.")
        return 4

    written = build_yaml_from_imports(bundle)
    print(
        f"[ok] build wrote {len(written['story'])} story, "
        f"{len(written['characters'])} characters, "
        f"{len(written['scenes'])} scenes, "
        f"{len(written['shots'])} shots"
    )
    for category, paths_ in written.items():
        for p in paths_:
            print(f"  {p.relative_to(paths.root.parent)}")

    print(
        "\nNext: video-director validate " + args.project +
        " (cross-checks) then video-director generate " + args.project +
        " --backend comfyui"
    )
    return 0
