"""Shared test helpers — fixture builders for projects."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from video_director.core.project_manager import ProjectManager


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "projects" / "template"


@contextmanager
def temp_project_root() -> Iterator[Path]:
    """Yield a clean tempdir with projects/template/ seeded from the real one.

    Each test gets its own isolated filesystem so it can run in parallel.
    """
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if TEMPLATE_DIR.exists():
            shutil.copytree(TEMPLATE_DIR, td / "projects" / "template")
        else:
            (td / "projects" / "template").mkdir(parents=True)
            (td / "projects" / "template" / "project.yaml").write_text(
                "project_id: template\ntitle: t\n"
            )
        yield td


def make_pm(root: Path) -> ProjectManager:
    return ProjectManager(root)
