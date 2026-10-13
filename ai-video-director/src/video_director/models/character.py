"""Character bible models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra


# Reference-image types. The role field stays as a free-form sub-label
# (e.g. "expression_happy", "costume_winter_jacket"); image_type is the
# coarse bucket the adapter uses to route refs to the right ComfyUI input
# slot and to apply a sensible default weight.
#
# Added 2026-10-12 to support MiniMax-H3 MiniMaxH3ReferenceToVideo workflow,
# which accepts up to 9 reference images and uses <Picture i> ordinals in
# the prompt. The adapter maps image_type → ref_image_N slot; users
# normally don't need to think about slot indices at all.
class ReferenceImageType:
    """Reference image semantic type.

    Not an Enum because we want lenient parsing: legacy yaml files use
    free-form ``role: hero | face | costume_01 | expression_happy`` and
    we accept all of those as-is (mapping ``hero`` → ``HERO`` etc.) so
    old character cards keep working.
    """

    HERO = "hero"             # default; legacy "hero" role
    FACE = "face"             # tight face close-up — highest face-lock weight
    FULL = "full"             # full body / composition
    FRONT = "front"           # front view
    SIDE = "side"             # side profile
    BACK = "back"             # back view
    COSTUME = "costume"       # outfit / clothing detail
    EXPRESSION = "expression" # specific expression (role label says which)
    OTHER = "other"           # anything else (still gets routed, low weight)

    ALL = {HERO, FACE, FULL, FRONT, SIDE, BACK, COSTUME, EXPRESSION, OTHER}

    # Default weights the adapter applies when the user doesn't override
    # via shot.workflow_overrides. Tuned for MiniMax-H3 ref2v. Face gets
    # the biggest share because the user's main complaint is "characters
    # look different from their reference".
    DEFAULT_WEIGHTS: dict[str, float] = {
        FACE: 0.85,
        EXPRESSION: 0.7,
        FRONT: 0.65,
        HERO: 0.7,        # legacy "hero" reference
        FULL: 0.6,
        SIDE: 0.55,
        BACK: 0.5,
        COSTUME: 0.4,
        OTHER: 0.5,
    }

    @classmethod
    def normalise(cls, raw: str) -> str:
        """Map a free-form role string to a known type, defaulting to OTHER.

        Accepts the legacy ``role: hero`` field verbatim, plus common
        variants like ``costume_01``, ``expression_happy``,
        ``face_close_up``, ``side_view`` etc. by substring match.
        """
        s = (raw or "").strip().lower()
        if not s:
            return cls.OTHER
        if s in cls.ALL:
            return s
        # substring fallback
        for token in (
            "face", "head", "portrait", "closeup", "close-up",
        ):
            if token in s:
                return cls.FACE
        if "expression" in s or "emotion" in s:
            return cls.EXPRESSION
        for token in ("full", "body", "wide"):
            if token in s:
                return cls.FULL
        for token in ("front", "facing"):
            if token in s:
                return cls.FRONT
        for token in ("side", "profile"):
            if token in s:
                return cls.SIDE
        for token in ("back", "rear", "behind"):
            if token in s:
                return cls.BACK
        if "costume" in s or "outfit" in s or "cloth" in s:
            return cls.COSTUME
        return cls.OTHER


@dataclass
class CharacterReference:
    """One reference image for a character (path inside the project's references/).

    ``role`` is the legacy free-form sub-label (e.g. "expression_happy",
    "costume_winter_jacket"). ``image_type`` is the semantic bucket the
    adapter uses to route the ref to the right ComfyUI input slot. If
    ``image_type`` is empty the adapter derives it from ``role`` via
    ReferenceImageType.normalise, so old yaml files work without edits.
    """

    role: str  # hero | face | costume_01 | expression_happy | ...
    path: str  # relative to project references dir
    notes: str = ""
    image_type: str = ""  # ReferenceImageType.*; "" = derive from role
    weight: float | None = None  # None = use ReferenceImageType.DEFAULT_WEIGHTS[image_type]

    def resolved_type(self) -> str:
        if self.image_type:
            return self.image_type
        return ReferenceImageType.normalise(self.role)

    def resolved_weight(self) -> float:
        if self.weight is not None:
            return float(self.weight)
        return ReferenceImageType.DEFAULT_WEIGHTS.get(
            self.resolved_type(), 0.5
        )


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
                {
                    "role": r.role,
                    "path": r.path,
                    "notes": r.notes,
                    # Only emit the new fields when non-default, to keep
                    # round-tripped yaml diffs clean for legacy cards.
                    **({"image_type": r.image_type} if r.image_type else {}),
                    **({"weight": r.weight} if r.weight is not None else {}),
                }
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
                    image_type=str(raw.get("image_type", "") or ""),
                    weight=(float(raw["weight"]) if raw.get("weight") is not None else None),
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