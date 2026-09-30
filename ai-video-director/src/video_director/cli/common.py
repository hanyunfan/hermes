"""Shared CLI helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..core.errors import (
    ProjectError,
    ProjectExistsError,
    ProjectNotFoundError,
    ValidationError,
    WorkflowNotFoundError,
    AssemblyError,
    GenerationError,
)
from ..core.project_manager import ProjectManager


def root_dir_from_env_or_cwd() -> Path:
    """Resolve the framework root directory.

    Priority:
      1. ``VIDEO_DIRECTOR_ROOT`` env var
      2. Current working directory
    """
    env = os.environ.get("VIDEO_DIRECTOR_ROOT")
    return Path(env).resolve() if env else Path.cwd().resolve()


def make_project_manager(root: str | Path | None = None) -> ProjectManager:
    if root is None:
        root = root_dir_from_env_or_cwd()
    return ProjectManager(root)


def print_error(e: BaseException) -> int:
    """Pretty-print a known error and return the exit code."""
    code = 1
    if isinstance(e, ProjectNotFoundError):
        code = 2
        print(f"[project-not-found] {e}")
    elif isinstance(e, ProjectExistsError):
        code = 3
        print(f"[project-exists] {e}")
    elif isinstance(e, WorkflowNotFoundError):
        code = 4
        print(f"[workflow-not-found] {e}")
    elif isinstance(e, ValidationError):
        code = 5
        print(f"[validation-error] {e}")
    elif isinstance(e, GenerationError):
        code = 6
        print(f"[generation-error] {e}")
    elif isinstance(e, AssemblyError):
        code = 7
        print(f"[assembly-error] {e}")
    elif isinstance(e, ProjectError):
        print(f"[project-error] {e}")
    else:
        print(f"[unexpected] {type(e).__name__}: {e}")
    return code


def json_dumps_safe(obj, indent: int = 2) -> str:
    return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)


def project_arg(value: str) -> str:
    """Validate a project id passed on the command line."""
    from ..models.base import validate_id
    return validate_id(value, "project_id")