"""Shot model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra
from .enums import ShotStatus


@dataclass
class Shot(TimestampedMixin):
    """A single camera-shot to be generated as one video clip."""

    shot_id: str = ""
    scene_id: str = ""
    shot_index: int = 0  # order within the scene
    duration_sec: float = 5.0
    shot_type: str = "medium"  # wide | medium | close_up | extreme_close_up | over_shoulder | insert
    camera: str = ""  # free-form: "35mm", "eye-level", etc.
    camera_motion: str = "static"  # static | pan | tilt | dolly | handheld | crane
    characters: list[str] = field(default_factory=list)
    action: str = ""
    emotion: str = ""
    environment: str = ""
    lighting: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    start_frame: str = ""  # path inside references/
    start_frame_source: str = "manual"  # manual | previous_shot
    end_frame: str = ""
    previous_shot: str = ""
    next_shot: str = ""
    reference_images: list[str] = field(default_factory=list)
    workflow_overrides: dict[str, Any] = field(default_factory=dict)
    status: ShotStatus = ShotStatus.PENDING
    output_clip: str = ""  # relative path once generated
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.shot_id = validate_id(self.shot_id, "shot_id")
        self.scene_id = validate_id(self.scene_id, "scene_id")
        if self.duration_sec <= 0:
            raise ValueError("shot.duration_sec must be > 0")
        if not self.prompt and not self.action:
            raise ValueError("shot requires either prompt or action")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "shot_id": self.shot_id,
            "scene_id": self.scene_id,
            "shot_index": self.shot_index,
            "duration_sec": self.duration_sec,
            "shot_type": self.shot_type,
            "camera": self.camera,
            "camera_motion": self.camera_motion,
            "characters": list(self.characters),
            "action": self.action,
            "emotion": self.emotion,
            "environment": self.environment,
            "lighting": self.lighting,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "seed": self.seed,
            "start_frame": self.start_frame,
            "start_frame_source": self.start_frame_source,
            "end_frame": self.end_frame,
            "previous_shot": self.previous_shot,
            "next_shot": self.next_shot,
            "reference_images": list(self.reference_images),
            "workflow_overrides": dict(self.workflow_overrides),
            "status": self.status.value if isinstance(self.status, ShotStatus) else str(self.status),
            "output_clip": self.output_clip,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Shot":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        status_raw = d.pop("status", "pending")
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        known.discard("status")
        kwargs = {k: v for k, v in d.items() if k in known}
        shot = cls(**kwargs)
        try:
            shot.status = ShotStatus(status_raw)
        except ValueError:
            shot.status = ShotStatus.PENDING
        merge_extra(shot.extra, extra)
        return shot