"""Scene + shot breakdown.

These planners convert a :class:`StoryBible` plus optional user-supplied
overrides into :class:`Scene` / :class:`Shot` objects that get persisted
into the project. Generation never re-reads the script; it reads the
intermediate plans, so a crash mid-generation can resume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from ..models import (
    Scene,
    Shot,
    StoryBible,
    Story,
    ShotStatus,
)
from ..utils.logging import get_logger


_LOG = get_logger("video_director.story.planner")


@dataclass
class ScenePlan:
    """Intermediate plan: a scene plus its shot list (still as raw dicts)."""

    scene: Scene
    shots: list[dict] = field(default_factory=list)


@dataclass
class ShotPlan:
    """One planned shot. Rendered to a :class:`Shot` by ``to_shot``."""

    scene_id: str
    shot_index: int
    duration_sec: float = 5.0
    shot_type: str = "medium"
    camera: str = ""
    camera_motion: str = "static"
    characters: list[str] = field(default_factory=list)
    action: str = ""
    emotion: str = ""
    environment: str = ""
    lighting: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None

    def to_shot(self, shot_id: str | None = None) -> Shot:
        sid = shot_id or f"{self.scene_id}_shot_{self.shot_index:03d}"
        return Shot(
            shot_id=sid,
            scene_id=self.scene_id,
            shot_index=self.shot_index,
            duration_sec=self.duration_sec,
            shot_type=self.shot_type,
            camera=self.camera,
            camera_motion=self.camera_motion,
            characters=list(self.characters),
            action=self.action,
            emotion=self.emotion,
            environment=self.environment,
            lighting=self.lighting,
            prompt=self.prompt,
            negative_prompt=self.negative_prompt,
            seed=self.seed,
            status=ShotStatus.PENDING,
        )


@dataclass
class ScenePlanner:
    """Build :class:`Scene` objects from a story bible.

    Strategy: one scene per script section. If the script has no sections
    but has body text, fall back to a single scene. Either way, scenes are
    *plans* — the user can edit the YAML before generating.
    """

    default_scene_duration_sec: float = 60.0
    default_location: str = "unspecified"

    def plan(self, story: Story, bible: StoryBible) -> list[Scene]:
        if not story.script:
            return []
        scenes: list[Scene] = []
        for idx, section in enumerate(story.script, start=1):
            scene_id = self._safe_id(f"scene_{idx:03d}", section.title, idx)
            location = section.location or self._pick_location(bible, idx)
            characters = list(section.characters) or self._pick_characters(bible, section.body)
            scene = Scene(
                scene_id=scene_id,
                title=section.title or f"Scene {idx}",
                location=location,
                time="",
                characters=characters,
                description=section.summary or section.body[:300],
                duration_sec=self.default_scene_duration_sec,
                style=story.style,
                continuity_requirements=[],
            )
            scenes.append(scene)
        return scenes

    def _pick_location(self, bible: StoryBible, idx: int) -> str:
        if not bible.locations:
            return self.default_location
        return bible.locations[(idx - 1) % len(bible.locations)]

    def _pick_characters(self, bible: StoryBible, body: str) -> list[str]:
        # First two declared characters — coarse, deterministic.
        return list(bible.characters[:2])

    def _safe_id(self, base: str, title: str, idx: int) -> str:
        # Always use the positional id so we never depend on user text.
        return base


@dataclass
class ShotPlanner:
    """Expand each :class:`Scene` into one or more :class:`ShotPlan` entries.

    Heuristic split: a scene of ``duration_sec`` seconds with shots of
    ``default_shot_duration_sec`` (default 5s) yields roughly N shots, with
    varying shot types to give the editor room to breathe.
    """

    default_shot_duration_sec: float = 5.0
    min_shots_per_scene: int = 2
    max_shots_per_scene: int = 8

    shot_type_pattern: tuple[str, ...] = (
        "wide",
        "medium",
        "close_up",
        "medium",
        "close_up",
        "over_shoulder",
        "wide",
        "insert",
    )

    def plan_scene(self, scene: Scene) -> list[ShotPlan]:
        # Number of shots needed to fill duration with default shot length.
        target = max(
            self.min_shots_per_scene,
            min(
                self.max_shots_per_scene,
                round(scene.duration_sec / self.default_shot_duration_sec),
            ),
        )
        plans: list[ShotPlan] = []
        for i in range(target):
            shot_type = self.shot_type_pattern[i % len(self.shot_type_pattern)]
            plans.append(
                ShotPlan(
                    scene_id=scene.scene_id,
                    shot_index=i + 1,
                    duration_sec=self.default_shot_duration_sec,
                    shot_type=shot_type,
                    camera=self._camera_for(shot_type),
                    camera_motion=self._motion_for(i, target),
                    characters=list(scene.characters),
                    action=scene.description,
                    emotion="",
                    environment=f"{scene.location} ({scene.time})".strip(),
                    lighting="",
                    prompt=self._build_prompt(scene, shot_type, i, target),
                    negative_prompt=self._build_negative_prompt(scene),
                )
            )
        return plans

    def plan_story(
        self,
        scenes: Iterable[Scene],
    ) -> list[ShotPlan]:
        plans: list[ShotPlan] = []
        for sc in scenes:
            plans.extend(self.plan_scene(sc))
        return plans

    def _camera_for(self, shot_type: str) -> str:
        return {
            "wide": "35mm wide",
            "medium": "50mm eye-level",
            "close_up": "85mm close",
            "extreme_close_up": "85mm macro",
            "over_shoulder": "50mm over-the-shoulder",
            "insert": "100mm insert",
        }.get(shot_type, "50mm")

    def _motion_for(self, idx: int, total: int) -> str:
        if idx == 0:
            return "slow_dolly_in"
        if idx == total - 1:
            return "slow_dolly_out"
        if idx % 3 == 1:
            return "pan"
        return "static"

    def _build_prompt(self, scene: Scene, shot_type: str, idx: int, total: int) -> str:
        parts = [
            f"Shot type: {shot_type}.",
            f"Location: {scene.location}.",
            f"Time: {scene.time or 'unspecified'}.",
        ]
        if scene.description:
            parts.append(f"Action: {scene.description}")
        if scene.characters:
            parts.append("Characters: " + ", ".join(scene.characters))
        return " ".join(p for p in parts if p)

    def _build_negative_prompt(self, scene: Scene) -> str:
        return "blurry, distorted, deformed, low quality, watermark, text"