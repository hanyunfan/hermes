"""Integration test for GenerationRunner — full pipeline via mock backend."""

from __future__ import annotations

from pathlib import Path

from video_director.core.project_manager import ProjectManager
from video_director.jobs import GenerationRunner, RunnerConfig, StateManager
from video_director.jobs.manager import make_job_id
from video_director.models import GenerationJob, JobStatus, Shot, ShotStatus, VideoClip

from ..conftest import temp_project_root, make_pm


def test_runner_completes_all_shots_with_mock_backend():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        # 3 shot files
        for i in range(3):
            sh = Shot(shot_id=f"s{i}", scene_id="sc1", duration_sec=0.5,
                      prompt=f"clip {i}", action="x", seed=42 + i)
            pm.save_shot(paths, sh)
        runner = GenerationRunner(paths, project_manager=pm,
                                  config=RunnerConfig(backend="mock", max_retries=1))
        summary = runner.run()
        assert summary.total == 3
        assert summary.completed == 3
        assert summary.failed == 0


def test_runner_is_idempotent_after_completion():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sh = Shot(shot_id="s1", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
        pm.save_shot(paths, sh)
        runner = GenerationRunner(paths, project_manager=pm,
                                  config=RunnerConfig(backend="mock"))
        first = runner.run()
        assert first.completed == 1
        second = runner.run()
        assert second.completed == 0  # nothing new to do


def test_runner_resume_picks_up_failed_shot():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        # Simulate a half-done run: 1 completed, 1 still pending
        sm = StateManager(paths)
        sm.save_job(GenerationJob(
            job_id=make_job_id("demo", "done", 1),
            shot_id="done", scene_id="sc1", project_id="demo",
            backend="mock", attempt=1, status=JobStatus.COMPLETED,
            output_path=str(paths.output_clips_dir / "done.mp4"),
        ))
        sm.save_clip(VideoClip(
            shot_id="done", path=str(paths.output_clips_dir / "done.mp4"),
            duration_sec=1.0,
        ))
        sh1 = Shot(shot_id="done", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
        sh2 = Shot(shot_id="todo", scene_id="sc1", duration_sec=0.5, prompt="p", action="x")
        pm.save_shot(paths, sh1)
        pm.save_shot(paths, sh2)
        runner = GenerationRunner(paths, project_manager=pm,
                                  config=RunnerConfig(backend="mock"))
        summary = runner.run()
        # "done" stays completed (eligible_shot_ids skips it); "todo" runs.
        assert summary.completed == 1
        # Output for todo should exist
        assert (paths.output_clips_dir / "todo.mp4").exists()


def test_runner_marks_shot_status_on_completion():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("demo", from_template=False)
        paths = pm.paths_for_id("demo")
        sh = Shot(shot_id="mark_me", scene_id="sc1", duration_sec=0.5,
                  prompt="p", action="x")
        pm.save_shot(paths, sh)
        runner = GenerationRunner(paths, project_manager=pm,
                                  config=RunnerConfig(backend="mock"))
        runner.run()
        # Reload shot — should now be COMPLETED
        reloaded = next(pm.iter_shots(paths))
        assert reloaded.shot_id == "mark_me"
        assert reloaded.status == ShotStatus.COMPLETED
        assert reloaded.output_clip.endswith("mark_me.mp4")