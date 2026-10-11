"""Build framework yaml files from a validated :class:`Imports` bundle.

Generates:

  * ``projects/<id>/story.yaml``            — from story.json
  * ``projects/<id>/characters/<id>.yaml``  — from characters.json
  * ``projects/<id>/scenes/<id>.yaml``      — from scenes.json
  * ``projects/<id>/shots/<id>.yaml``       — from shots.json (with
    dialogue lines embedded as shot.extra.dialogues if any)

This function ASSUMES the bundle has been :func:`check_imports`ed and
passed. It will not re-check; build will happily write garbage if you
hand it garbage. Always validate first.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .loader import Imports

from ..utils.io import write_yaml


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _build_story_yaml(bundle: Imports) -> dict[str, Any]:
    story = bundle.story
    assert story is not None  # caller guarantees via loader
    # Map to the existing Story model + script structure.
    # The yaml layout mirrors story.yaml from the framework's existing
    # projects/template/, so future `analyze`/`validate` work unchanged.
    return {
        "story_id": story.story_id,
        "title": story.title,
        "story_summary": story.extra.get("story_summary", story.style),
        "genre": story.genre,
        "tone": story.tone,
        "language": story.language,
        "style": story.style,
        "target_duration_sec": story.target_duration_sec,
        "characters": list(story.character_ids),
        "scenes": [
            {"scene_id": sid, "title": ""} for sid in story.scene_ids
        ],
        "script": [],
    }


def _build_character_yaml(ch) -> dict[str, Any]:
    # Combine description + clothing_default so existing Character model
    # is satisfied.
    description_parts = []
    if ch.age:
        description_parts.append(f"{ch.age}岁")
    if ch.gender:
        description_parts.append(ch.gender)
    if ch.clothing_default:
        description_parts.append(f"服装:{ch.clothing_default}")
    if ch.personality:
        description_parts.append(f"性格:{ch.personality}")
    desc = " ".join(description_parts)
    return {
        "character_id": ch.character_id,
        "name": ch.name,
        "description": desc or ch.personality,
        "age": str(ch.age) if ch.age else "",
        "gender": ch.gender,
        "appearance": ch.appearance,
        "clothing_default": ch.clothing_default,
        "personality": ch.personality,
        "reference_images": (
            [{"role": "hero", "path": ch.reference_image}]
            if ch.reference_image else []
        ),
    }


def _build_scene_yaml(sc) -> dict[str, Any]:
    return {
        "scene_id": sc.scene_id,
        "title": sc.title,
        "location": sc.location,
        "time": sc.time_of_day,
        "weather": sc.weather,
        "description": sc.environment,
        "duration_sec": sc.duration_sec,
        "style": sc.lighting,  # light info is closest match for existing "style" field
        "characters": list(sc.character_ids),
        "continuity_requirements": [],
    }


def _build_shot_yaml(sh) -> dict[str, Any]:
    # start_frame_source must live at top-level so Shot.from_dict picks it up
    # (it gets ignored if buried under extra:).
    return {
        "shot_id": sh.shot_id,
        "scene_id": sh.scene_id,
        "shot_index": sh.shot_index,
        "duration_sec": sh.duration_sec,
        "shot_type": sh.shot_type,
        "camera": sh.camera,
        "camera_motion": sh.camera_motion,
        "characters": list(sh.character_ids),
        "action": sh.action,
        "emotion": sh.emotion,
        "environment": sh.environment,
        "lighting": sh.lighting,
        "prompt": sh.prompt,
        "negative_prompt": sh.negative_prompt,
        "start_frame": sh.start_frame,
        "start_frame_source": sh.start_frame_source,
        "previous_shot": sh.previous_shot,
        "next_shot": sh.next_shot,
        "extra": {},
    }


def build_yaml_from_imports(bundle: Imports) -> dict[str, list[Path]]:
    """Write all yaml files. Returns a map of category → list of paths written.

    The bundle must have been :func:`check_imports`ed successfully.
    """
    project = bundle.project_dir

    written: dict[str, list[Path]] = {
        "story": [], "characters": [], "scenes": [], "shots": [],
    }

    if bundle.story is not None:
        story_path = project / "story.yaml"
        write_yaml(story_path, _build_story_yaml(bundle))
        written["story"].append(story_path)

    chars_dir = _ensure_dir(project / "characters")
    for ch in bundle.characters:
        p = chars_dir / f"{ch.character_id}.yaml"
        write_yaml(p, _build_character_yaml(ch))
        written["characters"].append(p)

    scenes_dir = _ensure_dir(project / "scenes")
    for sc in bundle.scenes:
        p = scenes_dir / f"{sc.scene_id}.yaml"
        write_yaml(p, _build_scene_yaml(sc))
        written["scenes"].append(p)

    shots_dir = _ensure_dir(project / "shots")
    for sh in bundle.shots:
        p = shots_dir / f"{sh.shot_id}.yaml"
        write_yaml(p, _build_shot_yaml(sh))
        written["shots"].append(p)

    return written
