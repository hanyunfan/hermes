"""Workflow adapter models: the indirection between shots and a real
ComfyUI / cloud-API workflow JSON.

Crucially, *real* workflow JSON is never stored in this repo. The
``WorkflowTemplate`` is a public placeholder schema; user-supplied workflows
live under each project's ``private/`` (gitignored) directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class WorkflowMapping:
    """How a shot's fields map onto nodes in a ComfyUI workflow.

    Node IDs are user-supplied; we treat them as opaque strings. Each entry
    is the *title* of the node (e.g. ``"PositivePrompt"``) rather than the
    ``"42"`` numeric ID — this survives node renumbering in the ComfyUI
    editor and keeps the mapping file readable.
    """

    workflow_name: str = ""
    workflow_path: str = ""  # relative to project private dir, NOT the public repo
    prompt_node: str = ""
    negative_prompt_node: str = ""
    seed_node: str = ""
    output_node: str = ""
    image_input_nodes: dict[str, str] = field(default_factory=dict)
    # role -> node_title for each character/scene reference image
    extra_param_nodes: dict[str, str] = field(default_factory=dict)
    # arbitrary extra param -> node_title pairs (size, steps, cfg, ...)
    notes: str = ""

    def required_node_titles(self) -> list[str]:
        nodes = [
            self.prompt_node,
            self.negative_prompt_node,
            self.seed_node,
            self.output_node,
        ]
        nodes.extend(self.image_input_nodes.values())
        nodes.extend(self.extra_param_nodes.values())
        return [n for n in nodes if n]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "workflow_path": self.workflow_path,
            "prompt_node": self.prompt_node,
            "negative_prompt_node": self.negative_prompt_node,
            "seed_node": self.seed_node,
            "output_node": self.output_node,
            "image_input_nodes": dict(self.image_input_nodes),
            "extra_param_nodes": dict(self.extra_param_nodes),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowMapping":
        return cls(
            workflow_name=str(data.get("workflow_name", "")),
            workflow_path=str(data.get("workflow_path", "")),
            prompt_node=str(data.get("prompt_node", "")),
            negative_prompt_node=str(data.get("negative_prompt_node", "")),
            seed_node=str(data.get("seed_node", "")),
            output_node=str(data.get("output_node", "")),
            image_input_nodes=dict(data.get("image_input_nodes", {}) or {}),
            extra_param_nodes=dict(data.get("extra_param_nodes", {}) or {}),
            notes=str(data.get("notes", "")),
        )


@dataclass
class WorkflowTemplate:
    """Public placeholder schema for a workflow file.

    Real workflow JSON is NEVER stored in this repo. The placeholder's only
    job is to document the *shape* expected by the adapter and to provide a
    starting point for users to drop their own workflow into ``private/``.
    """

    workflow_name: str = "USER_PROVIDED_VIDEO_WORKFLOW"
    description: str = (
        "PLACEHOLDER. Real ComfyUI workflow JSON must be supplied by the user "
        "under this project's private/ directory. See docs/comfyui.md."
    )
    schema_version: str = "0.1.0"
    nodes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "description": self.description,
            "schema_version": self.schema_version,
            "nodes": dict(self.nodes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowTemplate":
        return cls(
            workflow_name=str(data.get("workflow_name", "USER_PROVIDED_VIDEO_WORKFLOW")),
            description=str(data.get("description", "")),
            schema_version=str(data.get("schema_version", "0.1.0")),
            nodes=dict(data.get("nodes", {}) or {}),
        )