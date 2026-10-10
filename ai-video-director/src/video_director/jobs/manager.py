"""State manager.

Persists three layers of state so a generation run can be interrupted and
resumed safely:

1. Top-level run state — :class:`GenerationState` + counters + active job id.
   Stored at ``<project>/state/generation_state.json``.
2. Per-job records — one :class:`GenerationJob` per execution attempt.
   Stored at ``<project>/state/jobs/<job_id>.json``.
3. Per-shot derived state — latest successful :class:`VideoClip` and latest
   :class:`QAResult`. Stored at ``<project>/state/clips/<shot_id>.json``
   and ``<project>/state/qa/<shot_id>.json``.

Atomicity: every write is tmp-file-then-os.replace so a crash mid-write can
never leave a half-written JSON file. Reads tolerate a missing file
(returning ``None``) so first-run state loads cleanly.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core.errors import ValidationError
from ..core.paths import ProjectPaths
from ..models import GenerationJob, JobStatus, VideoClip
from ..models.enums import GenerationState
from ..utils.io import read_json, read_yaml, write_json, write_yaml
from ..utils.logging import get_logger


_LOG = get_logger("video_director.jobs.manager")


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}(__[a-z0-9_\-]{1,64})*$")


@dataclass
class GenerationRunState:
    """Top-level state of the entire generation run for a project."""

    project_id: str = ""
    state: GenerationState = GenerationState.NOT_STARTED
    started_at: str = ""
    updated_at: str = ""
    backend: str = ""
    max_concurrent_jobs: int = 1
    max_retries: int = 3
    total_shots: int = 0
    completed_shots: int = 0
    failed_shots: int = 0
    skipped_shots: int = 0
    last_job_id: str = ""
    last_error: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "state": self.state.value,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "backend": self.backend,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "max_retries": self.max_retries,
            "total_shots": self.total_shots,
            "completed_shots": self.completed_shots,
            "failed_shots": self.failed_shots,
            "skipped_shots": self.skipped_shots,
            "last_job_id": self.last_job_id,
            "last_error": self.last_error,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GenerationRunState":
        try:
            state = GenerationState(data.get("state", "not_started"))
        except ValueError:
            state = GenerationState.NOT_STARTED
        return cls(
            project_id=str(data.get("project_id", "")),
            state=state,
            started_at=str(data.get("started_at", "")),
            updated_at=str(data.get("updated_at", "")),
            backend=str(data.get("backend", "")),
            max_concurrent_jobs=int(data.get("max_concurrent_jobs", 1) or 1),
            max_retries=int(data.get("max_retries", 3) or 3),
            total_shots=int(data.get("total_shots", 0) or 0),
            completed_shots=int(data.get("completed_shots", 0) or 0),
            failed_shots=int(data.get("failed_shots", 0) or 0),
            skipped_shots=int(data.get("skipped_shots", 0) or 0),
            last_job_id=str(data.get("last_job_id", "")),
            last_error=str(data.get("last_error", "")),
            notes=list(data.get("notes", []) or []),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_id(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.match(value):
        raise ValidationError(f"{kind}={value!r} is not a valid slug")
    return value


def make_job_id(project_id: str, shot_id: str, attempt: int) -> str:
    """Build a stable, sortable job id.

    Pattern: ``<project>__<shot>__a<NNN>__<short-uuid>``. The attempt suffix
    means lexical sort == chronological sort for human eyeballing.
    """
    short = uuid.uuid4().hex[:8]
    _validate_id(project_id, "project_id")
    _validate_id(shot_id, "shot_id")
    return f"{project_id}__{shot_id}__a{attempt:03d}__{short}"


class StateManager:
    """Owns all per-project state files.

    All write paths are atomic. Reads tolerate missing files so first-run
    bootstrapping is a no-op.
    """

    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        paths.ensure_all()

    # ---- top-level run state ----------------------------------------

    def run_state_file(self) -> Path:
        return self.paths.state_dir / "generation_state.json"

    def load_run_state(self) -> GenerationRunState:
        f = self.run_state_file()
        if not f.exists():
            return GenerationRunState(project_id=self.paths.root.name)
        raw = read_json(f)
        if not isinstance(raw, dict):
            raise ValidationError(f"generation_state.json is not a mapping: {f}")
        return GenerationRunState.from_dict(raw)

    def save_run_state(self, state: GenerationRunState) -> None:
        state.updated_at = _now_iso()
        write_json(self.run_state_file(), state.to_dict())

    def reset_run_state(self) -> GenerationRunState:
        """Clear run-level counters (used when starting fresh)."""
        state = GenerationRunState(
            project_id=self.paths.root.name,
            state=GenerationState.NOT_STARTED,
        )
        self.save_run_state(state)
        return state

    # ---- job lifecycle ----------------------------------------------

    def job_file(self, job_id: str) -> Path:
        _validate_id(job_id, "job_id")
        return self.paths.state_jobs_dir / f"{job_id}.json"

    def save_job(self, job: GenerationJob) -> None:
        write_json(self.job_file(job.job_id), job.to_dict())

    def load_job(self, job_id: str) -> GenerationJob | None:
        f = self.job_file(job_id)
        if not f.exists():
            return None
        return GenerationJob.from_dict(read_json(f))

    def iter_jobs(self) -> Iterable[GenerationJob]:
        if not self.paths.state_jobs_dir.exists():
            return
        for f in sorted(self.paths.state_jobs_dir.glob("*.json")):
            try:
                yield GenerationJob.from_dict(read_json(f))
            except Exception as e:
                _LOG.warning("skipping corrupt job file %s: %s", f, e)

    def jobs_for_shot(self, shot_id: str) -> list[GenerationJob]:
        out = []
        for job in self.iter_jobs():
            if job.shot_id == shot_id:
                out.append(job)
        return sorted(out, key=lambda j: j.attempt)

    def next_attempt_for_shot(self, shot_id: str) -> int:
        jobs = self.jobs_for_shot(shot_id)
        if not jobs:
            return 1
        return max(j.attempt for j in jobs) + 1

    def latest_job_for_shot(self, shot_id: str) -> GenerationJob | None:
        jobs = self.jobs_for_shot(shot_id)
        if not jobs:
            return None
        return jobs[-1]

    def has_successful_job(self, shot_id: str) -> bool:
        return any(j.status == JobStatus.COMPLETED for j in self.jobs_for_shot(shot_id))

    # ---- clip records ------------------------------------------------

    def clip_file(self, shot_id: str) -> Path:
        _validate_id(shot_id, "shot_id")
        return self.paths.state_clips_dir / f"{shot_id}.json"

    def save_clip(self, clip: VideoClip) -> None:
        write_json(self.clip_file(clip.shot_id), clip.to_dict())

    def load_clip(self, shot_id: str) -> VideoClip | None:
        f = self.clip_file(shot_id)
        if not f.exists():
            return None
        return VideoClip.from_dict(read_json(f))

    def iter_clips(self) -> Iterable[VideoClip]:
        if not self.paths.state_clips_dir.exists():
            return
        for f in sorted(self.paths.state_clips_dir.glob("*.json")):
            try:
                yield VideoClip.from_dict(read_json(f))
            except Exception as e:
                _LOG.warning("skipping corrupt clip file %s: %s", f, e)

    # ---- counters ----------------------------------------------------

    def recompute_counters(self, total_shots: int | None = None) -> GenerationRunState:
        """Recompute ``completed/failed/skipped`` counters from the on-disk
        jobs + clips. Idempotent — safe to call at the start of any run.

        A shot is COMPLETED iff it has at least one COMPLETED job (regardless
        of whether a clip record exists). The old logic also required a clip
        record, but if the runner crashed before writing the clip the count
        silently read as zero (observed 2026-10-09: 4 shots succeeded but
        ``completed_shots=0`` because the mp4 download step succeeded but the
        runner died before save_clip).
        """
        state = self.load_run_state()
        completed = 0
        failed = 0
        skipped = 0
        # Collect every unique shot_id seen in jobs
        all_shot_ids: set[str] = set()
        for job in self.iter_jobs():
            all_shot_ids.add(job.shot_id)
        shots_with_success: set[str] = {
            sid for sid in all_shot_ids if self.has_successful_job(sid)
        }
        shots_with_skip: set[str] = set()
        for job in self.iter_jobs():
            if job.status == JobStatus.SKIPPED:
                shots_with_skip.add(job.shot_id)
        # completed = shots with at least one COMPLETED job
        completed = len(shots_with_success)
        # skipped = shots with at least one SKIPPED job and no success
        skipped = len(shots_with_skip - shots_with_success)
        # failed = shots with at least one FAILED job and no success and not skipped
        failed = sum(
            1
            for sid in all_shot_ids
            if sid not in shots_with_success
            and sid not in shots_with_skip
            and any(j.status == JobStatus.FAILED for j in self.jobs_for_shot(sid))
        )
        state.completed_shots = completed
        state.failed_shots = failed
        state.skipped_shots = skipped
        if total_shots is not None:
            state.total_shots = total_shots
        self.save_run_state(state)
        return state

    # ---- eligibility for resume -------------------------------------

    def eligible_shot_ids(self, all_shot_ids: list[str], max_retries: int) -> list[str]:
        """Return the subset of ``all_shot_ids`` that still need work.

        A shot is skipped iff it already has at least one COMPLETED job
        (regardless of clip state — operator can rerun assembly separately
        if the clip file went missing). Otherwise it's eligible.

        Within eligible, shots whose failed-job count >= max_retries are
        filtered out (they need manual retry / intervention).
        """
        eligible: list[str] = []
        for shot_id in all_shot_ids:
            jobs = self.jobs_for_shot(shot_id)
            if any(j.status == JobStatus.COMPLETED for j in jobs):
                continue
            if any(j.status == JobStatus.SKIPPED for j in jobs):
                continue
            failed_count = sum(1 for j in jobs if j.status == JobStatus.FAILED)
            if failed_count >= max_retries:
                continue
            eligible.append(shot_id)
        return eligible

    # ---- bulk clear (used by ``retry --reset``) ---------------------

    def clear_jobs_for_shot(self, shot_id: str, project_id: str | None = None) -> int:
        """Delete every job file whose id encodes ``shot_id``.

        Job ids follow ``<project>__<shot>__a<NNN>__<uuid>``. With no
        ``project_id`` we conservatively scan all jobs whose id *contains*
        ``__<shot_id>__`` — slower but robust to caller mistakes. With a
        project_id we use a precise glob.
        """
        _validate_id(shot_id, "shot_id")
        removed = 0
        if project_id is not None:
            _validate_id(project_id, "project_id")
            for f in self.paths.state_jobs_dir.glob(f"{project_id}__{shot_id}__*.json"):
                f.unlink()
                removed += 1
        else:
            suffix = f"__{shot_id}__"
            for f in self.paths.state_jobs_dir.glob("*.json"):
                if suffix in f.name:
                    f.unlink()
                    removed += 1
        clip = self.clip_file(shot_id)
        if clip.exists():
            clip.unlink()
            removed += 1
        return removed

    def clear_all(self) -> int:
        """Wipe jobs/clips/qa. Returns the number of files removed."""
        removed = 0
        for d in (self.paths.state_jobs_dir, self.paths.state_clips_dir):
            for f in d.glob("*.json"):
                f.unlink()
                removed += 1
        return removed