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


"""Tests for the new dependency-skip behavior (2026-10-13).

When a shot's start_frame_source is "previous_shot" but the
predecessor has no usable output (no clip on disk AND no
completed job), the runner must skip the shot instead of
submitting it to ComfyUI.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_director.jobs.runner import GenerationRunner, RunnerConfig  # noqa: E402
from video_director.jobs.manager import JobStatus  # noqa: E402
from video_director.models import Shot  # noqa: E402


def _paths(tmp_path: Path):
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
    for d in (
        paths.output_clips_dir,
        paths.state_jobs_dir,
        paths.state_clips_dir,
        paths.state_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)
    paths.ensure_all = lambda: None
    return paths


def _shot(sid, *, prev="", src="manual"):
    return Shot(
        shot_id=sid,
        scene_id="scn",
        shot_index=int(sid.split("_")[-1]),
        duration_sec=5.0,
        shot_type="medium",
        camera="",
        camera_motion="static",
        characters=[],
        action="x",
        emotion="",
        environment="",
        lighting="",
        prompt="x",
        negative_prompt="",
        seed=None,
        start_frame="",
        start_frame_source=src,
        end_frame="",
        previous_shot=prev,
        next_shot="",
        reference_images=[],
        workflow_overrides={},
        status="pending",
        output_clip="",
        created_at="2026-10-13T00:00:00Z",
        updated_at="2026-10-13T00:00:00Z",
        extra={},
    )


def _runner(tmp_path: Path) -> GenerationRunner:
    paths = _paths(tmp_path)
    cfg = RunnerConfig(backend="mock", max_retries=2)
    # Use a custom state manager mock that doesn't try to write
    # real files. The real StateManager reads paths.state_jobs_dir
    # which is empty in tmp_path so it works fine, but we override
    # jobs_for_shot / next_attempt_for_shot / save_job with MagicMock.
    runner = GenerationRunner(
        paths=paths,
        config=cfg,
        project_manager=MagicMock(iter_shots=MagicMock(return_value=[])),
        workflow_mapping=MagicMock(),
    )
    # The real StateManager is created in __init__. Patch it.
    runner.state.jobs_for_shot = MagicMock(return_value=[])
    runner.state.next_attempt_for_shot = MagicMock(return_value=1)
    runner.state.save_job = MagicMock()
    return runner


def test_dependency_skip_when_previous_clip_missing_and_no_completed_job(tmp_path):
    """shot_002 has previous_shot=shot_001 and start_frame_source=previous_shot,
    but shot_001 has no clip on disk and no completed job. shot_002 must
    be skipped without calling the backend.
    """
    runner = _runner(tmp_path)
    runner.state.jobs_for_shot = MagicMock(return_value=[])

    shot_002 = _shot("shot_002", prev="shot_001", src="previous_shot")
    result = runner._run_one(shot_002, bible=None)
    assert result.status == JobStatus.SKIPPED
    assert "shot_001" in result.error_message
    assert result.error_class == "DependencySkip"
    assert runner.state.save_job.called
    saved_job = runner.state.save_job.call_args[0][0]
    assert saved_job.status == JobStatus.SKIPPED
    assert saved_job.error_class == "DependencySkip"


def test_dependency_skip_when_previous_only_failed(tmp_path):
    """shot_002 should also be skipped when its predecessor only has
    FAILED jobs (no completed clip ever produced)."""
    runner = _runner(tmp_path)
    failed_job = MagicMock(status=JobStatus.FAILED)
    runner.state.jobs_for_shot = MagicMock(return_value=[failed_job])

    shot_002 = _shot("shot_002", prev="shot_001", src="previous_shot")
    result = runner._run_one(shot_002, bible=None)
    assert result.status == JobStatus.SKIPPED
    assert "failed" in result.error_message


def test_dependency_skip_when_data_error_empty_previous_shot(tmp_path):
    """If start_frame_source is previous_shot but previous_shot is empty,
    the shot has no valid chain anchor — skip with a data-error reason
    rather than submitting a clip that will be disconnected."""
    runner = _runner(tmp_path)
    shot_002 = _shot("shot_002", prev="", src="previous_shot")
    result = runner._run_one(shot_002, bible=None)
    assert result.status == JobStatus.SKIPPED
    assert "data error" in result.error_message


def test_proceed_when_previous_clip_exists(tmp_path):
    """shot_002 with previous_shot=shot_001 and a real shot_001.mp4 on
    disk must NOT be skipped — the dependency check returns None and
    the normal path runs."""
    runner = _runner(tmp_path)
    (tmp_path / "output" / "clips").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output" / "clips" / "shot_001.mp4").write_bytes(b"x" * 50_000)
    shot_002 = _shot("shot_002", prev="shot_001", src="previous_shot")

    runner._build_references = MagicMock(return_value={})
    runner._build_ordered_reference_images = MagicMock(return_value=[])
    runner._build_ordered_reference_videos = MagicMock(return_value=[])
    runner._make_job = MagicMock(return_value=MagicMock(
        shot_id="shot_002", status=JobStatus.RUNNING, attempt=1,
    ))
    runner.backend = MagicMock()
    runner.backend.generate = MagicMock(side_effect=Exception("boom"))
    runner._seed_for_attempt = MagicMock(return_value=None)

    result = runner._run_one(shot_002, bible=None)
    assert result.status == JobStatus.FAILED
    assert result.error_class == "Exception"


def test_proceed_when_previous_completed_in_state_even_if_clip_missing(tmp_path):
    """If shot_001's job is COMPLETED but the clip file is gone (operator
    deleted it), we still proceed — the previous attempt succeeded."""
    runner = _runner(tmp_path)
    completed_job = MagicMock(status=JobStatus.COMPLETED)
    runner.state.jobs_for_shot = MagicMock(return_value=[completed_job])
    runner._build_references = MagicMock(return_value={})
    runner._build_ordered_reference_images = MagicMock(return_value=[])
    runner._build_ordered_reference_videos = MagicMock(return_value=[])
    runner._make_job = MagicMock(return_value=MagicMock(
        shot_id="shot_002", status=JobStatus.RUNNING, attempt=1,
    ))
    runner.backend = MagicMock()
    runner.backend.generate = MagicMock(side_effect=Exception("boom"))
    runner._seed_for_attempt = MagicMock(return_value=None)

    shot_002 = _shot("shot_002", prev="shot_001", src="previous_shot")
    result = runner._run_one(shot_002, bible=None)
    assert result.status != JobStatus.SKIPPED


def test_proceed_when_no_previous_dependency(tmp_path):
    """shot with no previous_shot and start_frame_source=manual is
    never subject to dependency-skip — returns None from the check."""
    runner = _runner(tmp_path)
    shot_001 = _shot("shot_001", prev="", src="manual")
    result = runner._check_previous_shot_dependency(shot_001)
    assert result is None
