"""Top-level :class:`Project` model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .base import TimestampedMixin, validate_id, merge_extra


@dataclass
class Project(TimestampedMixin):
    """A single story project.

    Each project lives in its own subdirectory under ``projects/<project_id>/``
    and is fully self-contained: story, characters, scenes, shots, references,
    output, and state. The framework never reads across projects.
    """

    project_id: str = ""
    title: str = ""
    description: str = ""
    language: str = "en"
    target_duration_sec: float = 0.0
    status: str = "draft"  # draft | ready | generating | assembled | archived
    story_path: str = "story.yaml"
    characters_dir: str = "characters"
    scenes_dir: str = "scenes"
    shots_dir: str = "shots"
    references_dir: str = "references"
    output_dir: str = "output"
    state_dir: str = "state"
    workflow_config: str = "workflow.yaml"  # inside project, NOT the public templates
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.project_id = validate_id(self.project_id, "project_id")
        if self.target_duration_sec < 0:
            raise ValueError("target_duration_sec must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "language": self.language,
            "target_duration_sec": self.target_duration_sec,
            "status": self.status,
            "story_path": self.story_path,
            "characters_dir": self.characters_dir,
            "scenes_dir": self.scenes_dir,
            "shots_dir": self.shots_dir,
            "references_dir": self.references_dir,
            "output_dir": self.output_dir,
            "state_dir": self.state_dir,
            "workflow_config": self.workflow_config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Project":
        d = dict(data)
        extra = d.pop("extra", None) or {}
        known = {f for f in cls.__dataclass_fields__}
        known.discard("extra")
        kwargs = {k: v for k, v in d.items() if k in known}
        project = cls(**kwargs)
        merge_extra(project.extra, extra)
        return project