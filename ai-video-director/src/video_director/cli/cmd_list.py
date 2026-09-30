"""``list`` command: show registered projects."""

from __future__ import annotations

from ..core.project_manager import ProjectManager
from .common import print_error


def run(args, pm: ProjectManager) -> int:
    try:
        infos = pm.list_projects(include_template=args.include_template)
    except Exception as e:
        return print_error(e)
    if not infos:
        print("(no projects found)")
        return 0
    for info in infos:
        print(f"  {info.project_id}\t{info.status}\t{info.title}\t{info.path}")
    return 0