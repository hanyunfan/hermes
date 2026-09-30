"""Tests for MockVideoGenerator + registry."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from video_director.core.errors import GenerationError
from video_director.generators import MockVideoGenerator, get_registry
from video_director.models import Shot


def test_registry_has_mock_and_comfyui():
    names = get_registry().names()
    assert "mock" in names
    assert "comfyui" in names


def test_mock_generator_produces_file(tmp_path: Path):
    g = MockVideoGenerator()
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
    out = g.generate(shot, output_dir=tmp_path)
    assert out.output_path.exists()
    assert out.output_path.stat().st_size > 0
    assert out.duration_sec == 0.5


def test_mock_generator_seeds_different_clips(tmp_path: Path):
    g = MockVideoGenerator()
    s1 = Shot(shot_id="s1", scene_id="sc1", duration_sec=0.5, prompt="p", seed=1)
    s2 = Shot(shot_id="s2", scene_id="sc1", duration_sec=0.5, prompt="p", seed=99999)
    o1 = g.generate(s1, output_dir=tmp_path)
    o2 = g.generate(s2, output_dir=tmp_path)
    # Different seed → different colour → different content bytes
    assert o1.output_path.read_bytes() != o2.output_path.read_bytes()


def test_mock_generator_handles_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda x: None)
    with pytest.raises(GenerationError):
        MockVideoGenerator()


def test_mock_generator_cancel_returns_false():
    assert MockVideoGenerator().cancel("anything") is False