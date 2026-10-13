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
        # Skip template/example shots — they are scaffolding, not real content.
        # Keeping the rule in the runner (not just assemble) means generate
        # never wastes GPU cycles on quick-check shots either.
        all_shots = [s for s in all_shots if not s.shot_id.startswith("example_")]
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
        # NEW (2026-10-12, ref2v): ordered list of reference images fed to
        # the workflow's reference_image_nodes slots. Returns [] when the
        # workflow has no reference_image_nodes declared (legacy single-
        # image mode) — the adapter treats an empty list as a no-op.
        ordered_refs = self._build_ordered_reference_images(shot, bible, references)
        # NEW (2026-10-12, prev-shot chain): ordered list of reference
        # videos (today: just the previous shot's mp4) routed to the
        # workflow's reference_video_nodes slots. When the workflow
        # exposes ref_video_0 and shot.start_frame_source==previous_shot
        # + a previous mp4 exists, this gives the unet a motion-primed
        # anchor for visual continuity.
        ordered_videos = self._build_ordered_reference_videos(shot)

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
                    reference_images_ordered=ordered_refs,
                    reference_videos_ordered=ordered_videos,
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
                # VRAM hygiene: on the retry path (attempt > 1 has
                # now become attempt > 1 effective after the +=1
                # above), free ComfyUI's GPU model state so the
                # next try starts from a clean baseline. The cost
                # is 30-90s of model reload + warm-up, which is
                # cheap relative to a hung render and worth paying
                # only when we know something went wrong. Mock
                # backends don't expose free_vram — skip silently.
                free = getattr(self.backend, "free_vram", None)
                if callable(free):
                    ok = free()
                    _LOG.info(
                        "shot %s attempt %d → %d: freed ComfyUI VRAM (ok=%s)",
                        shot.shot_id, attempt - 1, attempt, ok,
                    )
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
        """Build the references dict that the adapter passes to the workflow.

        Returns a ``role -> filename`` map suitable for ComfyUI's LoadImage
        node. Two important rules:

        * Reference paths are project-relative (``imports/references/...``)
          and must be resolved against ``paths.root`` (NOT against ``cwd``),
          so a project in ``projects/foo/`` finds ``imports/references/...``
          under ``projects/foo/`` rather than at the framework root.
        * All reference files are uploaded to ComfyUI's input dir via
          ``/upload/image`` before being referenced. ComfyUI's LoadImage
          resolves filenames against its input DB, not the filesystem —
          without an upload, the file on disk is invisible to the
          workflow and the prompt fails with
          ``Invalid image file: <name>``.
        * The shot's ``start_frame`` and ``start_frame_source: previous_shot``
          are also normalized to a single filename here, in priority order:
          previous_shot (uploaded) > manual shot.start_frame (uploaded) >
          character hero reference (uploaded).
        """
        refs: dict[str, str] = {}
        project_root = self.paths.root
        for char_id in shot.characters:
            ch = bible.get(char_id)
            if not ch:
                continue
            for ref in ch.reference_images:
                # Resolve the source file (project-relative path).
                p = Path(ref.path)
                if p.is_absolute() or p.exists():
                    src = p
                else:
                    src = project_root / ref.path
                if not src.exists():
                    _LOG.warning(
                        "character %s reference %s not found at %s; skipping",
                        char_id, ref.path, src,
                    )
                    continue
                # Upload to ComfyUI's input dir so LoadImage can resolve it
                # by basename. Use allow_rename=True so multiple heroes that
                # share the same basename (e.g. hero.jpg) don't overwrite
                # each other in the input dir.
                uploaded = self._upload_to_comfyui(src, allow_rename=True)
                if uploaded:
                    refs[ref.role] = uploaded
                else:
                    # Last-ditch: return basename; ComfyUI may see the file
                    # via shared filesystem mount.
                    refs[ref.role] = src.name
        if shot.start_frame_source == "previous_shot":
            extracted = self._extract_previous_shot_frame(shot)
            if extracted:
                refs["start_frame"] = extracted
            else:
                _LOG.warning(
                    "shot %s start_frame_source=previous_shot but no previous shot mp4 found; "
                    "falling back to character hero reference",
                    shot.shot_id,
                )
                # Fall back to the first character hero reference. The
                # character refs have already been uploaded above under
                # their role keys; copy one of them into refs["start_frame"]
                # so the workflow has something to anchor the first frame.
                # Prefer shot.start_frame path if it's set, otherwise the
                # first character hero.
                if shot.start_frame:
                    uploaded = self._upload_reference_file(shot.start_frame)
                    if uploaded:
                        refs["start_frame"] = uploaded
                    else:
                        refs["start_frame"] = self._resolve_to_filename(shot.start_frame)
                else:
                    for char_id in shot.characters:
                        ch = bible.get(char_id)
                        if ch and ch.reference_images:
                            hero_ref = next(
                                (refs[r] for r in refs if r in {ref.role for ref in ch.reference_images}),
                                None,
                            )
                            if hero_ref:
                                refs.setdefault("start_frame", hero_ref)
                                break
        elif shot.start_frame and not shot.start_frame.startswith("prev:"):
            uploaded = self._upload_reference_file(shot.start_frame)
            if uploaded:
                refs.setdefault("start_frame", uploaded)
            else:
                refs.setdefault("start_frame", self._resolve_to_filename(shot.start_frame))
        else:
            # No explicit start_frame. Fall back to the first character
            # hero reference so the workflow has at least one image to
            # anchor the first frame. Required when the workflow JSON's
            # LoadImage node title is wired to start_frame_role (e.g.
            # ``start_frame: "Load Image"``) — without this fallback the
            # adapter leaves the original ``image: 'science2.jpeg'`` (or
            # whatever the workflow shipped with) and ComfyUI fails with
            # ``Invalid image file: <name>`` because no upload happens
            # for that default name.
            for char_id in shot.characters:
                ch = bible.get(char_id)
                if ch and ch.reference_images:
                    # Use the first hero reference; it's already uploaded
                    # in the loop above, so refs already has it under its
                    # role key. Copy it under "start_frame" too.
                    hero_ref = next(
                        (refs[r] for r in refs if r in {ref.role for ref in ch.reference_images}),
                        None,
                    )
                    if hero_ref:
                        refs.setdefault("start_frame", hero_ref)
                        break
        return refs

    def _build_ordered_reference_images(
        self,
        shot: Shot,
        bible: CharacterBible,
        references: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Build an ordered list of reference images for the ref2v workflow.

        Returns a list of dicts, one per reference image, in the order the
        adapter should route them into the workflow's ``ref_image_N`` slots
        (face gets slot 0, then full / front / hero, then the rest).

        Each entry: ``{"basename": str, "image_type": str, "weight": float,
        "character_id": str, "role": str}``.

        Slot ordering rationale (so the most identity-anchoring refs get
        the lowest ordinals that the workflow reserves for the strongest
        signals):

          1. FACE / EXPRESSION (closest-up face cues) — slots 0, 1
          2. FRONT / HERO / FULL (full-body / default) — slot 2
          3. SIDE / BACK / COSTUME / OTHER — slots 3..8

        The list is empty when the workflow has no
        ``reference_image_nodes`` declared (legacy single-image mode).
        That's not a bug — the adapter treats [] as a no-op and falls back
        to the ``start_frame`` path.

        Returns ``[]`` if the workflow has no reference_image_nodes. This
        is determined by checking the workflow_mapping. We look at the
        adapter request from the resolver later; for now we always build
        the list (cheap) and let the adapter skip if no slots are mapped.
        """
        # Only build the list if the workflow mapping asks for it.
        # The check is on the mapping object held on the runner. We avoid
        # circular imports by reading the attribute defensively.
        mapping = getattr(self, "workflow_mapping", None)
        if mapping is None or not getattr(mapping, "reference_image_nodes", None):
            return []

        # Priority queue: lower = earlier slot.
        type_priority = {
            "face": 0,
            "expression": 1,
            "front": 2,
            "hero": 2,
            "full": 3,
            "side": 4,
            "back": 5,
            "costume": 6,
            "other": 7,
        }
        # Collect (priority, role, basename, image_type, weight, char_id)
        # for every reference the shot's characters declare.
        items: list[tuple[int, str, str, str, float, str]] = []
        for char_id in shot.characters:
            ch = bible.get(char_id)
            if not ch:
                continue
            for ref in ch.reference_images:
                basename = references.get(ref.role)
                if not basename:
                    # Not uploaded (file missing) — skip silently. _build_references
                    # already logged a warning.
                    continue
                rtype = ref.resolved_type()
                items.append((
                    type_priority.get(rtype, 99),
                    ref.role,  # tie-breaker: stable order
                    basename,
                    rtype,
                    ref.resolved_weight(),
                    char_id,
                ))
        items.sort(key=lambda x: (x[0], x[1]))
        return [
            {
                "basename": basename,
                "image_type": rtype,
                "weight": weight,
                "character_id": char_id,
                "role": role,
            }
            for _, role, basename, rtype, weight, char_id in items
        ]

    def _build_ordered_reference_videos(self, shot: Shot) -> list[dict[str, Any]]:
        """Build the ordered list of reference VIDEOS for the ref2v workflow.

        NEW (2026-10-12, prev-shot chain): for each ``ref_video_<i>`` slot
        the workflow declares, the runner can attach a video file. Today
        the only supported source is the *previous shot's mp4*, which
        gives the unet a motion-primed anchor at the start of the new
        shot and produces visually continuous video. Returns [] when the
        workflow has no reference_video_nodes declared, or when this
        shot has no usable previous-shot mp4.

        Slot 0 is reserved for the previous shot when applicable. Future
        slots could carry earlier shots (shot-2, shot-3, ...) but the
        H3 node caps ref_videos at 3 and the relevant continuity window
        is just one step.
        """
        # Only build the list if the workflow mapping asks for it.
        mapping = getattr(self, "workflow_mapping", None)
        if mapping is None or not getattr(mapping, "reference_video_nodes", None):
            return []

        out: list[dict[str, Any]] = []
        # slot 0: previous shot's mp4 (when available and requested)
        if shot.start_frame_source == "previous_shot" and shot.previous_shot:
            prev_clip = self.paths.output_clips_dir / f"{shot.previous_shot}.mp4"
            if not prev_clip.exists():
                _LOG.warning(
                    "shot %s wants previous_shot=%s but mp4 missing at %s; "
                    "ref_video_0 will be left empty",
                    shot.shot_id, shot.previous_shot, prev_clip,
                )
            else:
                # Re-use the extracted end-frame PNG (already in ComfyUI
                # input dir if _extract_previous_shot_frame ran) when
                # the previous shot is short; for full video continuity
                # we instead upload the *whole* mp4 and let ComfyUI
                # LoadImage decode all frames. The mp4 is cheaper to keep
                # than a per-frame PNG sequence.
                basename = self._upload_video_to_comfyui(prev_clip)
                if basename:
                    out.append({
                        "basename": basename,
                        "role": "previous_shot",
                        "shot_id": shot.previous_shot,
                        "video_type": "mp4",
                    })
        return out

    def _upload_video_to_comfyui(self, src: Path) -> str | None:
        """Upload a video file (mp4) to ComfyUI's input directory.

        ComfyUI's ``/upload/image`` endpoint accepts any bytes; the file
        lands in the input dir and ``LoadImage`` will load it via
        ``InputImpl.VideoFromFile`` (pyav), returning an IMAGE batch
        representing the full 24 fps sequence. ``allow_rename`` keeps
        prev-shot uploads from clobbering each other when two adjacent
        shots share the same name (which is impossible by construction
        here, but defensive).
        """
        import hashlib
        import requests
        if not src.exists():
            return None
        stem = src.stem
        suffix = src.suffix or ".mp4"
        digest = hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:8]
        target_name = f"{stem}__{digest}{suffix}"
        try:
            # video/mp4 is the closest MIME type; ComfyUI doesn't care
            # about the exact value, only the bytes.
            with open(src, "rb") as f:
                resp = requests.post(
                    "http://127.0.0.1:8188/upload/image",
                    files={"image": (target_name, f, "video/mp4")},
                    data={"type": "input", "overwrite": "true"},
                    timeout=120,
                )
            resp.raise_for_status()
            try:
                body = resp.json()
                return body.get("name", target_name)
            except Exception:
                return target_name
        except Exception as e:  # noqa: BLE001
            _LOG.warning("ComfyUI video upload failed for %s: %s", src, e)
            return None

    def _upload_reference_file(self, path: str) -> str | None:
        """Resolve a project-relative path to a real file and upload it.

        Returns the basename ComfyUI should use, or None if the file is
        missing or upload failed. Used for character references and
        manual start_frame paths so they all reach ComfyUI's input dir.
        """
        p = Path(path)
        if p.is_absolute() or p.exists():
            src = p
        else:
            src = self.paths.root / path
        if not src.exists():
            _LOG.warning("reference file %s does not exist; cannot upload", src)
            return None
        return self._upload_to_comfyui(src)

    def _upload_to_comfyui(self, src: Path, *, allow_rename: bool = False) -> str | None:
        """Upload a file to ComfyUI's input directory via /upload/image.

        Returns the basename ComfyUI should reference, or None on failure.
        overwrite=true so re-runs replace stale copies.

        ``allow_rename``: when True (default for character refs to avoid
        filename collisions on ComfyUI's input dir when multiple heroes
        share the same basename, e.g. hero.jpg/hero.png), the upload
        name is suffixed with an 8-char hex hash of the source path so
        each upload is unique. When False (start_frame paths that the
        workflow JSON hard-codes by name), the source basename is used
        verbatim and may overwrite prior uploads.
        """
        import hashlib
        if allow_rename:
            stem = src.stem
            suffix = src.suffix or ".png"
            digest = hashlib.sha1(str(src.resolve()).encode()).hexdigest()[:8]
            target_name = f"{stem}__{digest}{suffix}"
        else:
            target_name = src.name
        try:
            import requests
            content_type = "image/jpeg" if src.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            with open(src, "rb") as f:
                resp = requests.post(
                    "http://127.0.0.1:8188/upload/image",
                    files={"image": (target_name, f, content_type)},
                    data={"type": "input", "overwrite": "true"},
                    timeout=30,
                )
            resp.raise_for_status()
            try:
                body = resp.json()
                return body.get("name", target_name)
            except Exception:
                return target_name
        except Exception as e:  # noqa: BLE001
            _LOG.warning("ComfyUI upload failed for %s: %s", src, e)
            return None

    def _resolve_to_filename(self, path: str) -> str:
        """Turn a project-relative path like ``imports/references/1/hero.jpg``
        into a ComfyUI-input filename. If the file exists at the project
        root (which is the typical case), returns the basename. Otherwise
        returns the path unchanged (the caller will warn)."""
        p = Path(path)
        if p.is_absolute():
            return p.name
        resolved = self.paths.root / path
        if resolved.exists():
            return resolved.name
        return path

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
        # The extracted PNG is now on disk in ComfyUI's input dir, but
        # LoadImage only sees files ComfyUI knows about via its image DB.
        # Upload via /upload/image so the workflow can reference it by filename.
        try:
            import requests
            with open(out_png, "rb") as f:
                resp = requests.post(
                    "http://127.0.0.1:8188/upload/image",
                    files={"image": (out_png.name, f, "image/png")},
                    data={"type": "input", "overwrite": "true"},
                    timeout=30,
                )
            resp.raise_for_status()
            uploaded_name = out_png.name
            try:
                body = resp.json()
                uploaded_name = body.get("name", out_png.name)
            except Exception:
                pass
            _LOG.info("uploaded start_frame %s -> ComfyUI input", uploaded_name)
            return uploaded_name
        except Exception as e:
            _LOG.warning("ComfyUI upload failed for %s: %s — returning local path", out_png, e)
            # Fallback: return just the filename; ComfyUI may already see it
            # from the filesystem if its input dir is the same path.
            return out_png.name

    def _mark_shot_status(self, shot: Shot, status: ShotStatus, output_clip: str = "") -> None:
        shot.status = status
        if output_clip:
            shot.output_clip = output_clip
        shot.touch()
        try:
            self.pm.save_shot(self.paths, shot)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("failed to update shot %s status: %s", shot.shot_id, e)