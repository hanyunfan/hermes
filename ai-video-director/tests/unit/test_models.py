"""Tests for the data models. Pure data, no I/O."""

from __future__ import annotations

import pytest

from video_director.models import (
    Character,
    CharacterReference,
    GenerationJob,
    JobStatus,
    Project,
    Scene,
    Shot,
    ShotStatus,
    Story,
    StoryBible,
    ScriptSection,
    VideoClip,
    WorkflowMapping,
)


def test_project_roundtrip():
    p = Project(project_id="p1", title="P", target_duration_sec=120)
    d = p.to_dict()
    p2 = Project.from_dict(d)
    assert p2.project_id == p.project_id
    assert p2.title == p.title
    assert p2.target_duration_sec == 120


def test_project_invalid_id():
    with pytest.raises(ValueError):
        Project(project_id="../escape")
    with pytest.raises(ValueError):
        Project(project_id="WITH CAPS")


def test_story_roundtrip():
    s = Story(
        story_id="s", title="T",
        script=[ScriptSection(section_id="x", body="hello", characters=["a"])],
    )
    d = s.to_dict()
    s2 = Story.from_dict(d)
    assert len(s2.script) == 1
    assert s2.script[0].body == "hello"


def test_character_requires_appearance():
    with pytest.raises(ValueError):
        Character(character_id="a", name="A", appearance="")


def test_character_roundtrip_with_refs():
    c = Character(
        character_id="a", name="Alice", appearance="short hair",
        reference_images=[CharacterReference(role="hero", path="a/hero.png")],
    )
    c2 = Character.from_dict(c.to_dict())
    assert c2.reference_images[0].path == "a/hero.png"


def test_shot_status_normalised():
    sh = Shot(shot_id="x", scene_id="s", duration_sec=1, prompt="p")
    assert sh.status == ShotStatus.PENDING
    d = sh.to_dict()
    d["status"] = "completed"
    sh2 = Shot.from_dict(d)
    assert sh2.status == ShotStatus.COMPLETED


def test_shot_unknown_status_falls_back_to_pending():
    sh = Shot(shot_id="x", scene_id="s", duration_sec=1, prompt="p")
    d = sh.to_dict()
    d["status"] = "not-a-real-status"
    sh2 = Shot.from_dict(d)
    assert sh2.status == ShotStatus.PENDING


def test_job_roundtrip():
    j = GenerationJob(
        job_id="p__s__a001__x", shot_id="s", scene_id="sc", project_id="p",
        backend="mock", attempt=1,
    )
    d = j.to_dict()
    j2 = GenerationJob.from_dict(d)
    assert j2.job_id == j.job_id
    assert j2.attempt == 1


def test_workflow_mapping_roundtrip():
    m = WorkflowMapping(
        workflow_name="t", workflow_path="wf.json",
        prompt_node="P", negative_prompt_node="N",
        seed_node="S", output_node="O",
        image_input_nodes={"hero": "H"},
        extra_param_nodes={"steps": "K"},
    )
    m2 = WorkflowMapping.from_dict(m.to_dict())
    assert m2.image_input_nodes == {"hero": "H"}
    assert m2.extra_param_nodes == {"steps": "K"}


def test_video_clip_roundtrip():
    c = VideoClip(shot_id="s1", path="/tmp/x.mp4", duration_sec=1.5, width=320, height=180)
    c2 = VideoClip.from_dict(c.to_dict())
    assert c2.width == 320 and c2.height == 180