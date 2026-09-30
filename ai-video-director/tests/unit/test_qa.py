"""Tests for QAChecker."""

from __future__ import annotations

from pathlib import Path

from video_director.generators import MockVideoGenerator
from video_director.models import Shot, VideoClip
from video_director.quality import QAChecker, DEFAULT_RULES


def test_qa_passes_on_mock_clip(tmp_path: Path):
    g = MockVideoGenerator()
    shot = Shot(shot_id="qa1", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
    out = g.generate(shot, output_dir=tmp_path)
    clip = VideoClip(shot_id=shot.shot_id, path=str(out.output_path), duration_sec=out.duration_sec)
    result = QAChecker().check_clip(clip)
    assert result.passed, result.notes


def test_qa_flags_missing_file(tmp_path: Path):
    clip = VideoClip(shot_id="missing", path=str(tmp_path / "ghost.mp4"), duration_sec=1.0)
    result = QAChecker().check_clip(clip)
    assert not result.passed
    assert any("exists" in n for n in result.notes)


def test_qa_flags_empty_file(tmp_path: Path):
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    clip = VideoClip(shot_id="empty", path=str(p), duration_sec=1.0)
    result = QAChecker().check_clip(clip)
    assert not result.passed


def test_qa_propagates_dimensions_and_fps(tmp_path: Path):
    g = MockVideoGenerator()
    shot = Shot(shot_id="props", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
    out = g.generate(shot, output_dir=tmp_path)
    clip = VideoClip(shot_id=shot.shot_id, path=str(out.output_path), duration_sec=0)
    QAChecker().check_clip(clip)
    assert clip.width > 0 and clip.height > 0
    assert clip.fps > 0


def test_qa_custom_rules_can_be_passed(tmp_path: Path):
    clip = VideoClip(shot_id="x", path="/nonexistent", duration_sec=0)
    rules = []  # empty = nothing checked = pass
    result = QAChecker(rules=rules).check_clip(clip)
    assert result.passed
    assert DEFAULT_RULES, "DEFAULT_RULES should not be empty"