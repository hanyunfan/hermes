"""Shot management helpers (loaders / writers).

Mirrors :mod:`video_director.scenes` for shots.
"""

from __future__ import annotations

from typing import Iterable

from ..core.paths import ProjectPaths
from ..core.project_manager import ProjectManager
from ..models import Shot


def list_shots(paths: ProjectPaths, pm: ProjectManager) -> list[Shot]:
    return list(pm.iter_shots(paths))


def save_shot(paths: ProjectPaths, pm: ProjectManager, shot: Shot) -> None:
    pm.save_shot(paths, shot)


def save_all(paths: ProjectPaths, pm: ProjectManager, shots: Iterable[Shot]) -> int:
    n = 0
    for sh in shots:
        save_shot(paths, pm, sh)
        n += 1
    return n