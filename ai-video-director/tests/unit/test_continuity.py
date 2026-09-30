"""Tests for ContinuityManager."""

from __future__ import annotations

from video_director.continuity import ContinuityManager
from video_director.models import (
    Character,
    CharacterBible,
    CharacterReference,
    ContinuityAspect,
    Scene,
    Shot,
    ShotStatus,
)


def _alice():
    return Character(
        character_id="alice", name="Alice", appearance="short hair",
        clothing_default="blue dress",
        reference_images=[CharacterReference(role="hero", path="alice/hero.png")],
        continuity_rules=["Always blue dress unless changed."],
    )


def test_unknown_character_flagged_high_severity():
    bible = CharacterBible(characters=[_alice()])
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=1, prompt="x", characters=["ghost"])
    issues = ContinuityManager().check_story(bible, [shot])
    assert any(i.aspect == ContinuityAspect.FACE and i.severity == "high" for i in issues)


def test_continuity_rule_emits_low_severity_issue():
    bible = CharacterBible(characters=[_alice()])
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=1, prompt="x", characters=["alice"])
    issues = ContinuityManager().check_story(bible, [shot])
    assert any(i.severity == "low" for i in issues)


def test_consecutive_shots_linked():
    bible = CharacterBible(characters=[_alice()])
    s1 = Shot(shot_id="s1", scene_id="sc1", shot_index=1, duration_sec=1, prompt="x", characters=["alice"])
    s2 = Shot(shot_id="s2", scene_id="sc1", shot_index=2, duration_sec=1, prompt="y", characters=["alice"])
    ContinuityManager().check_story(bible, [s1, s2])
    assert s2.previous_shot == "s1"


def test_shot_change_records_outfit_change_medium():
    bible = CharacterBible(characters=[_alice()])
    s1 = Shot(shot_id="s1", scene_id="sc1", duration_sec=1, prompt="x", characters=["alice"])
    s2 = Shot(
        shot_id="s2", scene_id="sc1", duration_sec=1, prompt="y",
        characters=["alice"], workflow_overrides={"outfit": "red dress"},
    )
    issues = ContinuityManager().check_story(bible, [s1, s2])
    assert any(i.severity == "medium" and i.aspect == ContinuityAspect.CLOTHING for i in issues)


def test_build_reference_payload_includes_roles():
    cm = ContinuityManager()
    char = _alice()
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=1, prompt="x", characters=["alice"])
    payload = cm.build_reference_payload(char, shot)
    assert payload["hero"] == "alice/hero.png"


def test_build_reference_payload_passes_start_frame():
    cm = ContinuityManager()
    char = _alice()
    # Case 1: prev: prefix → not exposed as a backend input
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=1, prompt="x",
                characters=["alice"], start_frame="prev:s0")
    payload = cm.build_reference_payload(char, shot)
    assert "start_frame" not in payload
    # Case 2: real path → included
    shot.start_frame = "real_start_frame.png"
    payload = cm.build_reference_payload(char, shot)
    assert payload["start_frame"] == "real_start_frame.png"


def test_link_disabled_does_not_set_previous_shot():
    bible = CharacterBible(characters=[_alice()])
    s1 = Shot(shot_id="s1", scene_id="sc1", shot_index=1, duration_sec=1, prompt="x", characters=["alice"])
    s2 = Shot(shot_id="s2", scene_id="sc1", shot_index=2, duration_sec=1, prompt="y", characters=["alice"])
    ContinuityManager(link_end_to_next_start=False).check_story(bible, [s1, s2])
    assert s2.previous_shot == ""