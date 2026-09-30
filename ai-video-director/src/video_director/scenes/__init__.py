"""Scene management helpers (loaders / planners / writers).

This subpackage is a thin wrapper over :class:`ScenePlanner` and
:class:`Scene` persistence. It exists so the CLI can refer to
``video_director.scenes`` as a stable import path.
"""

from __future__ import annotations

from typing import Iterable

from ..core.paths import ProjectPaths
from ..core.project_manager import ProjectManager
from ..models import Scene
from ..utils.io import write_yaml


def list_scenes(paths: ProjectPaths, pm: ProjectManager) -> list[Scene]:
    return list(pm.iter_scenes(paths))


def save_scene(paths: ProjectPaths, pm: ProjectManager, scene: Scene) -> None:
    pm.save_scene(paths, scene)


def save_all(paths: ProjectPaths, pm: ProjectManager, scenes: Iterable[Scene]) -> int:
    n = 0
    for sc in scenes:
        save_scene(paths, pm, sc)
        n += 1
    return n