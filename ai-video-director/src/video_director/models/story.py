"""Story bible model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, merge_extra


@dataclass
class ScriptSection:
    """One chunk of the screenplay / script."""

    section_id: str
    title: str = ""
    summary: str = ""
    body: str = ""
    characters: list[str] = field(default_factory=list)
    location: str = ""
    notes: str = ""


@dataclass
class Story(TimestampedMixin):
    """High-level narrative metadata plus the script itself."""

    story_id: str = ""
    title: str = ""
    story_summary: str = ""
    genre: str = ""
    style: str = ""
    tone: str = ""
    target_duration_sec: float = 0.0
    language: str = "en"
    script: list[ScriptSection] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target_duration_sec < 0:
            raise ValueError("target_duration_sec must be >= 0")

    @property
    def full_text(self) -> str:
        """Return the concatenated script body as a single string.

        Useful for analysis passes that don't care about section boundaries.
        """
        return "\n\n".join(s.body for s in self.script if s.body)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "story_id": self.story_id,
            "title": self.title,
            "story_summary": self.story_summary,
            "genre": self.genre,
            "style": self.style,
            "tone": self.tone,
            "target_duration_sec": self.target_duration_sec,
            "language": self.language,
            "script": [
                {
                    "section_id": s.section_id,
                    "title": s.title,
                    "summary": s.summary,
                    "body": s.body,
                    "characters": list(s.characters),
                    "location": s.location,
                    "notes": s.notes,
                }
                for s in self.script
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Story":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        script_raw = d.pop("script", []) or []
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        known.discard("script")
        kwargs = {k: v for k, v in d.items() if k in known}
        story = cls(**kwargs)
        for raw in script_raw:
            story.script.append(
                ScriptSection(
                    section_id=str(raw.get("section_id", "")),
                    title=str(raw.get("title", "")),
                    summary=str(raw.get("summary", "")),
                    body=str(raw.get("body", "")),
                    characters=list(raw.get("characters", []) or []),
                    location=str(raw.get("location", "")),
                    notes=str(raw.get("notes", "")),
                )
            )
        merge_extra(story.extra, extra)
        return story


@dataclass
class StoryBible:
    """In-memory compiled view of the story used by the director.

    Built by :class:`StoryAnalyzer` from a :class:`Story` plus optional notes.
    """

    title: str = ""
    logline: str = ""
    acts: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    beats: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "logline": self.logline,
            "acts": list(self.acts),
            "themes": list(self.themes),
            "beats": list(self.beats),
            "characters": list(self.characters),
            "locations": list(self.locations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StoryBible":
        return cls(
            title=str(data.get("title", "")),
            logline=str(data.get("logline", "")),
            acts=list(data.get("acts", []) or []),
            themes=list(data.get("themes", []) or []),
            beats=list(data.get("beats", []) or []),
            characters=list(data.get("characters", []) or []),
            locations=list(data.get("locations", []) or []),
        )