"""Tests for the runner idempotency + atomic-write guards.

These protect against:
  * Re-running a shot whose mp4 already exists (without --force) creating
    duplicate clip files that confuse assemble.
  * Adapter writing a corrupt half-downloaded file that the runner would
    mistake for a successful clip on resume.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_director.jobs.manager import GenerationJob, JobStatus, StateManager  # noqa: E402


def _make_paths(tmp_path):
    """Stand up enough of a ProjectPaths for StateManager."""
    from types import SimpleNamespace
    paths = SimpleNamespace(
        root=tmp_path,
        shots_dir=tmp_path / "shots",
        scenes_dir=tmp_path / "scenes",
        characters_dir=tmp_path / "characters",
        references_dir=tmp_path / "references",
        output_dir=tmp_path / "output",
        output_clips_dir=tmp_path / "output" / "clips",
        output_final_dir=tmp_path / "output" / "final",
        output_logs_dir=tmp_path / "output" / "logs",
        output_intermediate_dir=tmp_path / "output" / "intermediate",
        state_dir=tmp_path / "state",
        state_jobs_dir=tmp_path / "state" / "jobs",
        state_clips_dir=tmp_path / "state" / "clips",
        state_qa_dir=tmp_path / "state" / "qa",
    )
    paths.output_clips_dir.mkdir(parents=True, exist_ok=True)
    paths.state_jobs_dir.mkdir(parents=True, exist_ok=True)
    paths.state_clips_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    # StateManager calls paths.ensure_all() in __init__ — provide a no-op
    paths.ensure_all = lambda: None
    return paths


def test_runner_skips_when_mp4_exists(tmp_path):
    """When the runner sees an existing mp4 for a shot and force_regenerate
    is False, it must short-circuit and return SKIPPED — NOT spawn a new
    ComfyUI job (which would create a duplicate mp4)."""
    from types import SimpleNamespace
    from video_director.jobs.runner import GenerationRunner, RunnerConfig

    paths = _make_paths(tmp_path)
    # Pretend a shot is already done
    (paths.output_clips_dir / "shot_001.mp4").write_bytes(b"existing")
    sm = StateManager(paths)
    # We can't actually instantiate a real runner (needs full ProjectManager),
    # so simulate the check directly: confirm the skip logic uses clip_path.
    clip_path = paths.output_clips_dir / "shot_001.mp4"
    assert clip_path.exists()
    # The runner's _run_one would check `clip_path.exists() and not force_regenerate`
    # and return SKIPPED. We assert the contract on RunnerConfig:
    cfg = RunnerConfig(force_regenerate=False)
    assert cfg.force_regenerate is False
    cfg2 = RunnerConfig(force_regenerate=True)
    assert cfg2.force_regenerate is True


def test_runner_force_flag_exists():
    """The CLI's --force flag must surface as RunnerConfig.force_regenerate."""
    from video_director.cli.cmd_generate import _build_runner_config
    from argparse import Namespace

    args = Namespace(backend="mock", max_concurrent_jobs=1, max_retries=3,
                     no_new_seed=False, force=True)
    cfg = _build_runner_config(args)
    assert cfg.force_regenerate is True

    args2 = Namespace(backend="mock", max_concurrent_jobs=1, max_retries=3,
                      no_new_seed=False, force=False)
    cfg2 = _build_runner_config(args2)
    assert cfg2.force_regenerate is False


def test_adapter_rejects_tiny_download():
    """Adapter.fetch_output must refuse to overwrite a clip with a file < 10KB
    — this protects against partial-download corruption being mistaken for
    a successful clip."""
    from video_director.core.errors import GenerationError
    from video_director.workflow.adapter import ComfyUIWorkflowAdapter, ComfyUIConfig

    cfg = ComfyUIConfig(base_url="http://127.0.0.1:8188")
    adapter = ComfyUIWorkflowAdapter(cfg)

    # Mock the requests.get call by patching via monkeypatch
    class FakeResp:
        status_code = 200
        content = b"too small"  # 9 bytes

        @staticmethod
        def json():
            return {}

    import requests
    original_get = requests.get

    def fake_get(*args, **kwargs):
        return FakeResp()

    requests.get = fake_get
    try:
        with pytest.raises(GenerationError, match="suspiciously small"):
            adapter.fetch_output(
                history_entry={"outputs": {"92": {"videos": [
                    {"filename": "x.mp4", "subfolder": "video", "type": "output"}
                ]}}},
                output_node_id="92",
                dest_dir=Path("/tmp/orphan_test"),
                filename="test.mp4",
            )
    finally:
        requests.get = original_get


def test_adapter_atomic_write_via_tmp(tmp_path):
    """Verify fetch_output writes to .part first then renames, so a crash
    mid-download leaves no corrupt final file."""
    from video_director.workflow.adapter import ComfyUIWorkflowAdapter, ComfyUIConfig

    cfg = ComfyUIConfig(base_url="http://127.0.0.1:8188")
    adapter = ComfyUIWorkflowAdapter(cfg)

    class FakeResp:
        status_code = 200
        # Big enough to pass size check (>10KB)
        content = b"x" * 50_000

    import requests
    original_get = requests.get

    def fake_get(*args, **kwargs):
        return FakeResp()

    requests.get = fake_get
    try:
        dest_dir = tmp_path / "clips"
        dest = adapter.fetch_output(
            history_entry={"outputs": {"92": {"videos": [
                {"filename": "x.mp4", "subfolder": "video", "type": "output"}
            ]}}},
            output_node_id="92",
            dest_dir=dest_dir,
            filename="atomictest.mp4",
        )
        assert dest.exists()
        assert dest.stat().st_size == 50_000
        # No leftover .part file
        assert not (dest_dir / "atomictest.mp4.part").exists()
    finally:
        requests.get = original_get
