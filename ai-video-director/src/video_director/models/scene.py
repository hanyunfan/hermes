"""Scene model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra


@dataclass
class Scene(TimestampedMixin):
    """A scene is one location + time + cast + action unit."""

    scene_id: str = ""
    title: str = ""
    location: str = ""
    time: str = ""  # free-form: "dawn", "night", "interior", "exterior"
    characters: list[str] = field(default_factory=list)
    description: str = ""
    duration_sec: float = 0.0
    style: str = ""
    continuity_requirements: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scene_id = validate_id(self.scene_id, "scene_id")
        if self.duration_sec < 0:
            raise ValueError("scene.duration_sec must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "scene_id": self.scene_id,
            "title": self.title,
            "location": self.location,
            "time": self.time,
            "characters": list(self.characters),
            "description": self.description,
            "duration_sec": self.duration_sec,
            "style": self.style,
            "continuity_requirements": list(self.continuity_requirements),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scene":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        kwargs = {k: v for k, v in d.items() if k in known}
        sc = cls(**kwargs)
        merge_extra(sc.extra, extra)
        return sc