"""Tests for ComfyUIWorkflowAdapter patching logic."""

from __future__ import annotations

import json

from video_director.models import Shot, WorkflowMapping
from video_director.workflow import WorkflowResolver
from video_director.workflow.adapter import ComfyUIWorkflowAdapter

from .test_workflow_resolver import project_paths, _UI  # noqa: F401


def _seed_resolved(paths):
    mapping = WorkflowMapping(
        workflow_path="wf.json",
        prompt_node="PositivePrompt",
        negative_prompt_node="NegativePrompt",
        seed_node="KSampler",
        output_node="VHS_VideoCombine",
        image_input_nodes={"hero": "LoadImageHero"},
        extra_param_nodes={"steps": "KSampler"},
    )
    from video_director.utils.io import write_yaml
    write_yaml(paths.workflow_mapping_file, mapping.to_dict())
    (paths.private_dir / "wf.json").write_text(_UI)
    return WorkflowResolver(paths, mapping).resolve()


def test_patch_writes_prompt_and_seed(tmp_path):
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=2, prompt="hello world", seed=123)
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)
    adapter.patch_workflow(req)
    # UI format: nodes list
    prompt_node = next(n for n in req.workflow["nodes"] if n["title"] == "PositivePrompt")
    assert prompt_node["inputs"]["text"] == "hello world"
    sampler = next(n for n in req.workflow["nodes"] if n["title"] == "KSampler")
    assert sampler["inputs"]["seed"] == 123


def test_patch_rotates_seed_when_shot_seed_missing(tmp_path):
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p")
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)
    adapter.patch_workflow(req)
    assert isinstance(req.seed_used, int)
    assert req.seed_used > 0


def test_patch_writes_image_inputs(tmp_path):
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p")
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, references={"hero": "refs/alice/hero.png"})
    adapter.patch_workflow(req)
    load_image = next(n for n in req.workflow["nodes"] if n["title"] == "LoadImageHero")
    assert load_image["inputs"]["image"] == "refs/alice/hero.png"


def test_patch_writes_extra_params(tmp_path):
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p",
        workflow_overrides={"steps": 30},
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)
    adapter.patch_workflow(req)
    sampler = next(n for n in req.workflow["nodes"] if n["title"] == "KSampler")
    assert sampler["inputs"]["steps"] == 30


def test_required_node_titles_filters_blanks():
    m = WorkflowMapping(
        workflow_path="x",
        prompt_node="P", negative_prompt_node="N",
        seed_node="", output_node="O",
        image_input_nodes={"a": "A", "b": ""},
    )
    titles = m.required_node_titles()
    assert "P" in titles and "N" in titles and "O" in titles
    assert "A" in titles and "" not in titles