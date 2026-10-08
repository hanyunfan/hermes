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


# ---- new: dynamic input-slot names + duration/start_frame auto-wire ----

_API_MINIMAX_H3 = """\
{
  "1": {"class_type": "MiniMaxH3ImageToVideo", "_meta": {"title": "MiniMaxH3I2V"}, "inputs": {"prompt": ""}},
  "2": {"class_type": "PrimitiveFloat", "_meta": {"title": "FloatDuration"}, "inputs": {"value": 5}},
  "3": {"class_type": "LoadImage", "_meta": {"title": "LoadStartFrame"}, "inputs": {"image": ""}},
  "4": {"class_type": "SaveVideo", "_meta": {"title": "SaveVideo"}, "inputs": {}},
  "5": {"class_type": "SaveVideo", "_meta": {"title": "SaveVideo2"}, "inputs": {}}
}
"""


def _seed_minimax_h3(paths):
    mapping = WorkflowMapping(
        workflow_path="wf.json",
        prompt_node="MiniMaxH3I2V",
        prompt_input_key="prompt",  # not "text" — MiniMaxH3 uses "prompt"
        negative_prompt_node="MiniMaxH3I2V",  # single node; key is same as prompt
        negative_prompt_input_key="prompt",
        seed_node="",
        output_node="SaveVideo",
        image_input_nodes={"start_frame": "LoadStartFrame"},
        extra_param_nodes={"duration_sec": "FloatDuration"},
        extra_param_input_keys={"duration_sec": "value"},  # PrimitiveFloat uses "value"
        duration_param="duration_sec",
        start_frame_role="start_frame",
    )
    from video_director.utils.io import write_yaml
    write_yaml(paths.workflow_mapping_file, mapping.to_dict())
    (paths.private_dir / "wf.json").write_text(_API_MINIMAX_H3)
    return WorkflowResolver(paths, mapping).resolve(), mapping


def test_dynamic_prompt_input_key(tmp_path):
    """Adapter writes shot.prompt into MiniMaxH3.inputs.prompt (NOT .text)."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=8.5, prompt="hello")
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, mapping=mapping)
    adapter.patch_workflow(req)
    i2v = req.workflow["1"]
    assert i2v["inputs"]["prompt"] == "hello"
    assert "text" not in i2v["inputs"]  # did not pollute the wrong slot


def test_duration_auto_wires_from_shot(tmp_path):
    """Adapter auto-writes shot.duration_sec into the duration node."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=12.5, prompt="p")
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, mapping=mapping)
    adapter.patch_workflow(req)
    duration_node = req.workflow["2"]
    assert duration_node["inputs"]["value"] == 12.5


def test_duration_overrides_clobber_extras(tmp_path):
    """workflow_overrides['duration_sec'] is ignored (auto-wired from shot)."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=7,
        prompt="p", workflow_overrides={"duration_sec": 99},
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, mapping=mapping)
    adapter.patch_workflow(req)
    assert req.workflow["2"]["inputs"]["value"] == 7  # shot wins


def test_start_frame_auto_wires_from_shot(tmp_path):
    """Adapter auto-writes shot.start_frame into the start_frame node."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p",
        start_frame="refs/alice/hero.png",
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, mapping=mapping)
    adapter.patch_workflow(req)
    load = req.workflow["3"]
    assert load["inputs"]["image"] == "refs/alice/hero.png"


def test_references_override_shot_start_frame(tmp_path):
    """Explicit character_references[start_frame] beats shot.start_frame."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p",
        start_frame="shot-default.png",
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(
        shot, resolved, references={"start_frame": "refs/explicit.png"},
        mapping=mapping,
    )
    adapter.patch_workflow(req)
    assert req.workflow["3"]["inputs"]["image"] == "refs/explicit.png"


def test_legacy_mapping_unchanged(tmp_path):
    """Mapping without new fields still uses 'text' / 'image' / 'seed' defaults."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p", seed=7)
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)  # no mapping passed
    adapter.patch_workflow(req)
    positive = next(n for n in req.workflow["nodes"] if n["title"] == "PositivePrompt")
    assert positive["inputs"]["text"] == "p"
    sampler = next(n for n in req.workflow["nodes"] if n["title"] == "KSampler")
    assert sampler["inputs"]["seed"] == 7


def test_negative_prompt_skipped_when_same_target(tmp_path):
    """When neg_prompt and prompt both target the same node+slot
    (e.g. MiniMaxH3 single-node setup), writing neg_prompt would
    clobber prompt. Adapter should skip."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved, mapping = _seed_minimax_h3(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=3, prompt="hello",
        negative_prompt="blurry, distorted",  # would clobber if written
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved, mapping=mapping)
    adapter.patch_workflow(req)
    assert req.workflow["1"]["inputs"]["prompt"] == "hello"  # not "blurry"


def test_negative_prompt_written_when_separate_node(tmp_path):
    """Legacy setup (CLIPTextEncode-style with two nodes): neg_prompt
    IS written to its own slot."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p",
        negative_prompt="avoid blurry",
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)  # no mapping → legacy
    adapter.patch_workflow(req)
    positive = next(n for n in req.workflow["nodes"] if n["title"] == "PositivePrompt")
    negative = next(n for n in req.workflow["nodes"] if n["title"] == "NegativePrompt")
    assert positive["inputs"]["text"] == "p"
    assert negative["inputs"]["text"] == "avoid blurry"


def test_workflow_overrides_with_input_key_remap(tmp_path):
    """workflow_overrides[k] writes to extra_param_input_keys[k] (or k as default)."""
    from video_director.core.paths import ProjectPaths
    from video_director.models import Project
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    paths = ProjectPaths.from_project(proj, Project(project_id="proj"))
    resolved = _seed_resolved(paths)
    # Add an extra param "strength" with a slot remap "strength" -> "value"
    # (mimics a PrimitiveFloat-style param named "strength")
    resolved.extra_param_node_ids["strength"] = "7"  # not present in fixture; will be no-op
    # Inject a node into the workflow to back this:
    # Just rely on the existing KSampler node — overwrite "steps" input via remap
    shot = Shot(
        shot_id="s1", scene_id="sc1", duration_sec=2, prompt="p",
        workflow_overrides={"steps": 30},
    )
    adapter = ComfyUIWorkflowAdapter()
    req = adapter.prepare_request(shot, resolved)  # no mapping → defaults
    adapter.patch_workflow(req)
    sampler = next(n for n in req.workflow["nodes"] if n["title"] == "KSampler")
    assert sampler["inputs"]["steps"] == 30