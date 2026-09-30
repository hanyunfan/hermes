"""Tests for ProjectManager lifecycle."""

from __future__ import annotations

import pytest

from video_director.core.errors import ProjectExistsError, ProjectNotFoundError, ValidationError
from video_director.core.project_manager import ProjectManager

from ..conftest import temp_project_root, make_pm
from ..fixtures import data


def test_init_creates_directories():
    with temp_project_root() as root:
        pm = make_pm(root)
        project = pm.init_project("story_alpha")
        assert project.project_id == "story_alpha"
        proj_root = pm.project_root_for("story_alpha")
        assert (proj_root / "project.yaml").exists()
        for sub in ("characters", "scenes", "shots", "references", "private", "output", "state"):
            assert (proj_root / sub).is_dir()


def test_init_twice_raises():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("dup")
        with pytest.raises(ProjectExistsError):
            pm.init_project("dup")


def test_load_project_validates_id_matches_dir():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("ok_id")
        # Tamper with the file: rename project_id
        proj_file = pm.project_root_for("ok_id") / "project.yaml"
        text = proj_file.read_text()
        proj_file.write_text(text.replace("project_id: ok_id", "project_id: renamed"))
        with pytest.raises(ValidationError):
            pm.load_project(pm.project_root_for("ok_id"))


def test_unknown_project_raises():
    with temp_project_root() as root:
        pm = make_pm(root)
        with pytest.raises(ProjectNotFoundError):
            pm.paths_for_id("ghost")


def test_list_projects_excludes_template_by_default():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("alpha")
        pm.init_project("beta")
        listed = pm.list_projects()
        ids = [p.project_id for p in listed]
        assert "alpha" in ids and "beta" in ids and "template" not in ids
        listed_all = pm.list_projects(include_template=True)
        assert "template" in [p.project_id for p in listed_all]


def test_template_round_trips_through_init():
    with temp_project_root() as root:
        pm = make_pm(root)
        project = pm.init_project("from_template", title="Hello", target_duration_sec=600)
        paths = pm.paths_for(project)
        story = pm.load_story(paths)
        assert story is not None
        assert story.title == "Example Story Title"


def test_save_and_load_character():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("chars_no_template", from_template=False)
        paths = pm.paths_for_id("chars_no_template")
        from video_director.models import Character
        c = Character(character_id="alice", name="Alice", appearance="x")
        pm.save_character(paths, c)
        loaded = list(pm.iter_characters(paths))
        ids = [c.character_id for c in loaded]
        assert "alice" in ids


def test_workflow_mapping_saved_and_loaded():
    with temp_project_root() as root:
        pm = make_pm(root)
        pm.init_project("wf")
        paths = pm.paths_for_id("wf")
        from video_director.models import WorkflowMapping
        m = WorkflowMapping(workflow_name="t", workflow_path="wf.json", prompt_node="P")
        pm.save_workflow_mapping(paths, m)
        m2 = pm.load_workflow_mapping(paths)
        assert m2 is not None and m2.prompt_node == "P"