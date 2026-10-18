"""Regression tests for the VideoGenerator protocol contract.

The runner now passes ``reference_images_ordered`` and
``reference_videos_ordered`` (ref2v / chain conditioning, 2026-10-12) to
every backend. The base ABC exposes them as kwargs (default None) so
backends that don't implement ref2v don't TypeError on the call site.

This test pins the contract: any VideoGenerator subclass must accept
those kwargs by name; otherwise the runner will fail again the next
time someone implements a new backend.

It also runs a quick mock generator smoke (one shot, default empty
refs) to verify the path doesn't TypeError under real call-site args.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from video_director.generators.base import VideoGenerator
from video_director.generators.mock import MockVideoGenerator


def _all_concrete_subclasses():
    found = []
    for name in dir(__import__("video_director.generators", fromlist=["*"])):
        cls = getattr(__import__("video_director.generators", fromlist=["*"]), name)
        if (
            inspect.isclass(cls)
            and issubclass(cls, VideoGenerator)
            and cls is not VideoGenerator
        ):
            found.append(cls)
    return found


@pytest.mark.parametrize(
    "cls", _all_concrete_subclasses(), ids=lambda c: c.__name__
)
def test_backend_accepts_ref2v_kwargs(cls):
    """Every concrete VideoGenerator must accept reference_*_ordered kwargs.

    Without this, the runner's call site (which passes these kwargs
    unconditionally) would TypeError on every backend that didn't add
    them to its signature, exactly the failure pattern of
    MockVideoGenerator when ref2v first shipped.
    """
    sig = inspect.signature(cls.generate)
    for name in ("reference_images_ordered", "reference_videos_ordered"):
        assert name in sig.parameters, (
            f"{cls.__name__}.generate() missing kwarg {name!r}; "
            f"the runner calls .generate(...) with this kwarg unconditionally."
        )


def test_mock_signature_matches_abc():
    """The mock backend must satisfy the ABC contract — Python's ABC
    machinery will refuse to instantiate MockVideoGenerator otherwise."""
    # Instantiate the mock generator; ABC's abstract method check
    # happens here. If the mock's .generate() drifted from the ABC
    # signature, this raises TypeError before any test can run.
    MockVideoGenerator()


def test_mock_generate_handles_ref2v_kwargs(tmp_path: Path):
    """Calling mock backend with ref2v kwargs must not raise TypeError."""
    from video_director.models.shot import Shot

    gen = MockVideoGenerator(width=320, height=180)
    shot = Shot(
        shot_id="mock_test_shot",
        scene_id="mock_test_scene",
        shot_index=1,
        duration_sec=1.0,
        prompt="test prompt",
        action="",
    )
    out = gen.generate(
        shot,
        output_dir=tmp_path,
        references=None,
        seed_override=None,
        context=None,
        reference_images_ordered=[{"basename": "fake.jpg"}],  # ignored by mock
        reference_videos_ordered=[{"basename": "fake.mp4"}],  # ignored by mock
    )
    assert out.output_path.exists()
    assert out.output_path.stat().st_size > 0
    assert out.metadata.get("backend") == "mock"
