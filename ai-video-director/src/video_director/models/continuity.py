"""Continuity state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .enums import ContinuityAspect


@dataclass
class ContinuityRule:
    """One rule to check between two shots / scenes."""

    aspect: ContinuityAspect
    expected: str  # e.g. "Alice must still wear the blue coat"
    severity: str = "high"  # low | medium | high — surfaces in QA notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect.value,
            "expected": self.expected,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContinuityRule":
        aspect_raw = data.get("aspect", "face")
        try:
            aspect = ContinuityAspect(aspect_raw)
        except ValueError:
            aspect = ContinuityAspect.FACE
        return cls(
            aspect=aspect,
            expected=str(data.get("expected", "")),
            severity=str(data.get("severity", "high")),
        )


@dataclass
class ContinuityState:
    """Per-character tracked continuity state at a given shot boundary."""

    character_id: str
    last_shot_id: str = ""
    last_outfit: str = ""
    last_location: str = ""
    last_hairstyle: str = ""
    last_props: list[str] = field(default_factory=list)
    last_lighting: str = ""
    last_seen_at: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "last_shot_id": self.last_shot_id,
            "last_outfit": self.last_outfit,
            "last_location": self.last_location,
            "last_hairstyle": self.last_hairstyle,
            "last_props": list(self.last_props),
            "last_lighting": self.last_lighting,
            "last_seen_at": self.last_seen_at,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContinuityState":
        return cls(
            character_id=str(data.get("character_id", "")),
            last_shot_id=str(data.get("last_shot_id", "")),
            last_outfit=str(data.get("last_outfit", "")),
            last_location=str(data.get("last_location", "")),
            last_hairstyle=str(data.get("last_hairstyle", "")),
            last_props=list(data.get("last_props", []) or []),
            last_lighting=str(data.get("last_lighting", "")),
            last_seen_at=str(data.get("last_seen_at", "")),
            notes=list(data.get("notes", []) or []),
        )