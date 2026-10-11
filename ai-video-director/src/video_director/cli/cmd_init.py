"""``init`` command: scaffold a new project from the template."""

from __future__ import annotations

from pathlib import Path

from ..core.project_manager import ProjectManager
from ..models.base import validate_id
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    project_id = validate_id(args.project, "project_id")
    try:
        project = pm.init_project(
            project_id,
            title=args.title or "",
            description=args.description or "",
            language=args.language or "en",
            target_duration_sec=float(args.duration or 0.0),
            from_template=not args.no_template,
            template_name=args.template,
        )
    except Exception as e:
        return print_error(e)
    root = pm.project_root_for(project_id)
    print(f"[ok] initialised project {project.project_id!r} at {root}")
    print(f"     edit story.yaml, characters/, scenes/, shots/ then run:")
    print(f"       video-director analyze {project_id}")
    print(f"       video-director storyboard {project_id}")
    print(f"       video-director generate {project_id}")
    return 0