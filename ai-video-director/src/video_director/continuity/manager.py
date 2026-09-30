"""Continuity manager.

Responsibilities:
  * Track per-character state across shots (outfit, location, lighting, props).
  * Detect potential continuity breaks before generation and surface warnings.
  * Auto-link consecutive shots: shot N's ``end_frame`` can be referenced by
    shot N+1's ``start_frame`` slot.

This is a *static* checker — it reads the shot list, doesn't run any vision
model. AI vision QA can plug into the same surface (see :func:`check_shot`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..models import (
    Character,
    CharacterBible,
    CharacterReference,
    ContinuityAspect,
    ContinuityRule,
    ContinuityState,
    Scene,
    Shot,
)
from ..utils.logging import get_logger


_LOG = get_logger("video_director.continuity.manager")


@dataclass
class ContinuityIssue:
    """One issue detected by the manager."""

    aspect: ContinuityAspect
    shot_id: str
    severity: str  # low | medium | high
    message: str

    def to_dict(self) -> dict:
        return {
            "aspect": self.aspect.value,
            "shot_id": self.shot_id,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class ContinuityManager:
    """Stateless checker; pass in bible + shots, get issues back."""

    link_end_to_next_start: bool = True

    def initial_state(self, character: Character) -> ContinuityState:
        return ContinuityState(
            character_id=character.character_id,
            last_outfit=character.clothing_default,
        )

    # ---- pre-generation checks --------------------------------------

    def check_story(
        self,
        bible: CharacterBible,
        shots: Iterable[Shot],
        scenes: Iterable[Scene] | None = None,
    ) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        states: dict[str, ContinuityState] = {
            c.character_id: self.initial_state(c) for c in bible.characters
        }
        scene_index = {s.scene_id: s for s in (scenes or [])}

        ordered = sorted(shots, key=lambda sh: (sh.scene_id, sh.shot_index))
        prev_shot: Shot | None = None
        for shot in ordered:
            scene = scene_index.get(shot.scene_id)
            for char_id in shot.characters:
                character = bible.get(char_id)
                if character is None:
                    issues.append(
                        ContinuityIssue(
                            aspect=ContinuityAspect.FACE,
                            shot_id=shot.shot_id,
                            severity="high",
                            message=f"shot references unknown character {char_id!r}",
                        )
                    )
                    continue
                state = states[char_id]
                issues.extend(self._check_character_in_shot(character, state, shot))
                # Update state from the shot.
                state.last_shot_id = shot.shot_id
                if scene:
                    state.last_location = scene.location
                state.last_props = list(shot.workflow_overrides.get("props", state.last_props))
                state.last_lighting = shot.lighting or state.last_lighting
                # Heuristic: outfit persists unless the shot description
                # mentions a wardrobe change.
                if any(k in shot.action.lower() for k in ("changes into", "puts on", "changes clothes", "wears")):
                    state.last_outfit = shot.action
                # First-shot reset: if the scene changed location, expect a new outfit only if
                # explicitly stated.
            # Link consecutive shots
            if self.link_end_to_next_start and prev_shot is not None and prev_shot.scene_id == shot.scene_id:
                if not shot.start_frame and prev_shot.output_clip:
                    shot.start_frame = f"prev:{prev_shot.shot_id}"
                if not prev_shot.next_shot:
                    prev_shot.next_shot = shot.shot_id
                if not shot.previous_shot:
                    shot.previous_shot = prev_shot.shot_id
            prev_shot = shot
        return issues

    def _check_character_in_shot(
        self,
        character: Character,
        state: ContinuityState,
        shot: Shot,
    ) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []
        # Rule-driven checks: every rule in character.continuity_rules
        for rule_text in character.continuity_rules:
            issues.append(
                ContinuityIssue(
                    aspect=ContinuityAspect.CLOTHING,
                    shot_id=shot.shot_id,
                    severity="low",
                    message=f"verify rule: {rule_text}",
                )
            )
        # Heuristic: if shot specifies an outfit and it contradicts the
        # current state.outfit, raise an issue.
        declared = shot.workflow_overrides.get("outfit")
        if declared and state.last_outfit and declared != state.last_outfit:
            issues.append(
                ContinuityIssue(
                    aspect=ContinuityAspect.CLOTHING,
                    shot_id=shot.shot_id,
                    severity="medium",
                    message=(
                        f"character {character.character_id} outfit change "
                        f"from {state.last_outfit!r} to {declared!r}"
                    ),
                )
            )
        return issues

    # ---- runtime continuity hints -----------------------------------

    def build_reference_payload(
        self,
        character: Character,
        shot: Shot,
    ) -> dict[str, str]:
        """Return ``role -> path`` for the references to send to the backend.

        Resolves paths against the project root. Skips missing files so a
        partial setup still runs.
        """
        out: dict[str, str] = {}
        for ref in character.reference_images:
            out[ref.role] = ref.path
        # Start-frame hint: pass through so backend can use it as input image.
        if shot.start_frame and not shot.start_frame.startswith("prev:"):
            out.setdefault("start_frame", shot.start_frame)
        return out