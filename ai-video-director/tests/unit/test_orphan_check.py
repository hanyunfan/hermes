"""Tests for the assemble-time orphan detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_director.cli.cmd_assemble import _check_orphan_clips  # noqa: E402


def _make_paths(tmp_path):
    """Build a ProjectPaths-like with just the dirs _check_orphan_clips needs."""
    # Use SimpleNamespace duck-typing so we don't need a real project
    from types import SimpleNamespace
    output_clips_dir = tmp_path / "output" / "clips"
    output_clips_dir.mkdir(parents=True)
    # Write some "shots" yaml names
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir(parents=True)
    return SimpleNamespace(output_clips_dir=output_clips_dir, shots_dir=shots_dir), output_clips_dir


def test_orphan_check_clean(tmp_path):
    paths, clips = _make_paths(tmp_path)
    (clips / "shot_001.mp4").write_bytes(b"x")
    (clips / "shot_002.mp4").write_bytes(b"y")
    missing, orphans = _check_orphan_clips(paths, {"shot_001", "shot_002"})
    assert missing == []
    assert orphans == []


def test_orphan_check_missing(tmp_path):
    paths, clips = _make_paths(tmp_path)
    (clips / "shot_001.mp4").write_bytes(b"x")
    missing, orphans = _check_orphan_clips(paths, {"shot_001", "shot_002", "shot_003"})
    assert missing == ["shot_002", "shot_003"]
    assert orphans == []


def test_orphan_check_orphan_detected(tmp_path):
    paths, clips = _make_paths(tmp_path)
    (clips / "shot_001.mp4").write_bytes(b"x")
    (clips / "shot_002.mp4").write_bytes(b"y")
    (clips / "leftover.mp4").write_bytes(b"z")
    missing, orphans = _check_orphan_clips(paths, {"shot_001"})
    assert missing == []
    # Both shot_002 (in on-disk, not in expected) and leftover are orphans
    assert set(orphans) == {"shot_002", "leftover"}


def test_orphan_check_both_missing_and_orphan(tmp_path):
    paths, clips = _make_paths(tmp_path)
    (clips / "shot_001.mp4").write_bytes(b"x")
    (clips / "extra.mp4").write_bytes(b"z")
    missing, orphans = _check_orphan_clips(paths, {"shot_001", "shot_002"})
    assert missing == ["shot_002"]
    assert orphans == ["extra"]
