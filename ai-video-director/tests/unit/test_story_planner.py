"""Tests for StoryAnalyzer + ScenePlanner + ShotPlanner."""

from __future__ import annotations

from video_director.models import ScriptSection, Story
from video_director.story import ScenePlanner, ShotPlanner, StoryAnalyzer


def _build_story():
    return Story(
        story_id="s", title="T", story_summary="A small test.",
        script=[
            ScriptSection(section_id="a", title="A", body="Alice walks in.", characters=["Alice"]),
            ScriptSection(section_id="b", title="B", body="Bob joins Alice.", characters=["Alice", "Bob"]),
            ScriptSection(section_id="c", title="C", body="They leave together.", characters=["Alice", "Bob"]),
        ],
    )


def test_analyzer_extracts_characters():
    s = _build_story()
    bible = StoryAnalyzer().analyze(s)
    assert "Alice" in bible.characters
    assert "Bob" in bible.characters


def test_analyzer_extracts_beats():
    s = _build_story()
    bible = StoryAnalyzer().analyze(s)
    assert len(bible.beats) >= 3
    assert any("Alice" in b for b in bible.beats)


def test_analyzer_empty_script_returns_empty_bible():
    bible = StoryAnalyzer().analyze(Story(story_id="e", title="E"))
    assert bible.title == "E"
    assert bible.beats == []


def test_analyzer_splits_into_acts():
    s = _build_story()
    bible = StoryAnalyzer(min_acts=3, max_acts=3).analyze(s)
    assert len(bible.acts) == 3


def test_scene_planner_one_scene_per_section():
    s = _build_story()
    bible = StoryAnalyzer().analyze(s)
    scenes = ScenePlanner().plan(s, bible)
    assert len(scenes) == 3
    assert scenes[0].scene_id == "scene_001"


def test_scene_planner_picks_declared_characters():
    s = _build_story()
    bible = StoryAnalyzer().analyze(s)
    scenes = ScenePlanner().plan(s, bible)
    assert scenes[0].characters == ["Alice"]
    assert scenes[1].characters == ["Alice", "Bob"]


def test_shot_planner_min_two_shots_per_scene():
    from video_director.models import Scene
    sc = Scene(scene_id="s1", title="T", location="L", characters=["a"], description="d", duration_sec=30)
    plans = ShotPlanner().plan_scene(sc)
    assert len(plans) >= 2


def test_shot_planner_respects_max_per_scene():
    from video_director.models import Scene
    sc = Scene(scene_id="s1", title="T", location="L", characters=["a"], description="d", duration_sec=999)
    plans = ShotPlanner(default_shot_duration_sec=1, max_shots_per_scene=4).plan_scene(sc)
    assert len(plans) <= 4


def test_shot_planner_to_shot_uses_scene_id_in_id():
    from video_director.models import Scene
    sc = Scene(scene_id="scene_007", title="T", location="L", characters=["a"], description="d")
    plans = ShotPlanner().plan_scene(sc)
    shot = plans[0].to_shot()
    assert shot.shot_id.startswith("scene_007_shot_")
    assert shot.scene_id == "scene_007"
    assert shot.shot_index == 1


def test_shot_planner_assigns_prompt():
    from video_director.models import Scene
    sc = Scene(scene_id="s", title="T", location="L", characters=["a"], description="alice runs")
    plans = ShotPlanner().plan_scene(sc)
    assert "alice runs" in plans[0].prompt


def test_story_full_text_concat():
    s = _build_story()
    assert "Alice walks in." in s.full_text
    assert "Bob joins Alice." in s.full_text