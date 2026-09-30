"""Character bible models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra


@dataclass
class CharacterReference:
    """One reference image for a character (path inside the project's references/)."""

    role: str  # hero | face | costume_01 | expression_happy | ...
    path: str  # relative to project references dir
    notes: str = ""


@dataclass
class Character(TimestampedMixin):
    """Persistent character description used to enforce continuity across shots."""

    character_id: str = ""
    name: str = ""
    description: str = ""
    age: str = ""  # free-form so users can write "early 30s"
    gender: str = ""
    appearance: str = ""  # one-paragraph prose
    hair: str = ""
    face: str = ""
    body: str = ""
    clothing_default: str = ""
    clothing_variants: list[str] = field(default_factory=list)
    personality: str = ""
    reference_images: list[CharacterReference] = field(default_factory=list)
    continuity_rules: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.character_id = validate_id(self.character_id, "character_id")
        if not self.name:
            raise ValueError("character.name is required")
        if not self.appearance:
            raise ValueError("character.appearance is required (continuity needs prose)")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "character_id": self.character_id,
            "name": self.name,
            "description": self.description,
            "age": self.age,
            "gender": self.gender,
            "appearance": self.appearance,
            "hair": self.hair,
            "face": self.face,
            "body": self.body,
            "clothing_default": self.clothing_default,
            "clothing_variants": list(self.clothing_variants),
            "personality": self.personality,
            "reference_images": [
                {"role": r.role, "path": r.path, "notes": r.notes}
                for r in self.reference_images
            ],
            "continuity_rules": list(self.continuity_rules),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Character":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        refs_raw = d.pop("reference_images", []) or []
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        known.discard("reference_images")
        kwargs = {k: v for k, v in d.items() if k in known}
        ch = cls(**kwargs)
        for raw in refs_raw:
            ch.reference_images.append(
                CharacterReference(
                    role=str(raw.get("role", "hero")),
                    path=str(raw.get("path", "")),
                    notes=str(raw.get("notes", "")),
                )
            )
        merge_extra(ch.extra, extra)
        return ch


@dataclass
class CharacterBible:
    """Compiled view of all characters for a project."""

    characters: list[Character] = field(default_factory=list)

    def get(self, character_id: str) -> Character | None:
        for c in self.characters:
            if c.character_id == character_id:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"characters": [c.to_dict() for c in self.characters]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CharacterBible":
        raw = list(data.get("characters", []) or [])
        return cls(characters=[Character.from_dict(r) for r in raw])