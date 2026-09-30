"""Generation job, video clip, audio, final video, and assembly manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra
from .enums import JobStatus


@dataclass
class GenerationJob(TimestampedMixin):
    """One execution attempt of a shot by a backend (ComfyUI, mock, ...).

    A shot may have multiple jobs (initial + retries). Job state is the
    source of truth for resumability.
    """

    job_id: str = ""
    shot_id: str = ""
    scene_id: str = ""
    project_id: str = ""
    backend: str = ""  # "comfyui" | "mock" | future
    attempt: int = 1
    status: JobStatus = JobStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    error_class: str = ""
    error_message: str = ""
    seed_used: int | None = None
    prompt_used: str = ""
    output_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.job_id = validate_id(self.job_id, "job_id")
        self.shot_id = validate_id(self.shot_id, "shot_id")
        self.scene_id = validate_id(self.scene_id, "scene_id")
        self.project_id = validate_id(self.project_id, "project_id")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "job_id": self.job_id,
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "project_id": self.project_id,
            "backend": self.backend,
            "attempt": self.attempt,
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_class": self.error_class,
            "error_message": self.error_message,
            "seed_used": self.seed_used,
            "prompt_used": self.prompt_used,
            "output_path": self.output_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GenerationJob":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        status_raw = d.pop("status", "pending")
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        known.discard("status")
        kwargs = {k: v for k, v in d.items() if k in known}
        job = cls(**kwargs)
        try:
            job.status = JobStatus(status_raw)
        except ValueError:
            job.status = JobStatus.PENDING
        merge_extra(job.extra, extra)
        return job


@dataclass
class VideoClip:
    """A produced video clip ready for assembly."""

    shot_id: str
    path: str
    duration_sec: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    file_size_bytes: int = 0
    qa_passed: bool = False
    qa_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "path": self.path,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "file_size_bytes": self.file_size_bytes,
            "qa_passed": self.qa_passed,
            "qa_notes": list(self.qa_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VideoClip":
        return cls(
            shot_id=str(data.get("shot_id", "")),
            path=str(data.get("path", "")),
            duration_sec=float(data.get("duration_sec", 0.0) or 0.0),
            width=int(data.get("width", 0) or 0),
            height=int(data.get("height", 0) or 0),
            fps=float(data.get("fps", 0.0) or 0.0),
            file_size_bytes=int(data.get("file_size_bytes", 0) or 0),
            qa_passed=bool(data.get("qa_passed", False)),
            qa_notes=list(data.get("qa_notes", []) or []),
        )


@dataclass
class Audio:
    """Audio track (voice-over, BGM, SFX) that the assembler mixes in."""

    track_id: str
    kind: str  # voice | bgm | sfx
    path: str
    start_sec: float = 0.0
    duration_sec: float = 0.0
    gain_db: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "kind": self.kind,
            "path": self.path,
            "start_sec": self.start_sec,
            "duration_sec": self.duration_sec,
            "gain_db": self.gain_db,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Audio":
        return cls(
            track_id=str(data.get("track_id", "")),
            kind=str(data.get("kind", "voice")),
            path=str(data.get("path", "")),
            start_sec=float(data.get("start_sec", 0.0) or 0.0),
            duration_sec=float(data.get("duration_sec", 0.0) or 0.0),
            gain_db=float(data.get("gain_db", 0.0) or 0.0),
            notes=str(data.get("notes", "")),
        )


@dataclass
class FinalVideo:
    """Final assembled video."""

    path: str
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    file_size_bytes: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "file_size_bytes": self.file_size_bytes,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FinalVideo":
        return cls(
            path=str(data.get("path", "")),
            duration_sec=float(data.get("duration_sec", 0.0) or 0.0),
            width=int(data.get("width", 0) or 0),
            height=int(data.get("height", 0) or 0),
            fps=float(data.get("fps", 0.0) or 0.0),
            file_size_bytes=int(data.get("file_size_bytes", 0) or 0),
            notes=str(data.get("notes", "")),
        )


@dataclass
class AssemblyManifest:
    """Inputs + parameters for the assembly step."""

    project_id: str
    clips: list[VideoClip] = field(default_factory=list)
    audios: list[Audio] = field(default_factory=list)
    subtitles_path: str = ""
    transitions: list[dict[str, Any]] = field(default_factory=list)
    output_path: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "clips": [c.to_dict() for c in self.clips],
            "audios": [a.to_dict() for a in self.audios],
            "subtitles_path": self.subtitles_path,
            "transitions": list(self.transitions),
            "output_path": self.output_path,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssemblyManifest":
        return cls(
            project_id=str(data.get("project_id", "")),
            clips=[VideoClip.from_dict(c) for c in (data.get("clips", []) or [])],
            audios=[Audio.from_dict(a) for a in (data.get("audios", []) or [])],
            subtitles_path=str(data.get("subtitles_path", "")),
            transitions=list(data.get("transitions", []) or []),
            output_path=str(data.get("output_path", "")),
            notes=str(data.get("notes", "")),
        )