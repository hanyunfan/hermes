"""Tests for the WorkflowResolver (UI format + API format)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from video_director.core.errors import ValidationError, WorkflowNotFoundError
from video_director.core.paths import ProjectPaths
from video_director.models import Project, WorkflowMapping
from video_director.workflow import WorkflowResolver
from video_director.workflow.workflow_resolver import WorkflowResolver as _Direct  # alias
from video_director.utils.io import write_yaml


@pytest.fixture
def project_paths(tmp_path: Path):
    proj = tmp_path / "proj"
    (proj / "private").mkdir(parents=True)
    return ProjectPaths.from_project(proj, Project(project_id="proj"))


def _write_workflow(paths: ProjectPaths, body: str, name: str = "wf.json") -> Path:
    target = paths.private_dir / name
    target.write_text(body, encoding="utf-8")
    return target


def _write_mapping(paths: ProjectPaths, mapping: WorkflowMapping) -> None:
    write_yaml(paths.workflow_mapping_file, mapping.to_dict())


def test_resolver_handles_ui_format(project_paths):
    _write_workflow(project_paths, _UI)
    mapping = WorkflowMapping(
        workflow_path="wf.json",
        prompt_node="PositivePrompt",
        negative_prompt_node="NegativePrompt",
        seed_node="KSampler",
        output_node="VHS_VideoCombine",
        image_input_nodes={"hero": "LoadImageHero"},
    )
    _write_mapping(project_paths, mapping)
    resolved = WorkflowResolver(project_paths, mapping).resolve()
    assert resolved.prompt_node_id == "1"
    assert resolved.image_input_node_ids["hero"] == "4"
    assert resolved.output_node_id == "5"


def test_resolver_handles_api_format(project_paths):
    _write_workflow(project_paths, _API)
    mapping = WorkflowMapping(
        workflow_path="wf.json",
        prompt_node="PositivePrompt",
        negative_prompt_node="NegativePrompt",
        seed_node="KSampler",
        output_node="VHS_VideoCombine",
        image_input_nodes={"hero": "LoadImageHero"},
    )
    _write_mapping(project_paths, mapping)
    resolved = WorkflowResolver(project_paths, mapping).resolve()
    assert resolved.prompt_node_id == "1"
    assert resolved.image_input_node_ids["hero"] == "4"


def test_resolver_raises_when_workflow_missing(project_paths):
    mapping = WorkflowMapping(workflow_path="missing.json", prompt_node="P")
    _write_mapping(project_paths, mapping)
    with pytest.raises(WorkflowNotFoundError):
        WorkflowResolver(project_paths, mapping).resolve()


def test_resolver_raises_when_node_missing(project_paths):
    _write_workflow(project_paths, _UI)
    mapping = WorkflowMapping(
        workflow_path="wf.json",
        prompt_node="NonExistentNode",
        negative_prompt_node="NegativePrompt",
        seed_node="KSampler",
        output_node="VHS_VideoCombine",
    )
    _write_mapping(project_paths, mapping)
    with pytest.raises(ValidationError):
        WorkflowResolver(project_paths, mapping).resolve()


def test_resolver_rejects_path_traversal(project_paths):
    mapping = WorkflowMapping(
        workflow_path="../../../etc/passwd",
        prompt_node="P",
    )
    _write_mapping(project_paths, mapping)
    with pytest.raises(ValidationError):
        WorkflowResolver(project_paths, mapping).resolve()


def test_resolver_rejects_malformed_json(project_paths):
    _write_workflow(project_paths, "{not json")
    mapping = WorkflowMapping(workflow_path="wf.json", prompt_node="P")
    _write_mapping(project_paths, mapping)
    with pytest.raises(ValidationError):
        WorkflowResolver(project_paths, mapping).resolve()


_UI = """\
{
  "last_node_id": 5,
  "last_link_id": 0,
  "nodes": [
    {"id": 1, "type": "CLIPTextEncode", "title": "PositivePrompt", "inputs": {"text": ""}},
    {"id": 2, "type": "CLIPTextEncode", "title": "NegativePrompt", "inputs": {"text": ""}},
    {"id": 3, "type": "KSampler", "title": "KSampler", "inputs": {"seed": 0}},
    {"id": 4, "type": "LoadImage", "title": "LoadImageHero", "inputs": {"image": ""}},
    {"id": 5, "type": "VHS_VideoCombine", "title": "VHS_VideoCombine", "inputs": {}}
  ],
  "links": []
}
"""

_API = """\
{
  "1": {"class_type": "CLIPTextEncode", "_meta": {"title": "PositivePrompt"}, "inputs": {"text": ""}},
  "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "NegativePrompt"}, "inputs": {"text": ""}},
  "3": {"class_type": "KSampler", "_meta": {"title": "KSampler"}, "inputs": {"seed": 0}},
  "4": {"class_type": "LoadImage", "_meta": {"title": "LoadImageHero"}, "inputs": {"image": ""}},
  "5": {"class_type": "VHS_VideoCombine", "_meta": {"title": "VHS_VideoCombine"}, "inputs": {}}
}
"""