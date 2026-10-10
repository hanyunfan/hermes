"""Generation runner.

Owns the orchestration loop: iterate shots in order, ask the backend to
generate each one, persist a :class:`GenerationJob`, persist a
:class:`VideoClip` on success, retry up to ``max_retries`` on failure,
and resume from the on-disk state.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..continuity.manager import ContinuityManager
from ..core.errors import GenerationError, ValidationError
from ..core.paths import ProjectPaths
from ..core.project_manager import ProjectManager
from ..models import (
    ContinuityState,
    GenerationJob,
    JobStatus,
    Shot,
    ShotStatus,
    VideoClip,
    WorkflowMapping,
)
from ..models.character import CharacterBible
from ..models.enums import GenerationState
from ..utils.io import read_yaml
from ..utils.logging import get_logger
from .manager import StateManager, make_job_id


_LOG = get_logger("video_director.jobs.runner")


@dataclass
class RunnerConfig:
    backend: str = "mock"
    max_concurrent_jobs: int = 1
    max_retries: int = 3
    retry_with_new_seed: bool = True
    skip_qa_on_resume: bool = False
    # When True, a shot whose mp4 already exists in output/clips/ is treated
    # as completed and skipped (default). When False, the shot is regenerated
    # and overwrites the existing mp4 atomically (only writes once a new file
    # is fully downloaded, so a crash mid-run never leaves a corrupt file).
    force_regenerate: bool = False


@dataclass
class ShotResult:
    """Per-shot summary for the caller."""

    shot_id: str
    status: JobStatus
    output_path: str = ""
    attempts: int = 0
    error_class: str = ""
    error_message: str = ""


@dataclass
class RunSummary:
    """Top-level summary returned by :meth:`GenerationRunner.run`."""

    started_at: str = ""
    finished_at: str = ""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[ShotResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "results": [r.__dict__ for r in self.results],
        }


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GenerationRunner:
    """Run a project: iterate shots, generate, persist state, retry."""

    def __init__(
        self,
        paths: ProjectPaths,
        *,
        workflow_mapping: WorkflowMapping | None = None,
        project_manager: ProjectManager | None = None,
        config: RunnerConfig | None = None,
    ):
        self.paths = paths
        self.pm = project_manager or ProjectManager(paths.root.parent.parent)
        self.config = config or RunnerConfig()
        self.state = StateManager(paths)
        self.workflow_mapping = workflow_mapping or self._load_workflow_mapping()
        self.backend = self._resolve_backend()
        self.continuity = ContinuityManager()

    # ---- helpers -----------------------------------------------------

    def _load_workflow_mapping(self) -> WorkflowMapping:
        if not self.paths.workflow_mapping_file.exists():
            return WorkflowMapping()
        raw = read_yaml(self.paths.workflow_mapping_file)
        if not raw:
            return WorkflowMapping()
        return WorkflowMapping.from_dict(raw)

    def _resolve_backend(self):
        from ..generators import get_registry  # local import to avoid cycles
        try:
            return get_registry().create(self.config.backend)
        except KeyError as e:
            raise ValidationError(str(e)) from e

    def _load_bible(self) -> CharacterBible:
        from ..characters import CharacterBibleService
        return CharacterBibleService(self.pm).load(self.paths)

    # ---- main entry --------------------------------------------------

    def run(
        self,
        shots: list[Shot] | None = None,
        *,
        reset: bool = False,
        only_shots: list[str] | None = None,
        progress_cb: Callable[[ShotResult], None] | None = None,
    ) -> RunSummary:
        if reset:
            removed = self.state.clear_all()
            _LOG.info("reset state: removed %d prior state files", removed)
        all_shots = list(shots or self.pm.iter_shots(self.paths))
        if only_shots:
            wanted = set(only_shots)
            all_shots = [s for s in all_shots if s.shot_id in wanted]
        all_shots.sort(key=lambda s: (s.scene_id, s.shot_index))
        total = len(all_shots)
        run_state = self.state.recompute_counters(total_shots=total)
        run_state.backend = self.config.backend
        run_state.max_concurrent_jobs = self.config.max_concurrent_jobs
        run_state.max_retries = self.config.max_retries
        run_state.state = GenerationState.RUNNING
        if not run_state.started_at:
            run_state.started_at = _now_iso()
        self.state.save_run_state(run_state)

        eligible_ids = self.state.eligible_shot_ids(
            [s.shot_id for s in all_shots], self.config.max_retries
        )
        shots_to_run = [s for s in all_shots if s.shot_id in set(eligible_ids)]

        bible = self._load_bible()
        summary = RunSummary(started_at=run_state.started_at, total=total)

        if self.config.max_concurrent_jobs > 1:
            _LOG.warning(
                "max_concurrent_jobs=%d requested, but this build runs serially; "
                "future work can parallelise the inner loop",
                self.config.max_concurrent_jobs,
            )

        for shot in shots_to_run:
            res = self._run_one(shot, bible)
            summary.results.append(res)
            if res.status == JobStatus.COMPLETED:
                summary.completed += 1
            elif res.status == JobStatus.SKIPPED:
                summary.skipped += 1
            else:
                summary.failed += 1
            if progress_cb:
                progress_cb(res)

        # summary.completed/failed/skipped here only count shots that were
        # *acted on in this run*. Already-done shots are visible via
        # ``state/recompute_counters()`` (the run_state file), not via the
        # RunSummary returned to the caller — otherwise idempotent reruns
        # would double-count work from previous invocations.
        summary.finished_at = _now_iso()
        run_state = self.state.recompute_counters(total_shots=total)
        if summary.failed > 0:
            run_state.state = GenerationState.FAILED
        else:
            run_state.state = GenerationState.COMPLETED
        self.state.save_run_state(run_state)
        return summary

    # ---- single shot -------------------------------------------------

    def _run_one(self, shot: Shot, bible: CharacterBible) -> ShotResult:
        _LOG.info("running shot %s (scene=%s)", shot.shot_id, shot.scene_id)
        references = self._build_references(shot, bible)

        # Idempotency: if the output mp4 already exists and force_regenerate is
        # not set, treat this shot as already-done and skip. Without this,
        # reruns would create a new mp4 every time and accumulate cruft.
        clip_path = self.paths.output_clips_dir / f"{shot.shot_id}.mp4"
        if clip_path.exists() and not self.config.force_regenerate:
            _LOG.info(
                "shot %s mp4 already exists at %s; skipping (force_regenerate=False)",
                shot.shot_id, clip_path,
            )
            return ShotResult(
                shot_id=shot.shot_id,
                status=JobStatus.SKIPPED,
                output_path=str(clip_path),
                attempts=0,
            )

        attempt = self.state.next_attempt_for_shot(shot.shot_id)
        last_error_class = ""
        last_error_message = ""

        while attempt <= self.config.max_retries + 1:  # +1 because attempt N is the Nth try
            job = self._make_job(shot, attempt)
            self.state.save_job(job)
            job.status = JobStatus.RUNNING
            job.started_at = _now_iso()
            self.state.save_job(job)
            try:
                outcome = self.backend.generate(
                    shot,
                    output_dir=self.paths.output_clips_dir,
                    references=references,
                    seed_override=self._seed_for_attempt(shot, attempt),
                    context={
                        "paths": self.paths,
                        "workflow_mapping": self.workflow_mapping,
                    },
                )
            except Exception as e:  # noqa: BLE001 — runner must record failures
                job.status = JobStatus.FAILED
                job.error_class = type(e).__name__
                job.error_message = str(e) or repr(e)
                job.finished_at = _now_iso()
                self.state.save_job(job)
                last_error_class = job.error_class
                last_error_message = job.error_message
                _LOG.warning(
                    "shot %s attempt %d failed: %s: %s",
                    shot.shot_id, attempt, last_error_class, last_error_message,
                )
                _LOG.exception("shot %s attempt %d full traceback:", shot.shot_id, attempt)
                attempt += 1
                if attempt > self.config.max_retries + 1:
                    break
                continue

            # Success: record job + clip
            job.status = JobStatus.COMPLETED
            job.seed_used = int(outcome.seed_used)
            job.prompt_used = outcome.prompt_used
            job.output_path = str(outcome.output_path)
            job.finished_at = _now_iso()
            self.state.save_job(job)
            clip = VideoClip(
                shot_id=shot.shot_id,
                path=str(outcome.output_path),
                duration_sec=float(outcome.duration_sec or shot.duration_sec),
                width=int(outcome.width or 0),
                height=int(outcome.height or 0),
                fps=float(outcome.fps or 0.0),
                file_size_bytes=int(outcome.file_size_bytes or 0),
                qa_passed=False,
                qa_notes=[],
            )
            self.state.save_clip(clip)
            # Reflect completion back onto the on-disk shot file
            self._mark_shot_status(shot, ShotStatus.COMPLETED, output_clip=str(outcome.output_path))
            return ShotResult(
                shot_id=shot.shot_id,
                status=JobStatus.COMPLETED,
                output_path=str(outcome.output_path),
                attempts=attempt,
            )

        # Exhausted retries
        self._mark_shot_status(shot, ShotStatus.FAILED)
        return ShotResult(
            shot_id=shot.shot_id,
            status=JobStatus.FAILED,
            attempts=max(0, attempt - 1),
            error_class=last_error_class,
            error_message=last_error_message,
        )

    def _make_job(self, shot: Shot, attempt: int) -> GenerationJob:
        job_id = make_job_id(self.paths.root.name, shot.shot_id, attempt)
        return GenerationJob(
            job_id=job_id,
            shot_id=shot.shot_id,
            scene_id=shot.scene_id,
            project_id=self.paths.root.name,
            backend=self.config.backend,
            attempt=attempt,
        )

    def _seed_for_attempt(self, shot: Shot, attempt: int) -> int | None:
        """Decide the seed for this attempt.

        First attempt honours ``shot.seed`` if set. Subsequent attempts:
          * if ``retry_with_new_seed`` is true, derive a new seed
          * otherwise keep the original seed
        """
        if attempt == 1 and shot.seed is not None:
            return shot.seed
        if not self.config.retry_with_new_seed:
            return shot.seed
        base = shot.seed if shot.seed is not None else hash(shot.shot_id)
        return (abs(base) + attempt * 1009 + int(time.time()) // 60) & 0x7FFFFFFF

    def _build_references(self, shot: Shot, bible: CharacterBible) -> dict[str, str]:
        refs: dict[str, str] = {}
        for char_id in shot.characters:
            ch = bible.get(char_id)
            if not ch:
                continue
            for ref in ch.reference_images:
                # The backend receives path strings (the adapter + backend decide
                # whether to read them as bytes or upload).
                refs[ref.role] = ref.path
        # Resolve start_frame based on start_frame_source. The two values are:
        #   "manual"          — use shot.start_frame path as-is
        #   "previous_shot"   — extract last frame from previous shot's mp4
        #                        into ComfyUI's input dir and use the new path
        if shot.start_frame_source == "previous_shot":
            extracted = self._extract_previous_shot_frame(shot)
            if extracted:
                refs["start_frame"] = extracted
            else:
                _LOG.warning(
                    "shot %s start_frame_source=previous_shot but no previous shot mp4 found; "
                    "falling back to manual start_frame",
                    shot.shot_id,
                )
                if shot.start_frame:
                    refs["start_frame"] = shot.start_frame
        elif shot.start_frame and not shot.start_frame.startswith("prev:"):
            refs.setdefault("start_frame", shot.start_frame)
        return refs

    def _extract_previous_shot_frame(self, shot: Shot) -> str | None:
        """Extract the last frame of shot.previous_shot's mp4 into ComfyUI's
        input directory so it can be referenced as LoadImage.

        Returns the absolute path to the new PNG, or None if extraction failed
        or there's no previous-shot mp4 available.
        """
        if not shot.previous_shot:
            return None
        prev_clip = self.paths.output_clips_dir / f"{shot.previous_shot}.mp4"
        if not prev_clip.exists():
            _LOG.warning("previous shot mp4 missing: %s", prev_clip)
            return None
        comfyui_input = Path("/home/frank/ComfyUI/input")
        if not comfyui_input.is_dir():
            _LOG.warning("ComfyUI input dir not found at %s", comfyui_input)
            return None
        out_png = comfyui_input / f"{shot.previous_shot}_end.png"
        # ffmpeg: take last frame (select the highest timestamp <= duration).
        # Using `-vf "select=eq(n\,0)"` would pick the first frame; we want last.
        # `-sseof -0.05` seeks to ~50ms before end so we land on a real frame.
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-sseof", "-0.1",
            "-i", str(prev_clip),
            "-frames:v", "1",
            "-update", "1",
            str(out_png),
        ]
        try:
            import subprocess
            subprocess.run(cmd, check=True, timeout=30)
        except Exception as e:
            _LOG.warning("ffmpeg extract failed for %s: %s", prev_clip, e)
            return None
        if not out_png.exists():
            return None
        return str(out_png)

    def _mark_shot_status(self, shot: Shot, status: ShotStatus, output_clip: str = "") -> None:
        shot.status = status
        if output_clip:
            shot.output_clip = output_clip
        shot.touch()
        try:
            self.pm.save_shot(self.paths, shot)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("failed to update shot %s status: %s", shot.shot_id, e)