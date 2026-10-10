"""Loader for the imports/ directory.

Accepts the raw LLM output and produces :class:`Imports` (a bundle of
dataclass instances). Permissive: missing optional fields default to
empty; extra fields are preserved under ``extra``. The *strict* checks
live in :mod:`video_director.imports.checker`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ImportError(Exception):
    """Raised by the loader when a JSON file is missing or unreadable.

    Schema-level errors are reported by :mod:`video_director.imports.checker`
    as :class:`CheckResult` records, not raised as exceptions.
    """


@dataclass
class ImportedStory:
    story_id: str = ""
    title: str = ""
    language: str = "zh"
    genre: str = ""
    tone: str = ""
    style: str = ""
    target_duration_sec: int = 0
    character_ids: list[str] = field(default_factory=list)
    scene_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedCharacter:
    character_id: str = ""
    name: str = ""
    age: int = 0
    gender: str = ""
    appearance: str = ""
    clothing_default: str = ""
    personality: str = ""
    reference_image: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedScene:
    scene_id: str = ""
    title: str = ""
    location: str = ""
    time_of_day: str = ""
    weather: str = ""
    lighting: str = ""
    environment: str = ""
    character_ids: list[str] = field(default_factory=list)
    duration_sec: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedShot:
    shot_id: str = ""
    scene_id: str = ""
    shot_index: int = 0
    duration_sec: float = 5.0
    shot_type: str = "medium"
    camera: str = ""
    camera_motion: str = "static"
    character_ids: list[str] = field(default_factory=list)
    action: str = ""
    emotion: str = ""
    environment: str = ""
    lighting: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    start_frame_source: str = "manual"  # manual | previous_shot
    start_frame: str = ""
    previous_shot: str = ""
    next_shot: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedDialogue:
    dialogue_id: str = ""
    shot_id: str = ""
    character_id: str = ""
    line: str = ""
    timing_sec: float = 0.0
    emotion: str = ""
    volume: str = "normal"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Imports:
    """Bundle of everything loaded from projects/<id>/imports/."""

    project_dir: Path
    story: ImportedStory | None = None
    characters: list[ImportedCharacter] = field(default_factory=list)
    scenes: list[ImportedScene] = field(default_factory=list)
    shots: list[ImportedShot] = field(default_factory=list)
    dialogues: list[ImportedDialogue] = field(default_factory=list)
    references_dir: Path | None = None
    raw_paths: dict[str, Path] = field(default_factory=dict)


_KNOWN_STORY_FIELDS = {
    "story_id", "title", "language", "genre", "tone", "style",
    "target_duration_sec", "character_ids", "scene_ids",
}
_KNOWN_CHARACTER_FIELDS = {
    "character_id", "name", "age", "gender", "appearance",
    "clothing_default", "personality", "reference_image",
}
_KNOWN_SCENE_FIELDS = {
    "scene_id", "title", "location", "time_of_day", "weather",
    "lighting", "environment", "character_ids", "duration_sec",
}
_KNOWN_SHOT_FIELDS = {
    "shot_id", "scene_id", "shot_index", "duration_sec", "shot_type",
    "camera", "camera_motion", "character_ids", "action", "emotion",
    "environment", "lighting", "prompt", "negative_prompt",
    "start_frame_source", "start_frame", "previous_shot", "next_shot",
}
_KNOWN_DIALOGUE_FIELDS = {
    "dialogue_id", "shot_id", "character_id", "line", "timing_sec",
    "emotion", "volume",
}


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ImportError(f"file not found: {path}") from e
    except OSError as e:
        raise ImportError(f"cannot read {path}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ImportError(
            f"invalid JSON in {path.name}: line {e.lineno} col {e.colno}: {e.msg}"
        ) from e


def _split_known_and_extra(raw: dict, known: set[str]) -> tuple[dict, dict]:
    """Pull known fields into one dict, everything else into ``extra``."""
    known_dict: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for k, v in raw.items():
        if k in known:
            known_dict[k] = v
        else:
            extra[k] = v
    return known_dict, extra


def _coerce_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise ImportError(
                    f"{field_name}[{i}] must be string, got {type(item).__name__}"
                )
            out.append(item)
        return out
    raise ImportError(f"{field_name} must be string or list of strings, got {type(value).__name__}")


def _parse_story(raw: Any) -> ImportedStory:
    if not isinstance(raw, dict):
        raise ImportError(f"story.json must be an object, got {type(raw).__name__}")
    known, extra = _split_known_and_extra(raw, _KNOWN_STORY_FIELDS)
    return ImportedStory(
        story_id=str(known.get("story_id", "")),
        title=str(known.get("title", "")),
        language=str(known.get("language", "zh")),
        genre=str(known.get("genre", "")),
        tone=str(known.get("tone", "")),
        style=str(known.get("style", "")),
        target_duration_sec=int(known.get("target_duration_sec", 0) or 0),
        character_ids=_coerce_str_list(known.get("character_ids"), "character_ids"),
        scene_ids=_coerce_str_list(known.get("scene_ids"), "scene_ids"),
        extra=extra,
    )


def _parse_characters(raw: Any) -> list[ImportedCharacter]:
    if not isinstance(raw, list):
        raise ImportError(f"characters.json must be an array, got {type(raw).__name__}")
    out: list[ImportedCharacter] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ImportError(f"characters[{i}] must be an object")
        known, extra = _split_known_and_extra(item, _KNOWN_CHARACTER_FIELDS)
        out.append(ImportedCharacter(
            character_id=str(known.get("character_id", "")),
            name=str(known.get("name", "")),
            age=int(known.get("age", 0) or 0),
            gender=str(known.get("gender", "")),
            appearance=str(known.get("appearance", "")),
            clothing_default=str(known.get("clothing_default", "")),
            personality=str(known.get("personality", "")),
            reference_image=str(known.get("reference_image", "")),
            extra=extra,
        ))
    return out


def _parse_scenes(raw: Any) -> list[ImportedScene]:
    if not isinstance(raw, list):
        raise ImportError(f"scenes.json must be an array, got {type(raw).__name__}")
    out: list[ImportedScene] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ImportError(f"scenes[{i}] must be an object")
        known, extra = _split_known_and_extra(item, _KNOWN_SCENE_FIELDS)
        out.append(ImportedScene(
            scene_id=str(known.get("scene_id", "")),
            title=str(known.get("title", "")),
            location=str(known.get("location", "")),
            time_of_day=str(known.get("time_of_day", "")),
            weather=str(known.get("weather", "")),
            lighting=str(known.get("lighting", "")),
            environment=str(known.get("environment", "")),
            character_ids=_coerce_str_list(known.get("character_ids"), "character_ids"),
            duration_sec=int(known.get("duration_sec", 0) or 0),
            extra=extra,
        ))
    return out


def _parse_shots(raw: Any) -> list[ImportedShot]:
    if not isinstance(raw, list):
        raise ImportError(f"shots.json must be an array, got {type(raw).__name__}")
    out: list[ImportedShot] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ImportError(f"shots[{i}] must be an object")
        known, extra = _split_known_and_extra(item, _KNOWN_SHOT_FIELDS)
        out.append(ImportedShot(
            shot_id=str(known.get("shot_id", "")),
            scene_id=str(known.get("scene_id", "")),
            shot_index=int(known.get("shot_index", 0) or 0),
            duration_sec=float(known.get("duration_sec", 5.0) or 5.0),
            shot_type=str(known.get("shot_type", "medium")),
            camera=str(known.get("camera", "")),
            camera_motion=str(known.get("camera_motion", "static")),
            character_ids=_coerce_str_list(known.get("character_ids"), "character_ids"),
            action=str(known.get("action", "")),
            emotion=str(known.get("emotion", "")),
            environment=str(known.get("environment", "")),
            lighting=str(known.get("lighting", "")),
            prompt=str(known.get("prompt", "")),
            negative_prompt=str(known.get("negative_prompt", "")),
            start_frame_source=str(known.get("start_frame_source", "manual")),
            start_frame=str(known.get("start_frame", "")),
            previous_shot=str(known.get("previous_shot", "")),
            next_shot=str(known.get("next_shot", "")),
            extra=extra,
        ))
    return out


def _parse_dialogues(raw: Any) -> list[ImportedDialogue]:
    if not isinstance(raw, list):
        raise ImportError(f"dialogues.json must be an array, got {type(raw).__name__}")
    out: list[ImportedDialogue] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ImportError(f"dialogues[{i}] must be an object")
        known, extra = _split_known_and_extra(item, _KNOWN_DIALOGUE_FIELDS)
        out.append(ImportedDialogue(
            dialogue_id=str(known.get("dialogue_id", "")),
            shot_id=str(known.get("shot_id", "")),
            character_id=str(known.get("character_id", "")),
            line=str(known.get("line", "")),
            timing_sec=float(known.get("timing_sec", 0.0) or 0.0),
            emotion=str(known.get("emotion", "")),
            volume=str(known.get("volume", "normal")),
            extra=extra,
        ))
    return out


def load_imports(project_dir: str | Path) -> Imports:
    """Load every JSON file under ``project_dir/imports/``.

    Required files: ``story.json``, ``characters.json``, ``scenes.json``,
    ``shots.json``. ``dialogues.json`` is optional.
    """
    project_dir = Path(project_dir).resolve()
    imports_dir = project_dir / "imports"
    if not imports_dir.is_dir():
        raise ImportError(f"imports directory not found: {imports_dir}")

    raw_paths: dict[str, Path] = {}
    bundle = Imports(project_dir=project_dir, raw_paths=raw_paths)

    # ---- story.json (required) ----
    story_path = imports_dir / "story.json"
    if not story_path.exists():
        raise ImportError(f"required file missing: {story_path}")
    bundle.story = _parse_story(_read_json(story_path))
    raw_paths["story"] = story_path

    # ---- characters.json (required) ----
    chars_path = imports_dir / "characters.json"
    if not chars_path.exists():
        raise ImportError(f"required file missing: {chars_path}")
    bundle.characters = _parse_characters(_read_json(chars_path))
    raw_paths["characters"] = chars_path

    # ---- scenes.json (required) ----
    scenes_path = imports_dir / "scenes.json"
    if not scenes_path.exists():
        raise ImportError(f"required file missing: {scenes_path}")
    bundle.scenes = _parse_scenes(_read_json(scenes_path))
    raw_paths["scenes"] = scenes_path

    # ---- shots.json (required) ----
    shots_path = imports_dir / "shots.json"
    if not shots_path.exists():
        raise ImportError(f"required file missing: {shots_path}")
    bundle.shots = _parse_shots(_read_json(shots_path))
    raw_paths["shots"] = shots_path

    # ---- dialogues.json (optional) ----
    dialogues_path = imports_dir / "dialogues.json"
    if dialogues_path.exists():
        bundle.dialogues = _parse_dialogues(_read_json(dialogues_path))
        raw_paths["dialogues"] = dialogues_path

    # ---- references/ (optional) ----
    refs_dir = imports_dir / "references"
    if refs_dir.is_dir():
        bundle.references_dir = refs_dir

    return bundle
