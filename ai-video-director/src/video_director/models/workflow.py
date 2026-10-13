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

    ``input_keys`` decouple the *node identity* (which ComfyUI node to
    target) from the *input slot name* (which input port on that node to
    write into). Different nodes name the same conceptual field
    differently:

      * ``CLIPTextEncode`` calls it ``text``
      * ``MiniMaxH3ImageToVideo`` calls it ``prompt``
      * ``PrimitiveFloat`` calls it ``value``
      * ``KSampler`` calls it ``seed``
      * ``LoadImage`` calls it ``image``
      * ``RandomNoise`` calls it ``noise_seed``

    Defaults match the legacy ``CLIPTextEncode`` / ``KSampler`` / ``LoadImage``
    pair so old mappings keep working without edits.
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
    # NEW (2026-10-12, ref2v): ordered slot_key -> node_title, where
    # slot_key is "ref_image_0", "ref_image_1", ... The adapter routes
    # each entry of ``reference_images_ordered`` (provided by the runner)
    # into the matching node's image slot. Used by MiniMax-H3
    # MiniMaxH3ReferenceToVideo workflow where each ref image is a
    # separate LoadImage node wired into the ref2v node's
    # ``ref_images.ref_image_<i>`` input.
    reference_image_nodes: dict[str, str] = field(default_factory=dict)

    # ---- input-slot names (NEW) --------------------------------------
    prompt_input_key: str = "text"
    negative_prompt_input_key: str = "text"
    seed_input_key: str = "seed"
    image_input_keys: dict[str, str] = field(default_factory=dict)
    # role -> input slot name on the image node (default: "image")
    extra_param_input_keys: dict[str, str] = field(default_factory=dict)
    # param key -> input slot name on the param node (default: same key)
    # Special: when ``duration_param`` is set, ``shot.duration_sec`` is
    # auto-written into that node's slot, no per-shot override needed.
    duration_param: str = ""
    # NEW (2026-10-12, ref2v): when set, the adapter writes a derived
    # INT frame count (= 24 * duration_sec, snapped to a 17-multiple)
    # into this node's slot. Used by MiniMaxH3ReferenceToVideo where
    # `length` is INT and we can't pass seconds directly.
    frame_count_param: str = ""
    start_frame_role: str = "start_frame"
    # which role the adapter should pull ``shot.start_frame`` from
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
        nodes.extend(self.reference_image_nodes.values())
        return [n for n in nodes if n]

    def image_input_key(self, role: str) -> str:
        return self.image_input_keys.get(role, "image")

    def extra_param_input_key(self, key: str) -> str:
        return self.extra_param_input_keys.get(key, key)

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
            "reference_image_nodes": dict(self.reference_image_nodes),
            "prompt_input_key": self.prompt_input_key,
            "negative_prompt_input_key": self.negative_prompt_input_key,
            "seed_input_key": self.seed_input_key,
            "image_input_keys": dict(self.image_input_keys),
            "extra_param_input_keys": dict(self.extra_param_input_keys),
            "duration_param": self.duration_param,
            "frame_count_param": self.frame_count_param,
            "start_frame_role": self.start_frame_role,
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
            reference_image_nodes=dict(data.get("reference_image_nodes", {}) or {}),
            prompt_input_key=str(data.get("prompt_input_key", "text")),
            negative_prompt_input_key=str(
                data.get("negative_prompt_input_key", "text")
            ),
            seed_input_key=str(data.get("seed_input_key", "seed")),
            image_input_keys=dict(data.get("image_input_keys", {}) or {}),
            extra_param_input_keys=dict(
                data.get("extra_param_input_keys", {}) or {}
            ),
            duration_param=str(data.get("duration_param", "")),
            frame_count_param=str(data.get("frame_count_param", "")),
            start_frame_role=str(data.get("start_frame_role", "start_frame")),
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