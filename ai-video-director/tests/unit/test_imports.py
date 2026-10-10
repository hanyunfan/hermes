"""Tests for the imports/ subsystem.

Covers:
  * loader: parses all 5 JSON shapes
  * checker: every error code is reachable, fixes are actionable
  * builder: imports → yaml round-trips cleanly
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from video_director.imports import (  # noqa: E402
    ImportError,
    build_yaml_from_imports,
    check_imports,
    load_imports,
)


# ---------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def minimal_project(tmp_path) -> Path:
    """Write a minimal valid imports/ tree under tmp_path/imports."""
    project = tmp_path / "demo"
    project.mkdir()
    imports_dir = project / "imports"
    imports_dir.mkdir()

    (imports_dir / "story.json").write_text(json.dumps({
        "story_id": "demo",
        "title": "Demo",
        "language": "zh",
        "target_duration_sec": 30,
        "character_ids": ["hero"],
        "scene_ids": ["scene_one"],
    }, ensure_ascii=False))

    (imports_dir / "characters.json").write_text(json.dumps([{
        "character_id": "hero",
        "name": "主角",
        "age": 25,
        "gender": "female",
        "appearance": "young woman, black hair, brown eyes",
        "clothing_default": "blue robe",
        "personality": "brave",
    }], ensure_ascii=False))

    (imports_dir / "scenes.json").write_text(json.dumps([{
        "scene_id": "scene_one",
        "title": "场景一",
        "location": "城内",
        "time_of_day": "morning",
        "lighting": "soft",
        "environment": "stone street",
        "character_ids": ["hero"],
        "duration_sec": 30,
    }], ensure_ascii=False))

    (imports_dir / "shots.json").write_text(json.dumps([
        {
            "shot_id": "scene_one_shot_001",
            "scene_id": "scene_one",
            "shot_index": 1,
            "duration_sec": 5,
            "shot_type": "medium",
            "camera": "50mm",
            "camera_motion": "static",
            "character_ids": ["hero"],
            "action": "stands still",
            "emotion": "calm",
            "environment": "stone street",
            "lighting": "soft",
            "prompt": "Cinematic medium shot of hero standing still",
            "negative_prompt": "blurry",
            "start_frame_source": "manual",
            "start_frame": "imports/references/hero/hero.png",
            "previous_shot": "",
            "next_shot": "scene_one_shot_002",
        },
        {
            "shot_id": "scene_one_shot_002",
            "scene_id": "scene_one",
            "shot_index": 2,
            "duration_sec": 5,
            "shot_type": "medium",
            "camera": "50mm",
            "camera_motion": "static",
            "character_ids": ["hero"],
            "action": "walks forward",
            "emotion": "calm",
            "environment": "stone street",
            "lighting": "soft",
            "prompt": "Cinematic medium shot of hero walking forward",
            "negative_prompt": "blurry",
            "start_frame_source": "previous_shot",
            "start_frame": "",
            "previous_shot": "scene_one_shot_001",
            "next_shot": "",
        },
    ], ensure_ascii=False))

    return project


# ---------------------------------------------------------------------
# loader
# ---------------------------------------------------------------------


def test_loader_parses_all_required_files(minimal_project):
    bundle = load_imports(minimal_project)
    assert bundle.story is not None
    assert bundle.story.story_id == "demo"
    assert len(bundle.characters) == 1
    assert bundle.characters[0].name == "主角"
    assert len(bundle.scenes) == 1
    assert len(bundle.shots) == 2
    assert bundle.dialogues == []


def test_loader_loads_optional_dialogues(minimal_project):
    (minimal_project / "imports" / "dialogues.json").write_text(json.dumps([
        {
            "dialogue_id": "dl_001",
            "shot_id": "scene_one_shot_001",
            "character_id": "hero",
            "line": "你好",
            "timing_sec": 1.0,
            "emotion": "calm",
            "volume": "normal",
        }
    ], ensure_ascii=False))
    bundle = load_imports(minimal_project)
    assert len(bundle.dialogues) == 1
    assert bundle.dialogues[0].line == "你好"


def test_loader_raises_on_missing_required(minimal_project):
    (minimal_project / "imports" / "shots.json").unlink()
    with pytest.raises(ImportError, match="shots.json"):
        load_imports(minimal_project)


def test_loader_raises_on_invalid_json(minimal_project):
    (minimal_project / "imports" / "shots.json").write_text("{not valid")
    with pytest.raises(ImportError, match="invalid JSON"):
        load_imports(minimal_project)


# ---------------------------------------------------------------------
# checker — pass case
# ---------------------------------------------------------------------


def test_checker_passes_minimal(minimal_project):
    bundle = load_imports(minimal_project)
    report = check_imports(bundle)
    assert report.ok, report.render()


# ---------------------------------------------------------------------
# checker — every error code is reachable
# ---------------------------------------------------------------------


def test_checker_invalid_slug(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[{"character_id": "Bad-ID", "name": "n", "appearance": "a"}]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "scene_one", "location": "x"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([{
        "shot_id": "scene_one_shot_001",
        "scene_id": "scene_one",
        "duration_sec": 5,
        "prompt": "x",
        "negative_prompt": "y",
        "previous_shot": "",
        "next_shot": "",
    }]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    codes = {r.code for r in report.errors}
    assert "INVALID_SLUG" in codes


def test_checker_missing_reference(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[{"character_id": "hero", "name": "n", "appearance": "a"}]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "scene_one", "location": "x"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([{
        "shot_id": "scene_one_shot_001",
        "scene_id": "scene_one",
        "duration_sec": 5,
        "prompt": "x",
        "negative_prompt": "y",
        "character_ids": ["nonexistent"],
        "previous_shot": "",
        "next_shot": "",
    }]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "MISSING_REFERENCE" for r in report.errors)


def test_checker_broken_chain(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": "s_shot_002"},
        {"shot_id": "s_shot_002", "scene_id": "s", "shot_index": 2, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "WRONG", "next_shot": ""},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "BROKEN_CHAIN" for r in report.errors)


def test_checker_empty_prompt(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "EMPTY_PROMPT" for r in report.errors)


def test_checker_bad_duration(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 30,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "BAD_DURATION" for r in report.errors)


def test_checker_too_many_shots(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    shots = [
        {"shot_id": f"s_shot_{i:03d}", "scene_id": "s", "shot_index": i, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""}
        for i in range(1, 152)
    ]
    (p / "imports" / "shots.json").write_text(json.dumps(shots))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "TOO_MANY_SHOTS" for r in report.errors)


def test_checker_duplicate_shot_id(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 2, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "DUPLICATE_SHOT_ID" for r in report.errors)


def test_checker_dialogue_bad_reference(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[{"character_id": "hero", "name": "n", "appearance": "a"}]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    (p / "imports" / "dialogues.json").write_text(json.dumps([
        {"dialogue_id": "dl_001", "shot_id": "MISSING", "character_id": "hero",
         "line": "x", "timing_sec": 0, "emotion": "", "volume": "normal"},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "MISSING_REFERENCE_IMAGE" for r in report.errors)


def test_checker_reference_dir_mismatch_warns(tmp_path):
    """character_id='hero' but file in references/1/ should WARN (the
    common Grok mistake: dir name != character_id)."""
    p = tmp_path / "p"
    (p / "imports" / "references" / "1").mkdir(parents=True)
    (p / "imports" / "references" / "1" / "hero.jpg").write_bytes(b"fake")
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text(json.dumps([{
        "character_id": "hero",
        "name": "n",
        "appearance": "a",
        "reference_image": "imports/references/1/hero.jpg",
    }], ensure_ascii=False))
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "REFERENCE_DIR_MISMATCH" for r in report.warnings)


def test_checker_dialogue_bad_reference(tmp_path):
    p = tmp_path / "p"
    (p / "imports").mkdir(parents=True)
    (p / "imports" / "story.json").write_text('{"story_id": "OK", "title": "t", "language": "zh"}')
    (p / "imports" / "characters.json").write_text('[{"character_id": "hero", "name": "n", "appearance": "a"}]')
    (p / "imports" / "scenes.json").write_text('[{"scene_id": "s"}]')
    (p / "imports" / "shots.json").write_text(json.dumps([
        {"shot_id": "s_shot_001", "scene_id": "s", "shot_index": 1, "duration_sec": 5,
         "prompt": "x", "negative_prompt": "y", "previous_shot": "", "next_shot": ""},
    ]))
    (p / "imports" / "dialogues.json").write_text(json.dumps([
        {"dialogue_id": "dl_001", "shot_id": "MISSING", "character_id": "hero",
         "line": "x", "timing_sec": 0, "emotion": "", "volume": "normal"},
    ]))
    bundle = load_imports(p)
    report = check_imports(bundle)
    assert any(r.code == "DIALOGUE_BAD_REFERENCE" for r in report.errors)


# ---------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------


def test_builder_writes_yaml_round_trip(minimal_project):
    bundle = load_imports(minimal_project)
    report = check_imports(bundle)
    assert report.ok
    written = build_yaml_from_imports(bundle)
    assert len(written["story"]) == 1
    assert len(written["characters"]) == 1
    assert len(written["scenes"]) == 1
    assert len(written["shots"]) == 2
    # Re-load to confirm yaml is parseable
    bundle2 = load_imports(minimal_project)
    assert bundle2.shots[0].shot_id == "scene_one_shot_001"


def test_builder_embeds_dialogues_in_shot_yaml(minimal_project):
    (minimal_project / "imports" / "dialogues.json").write_text(json.dumps([
        {"dialogue_id": "dl_001", "shot_id": "scene_one_shot_001",
         "character_id": "hero", "line": "你好", "timing_sec": 1.0,
         "emotion": "calm", "volume": "normal"},
    ], ensure_ascii=False))
    bundle = load_imports(minimal_project)
    report = check_imports(bundle)
    assert report.ok
    build_yaml_from_imports(bundle)
    # Read back the shot yaml and check the dialogues landed
    import yaml
    shot_yaml = yaml.safe_load((minimal_project / "shots" / "scene_one_shot_001.yaml").read_text())
    assert "dialogues" in shot_yaml.get("extra", {})
    assert shot_yaml["extra"]["dialogues"][0]["line"] == "你好"


# ---------------------------------------------------------------------
# end-to-end CLI smoke
# ---------------------------------------------------------------------


def test_cli_validate_imports_hello_test_passes():
    """End-to-end: run the real CLI against the hello_test sample project."""
    project_root = Path("/home/frank/hermes/ai-video-director")
    if not (project_root / "projects" / "hello_test" / "imports" / "story.json").exists():
        pytest.skip("hello_test/imports not present")
    result = subprocess.run(
        [str(project_root / ".venv" / "bin" / "video-director"), "validate-imports", "hello_test"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert "ALL CHECKS PASSED" in result.stdout or result.returncode == 0, result.stdout + result.stderr
