"""Tests for scripts/check_git_safety.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_git_safety.py"
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def _run(workdir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), str(SCRIPT), "--workdir", str(workdir), "--no-git", *extra],
        capture_output=True, text=True, timeout=30,
    )


def test_clean_tree_passes(tmp_path):
    # tmp_path is empty
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ok]" in r.stdout


def test_real_workflow_json_flagged(tmp_path):
    (tmp_path / "real_workflow.json").write_text("{}")
    r = _run(tmp_path, "--strict")
    assert r.returncode == 1
    assert "real_workflow.json" in r.stdout


def test_private_dir_file_flagged(tmp_path):
    p = tmp_path / "private"
    p.mkdir()
    (p / "secret.json").write_text("{}")
    r = _run(tmp_path, "--strict")
    assert r.returncode == 1
    assert "secret.json" in r.stdout


def test_env_file_flagged(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=abc")
    r = _run(tmp_path, "--strict")
    assert r.returncode == 1


def test_video_in_output_flagged(tmp_path):
    p = tmp_path / "output" / "clips"
    p.mkdir(parents=True)
    (p / "shot_001.mp4").write_bytes(b"fake")
    r = _run(tmp_path, "--strict")
    assert r.returncode == 1
    assert "shot_001.mp4" in r.stdout


def test_template_readme_not_flagged(tmp_path):
    """README.md files inside the template dirs must NOT be flagged."""
    t = tmp_path / "projects" / "template" / "state"
    t.mkdir(parents=True)
    (t / "README.md").write_text("# state")
    r = _run(tmp_path, "--strict")
    assert r.returncode == 0


def test_strict_mode_vs_warn_only(tmp_path):
    (tmp_path / "real_workflow.json").write_text("{}")
    warn = _run(tmp_path)  # no --strict
    assert warn.returncode == 0
    assert "[warn]" in warn.stderr or "[risk]" in warn.stdout


def test_real_tree_passes():
    """The real repo tree may legitimately contain large generated mp4 files
    under ``projects/*/output/`` that are .gitignored — so when ``--no-git``
    is used (which bypasses gitignore), the script WILL flag them. That's
    correct behaviour: real_workflow_api.json inside projects/template/private/
    IS in .gitignore but still surfaces here, which is fine — the test just
    verifies the script runs without crashing.
    """
    r = _run(REPO_ROOT)
    # Returncode is 0 in non-strict mode regardless of findings
    assert r.returncode == 0
    # Output is either "[ok]" (clean) or "[risk] N file(s) flagged" — both valid
    assert "[ok]" in r.stdout or "[risk]" in r.stdout