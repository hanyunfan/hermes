"""Integration test for StateManager."""

from __future__ import annotations

import pytest

from video_director.core.project_manager import ProjectManager
from video_director.jobs import StateManager, make_job_id
from video_director.models import GenerationJob, JobStatus, Shot, ShotStatus, VideoClip

from ..conftest import temp_project_root, make_pm


def test_state_persistence_across_instances():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        # Write
        job = GenerationJob(
            job_id="demo__s1__a001__abcd1234",
            shot_id="s1", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1,
        )
        sm.save_job(job)
        # New instance — state must persist
        sm2 = StateManager(paths)
        loaded = sm2.load_job(job.job_id)
        assert loaded is not None
        assert loaded.shot_id == "s1"
        assert loaded.attempt == 1


def test_next_attempt_increments():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        assert sm.next_attempt_for_shot("s1") == 1
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "s1", 1),
            shot_id="s1", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1,
        ))
        assert sm.next_attempt_for_shot("s1") == 2


def test_eligible_shot_ids_skips_completed():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "s1", 1),
            shot_id="s1", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1, status=JobStatus.COMPLETED,
        ))
        eligible = sm.eligible_shot_ids(["s1", "s2", "s3"], max_retries=3)
        assert "s1" not in eligible
        assert "s2" in eligible and "s3" in eligible


def test_eligible_skips_when_retries_exhausted():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        for attempt in range(1, 4):
            sm.save_job(GenerationJob(
                job_id=make_job_id("demo", "s1", attempt),
                shot_id="s1", scene_id="sc1", project_id="demo",
                backend="mock", attempt=attempt, status=JobStatus.FAILED,
            ))
        eligible = sm.eligible_shot_ids(["s1"], max_retries=3)
        assert "s1" not in eligible


def test_clear_jobs_for_shot():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "s1", 1),
            shot_id="s1", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1,
        ))
        sm.save_clip(VideoClip(
            shot_id="s1", path="/tmp/x", duration_sec=1.0,
        ))
        removed = sm.clear_jobs_for_shot("s1")
        assert removed == 2
        assert not (paths.state_jobs_dir / f"{make_job_id('demo','s1',1)}.json").exists()


def test_recompute_counters():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sm = StateManager(paths)
        # one success + one failure
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "ok", 1),
            shot_id="ok", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1, status=JobStatus.COMPLETED,
        ))
        from video_director.models import VideoClip
        sm.save_clip(VideoClip(shot_id="ok", path="/tmp/x.mp4", duration_sec=1.0, file_size_bytes=100))
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "bad", 1),
            shot_id="bad", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1, status=JobStatus.FAILED,
        ))
        rs = sm.recompute_counters(total_shots=2)
        assert rs.completed_shots == 1
        assert rs.failed_shots == 1