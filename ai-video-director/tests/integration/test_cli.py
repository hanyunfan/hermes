"""CLI integration tests: invoke each subcommand via subprocess."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def _run(*args, workdir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VIDEO_DIRECTOR_ROOT"] = str(workdir)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [str(PYTHON), "-m", "video_director.cli.main", *args],
        cwd=str(workdir), capture_output=True, text=True, env=env, timeout=60,
    )


@pytest.fixture
def project_root(tmp_path: Path):
    """Temp root with a seeded projects/template/ directory."""
    src = REPO_ROOT / "projects" / "template"
    if src.exists():
        shutil.copytree(src, tmp_path / "projects" / "template")
    else:
        (tmp_path / "projects" / "template").mkdir(parents=True)
        (tmp_path / "projects" / "template" / "project.yaml").write_text(
            "project_id: template\ntitle: t\n"
        )
    return tmp_path


def test_cli_help():
    r = _run("--help", workdir=Path("/tmp"))
    assert r.returncode == 0
    assert "video-director" in r.stdout


def test_cli_init_then_list(project_root):
    r = _run("init", "story_alpha", "--title", "Demo", "--duration", "120",
             workdir=project_root)
    assert r.returncode == 0, r.stderr or r.stdout
    r = _run("list", workdir=project_root)
    assert r.returncode == 0
    assert "story_alpha" in r.stdout


def test_cli_status_for_unknown_project(project_root):
    r = _run("status", "nope", workdir=project_root)
    assert r.returncode != 0  # ProjectNotFoundError → exit 2


def test_cli_full_lifecycle(project_root):
    """init → analyze → storyboard → validate → generate → status → assemble."""
    # init
    assert _run("init", "story", "--duration", "30", workdir=project_root).returncode == 0
    # analyze
    r = _run("analyze", "story", workdir=project_root)
    assert r.returncode == 0, r.stdout + r.stderr
    # storyboard
    r = _run("storyboard", "story", workdir=project_root)
    assert r.returncode == 0, r.stdout + r.stderr
    # validate
    r = _run("validate", "story", workdir=project_root)
    assert r.returncode == 0, r.stdout + r.stderr
    # generate with mock
    r = _run("generate", "story", "--backend", "mock", "--max-retries", "1",
             workdir=project_root)
    assert r.returncode == 0, r.stdout + r.stderr
    # status
    r = _run("status", "story", workdir=project_root)
    assert r.returncode == 0
    assert "completed=" in r.stdout
    # assemble (skip QA because mock clips pass duration min)
    r = _run("assemble", "story", "--skip-qa", workdir=project_root)
    assert r.returncode == 0, r.stdout + r.stderr
    final = project_root / "projects" / "story" / "output" / "final" / "final.mp4"
    assert final.exists()
    assert final.stat().st_size > 0


def test_cli_status_json(project_root):
    _run("init", "jsonproj", workdir=project_root)
    r = _run("status", "jsonproj", "--json", workdir=project_root)
    assert r.returncode == 0
    import json
    parsed = json.loads(r.stdout)
    assert "run_state" in parsed
    assert "jobs" in parsed