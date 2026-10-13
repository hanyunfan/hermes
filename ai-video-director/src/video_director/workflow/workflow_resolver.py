"""Locate + load the user-supplied ComfyUI workflow JSON.

The user stores their real workflow under ``<project>/private/``. We never
read or write to anything inside ``projects/template/`` or ``workflows/``
because that would pull real data into the public framework.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import WorkflowNotFoundError, ValidationError
from ..core.paths import ProjectPaths
from ..models.workflow import WorkflowMapping
from ..utils.logging import get_logger


_LOG = get_logger("video_director.workflow.resolver")


@dataclass
class ResolvedWorkflow:
    """A workflow JSON with the user's node IDs already resolved."""

    workflow: dict[str, Any]
    prompt_node_id: str
    negative_prompt_node_id: str
    seed_node_id: str | None
    output_node_id: str
    image_input_node_ids: dict[str, str]
    extra_param_node_ids: dict[str, str]
    # NEW (2026-10-12, ref2v): ordered slot_key ("ref_image_0"...) → node_id.
    reference_image_node_ids: dict[str, str] = field(default_factory=dict)


class WorkflowResolver:
    """Read workflow JSON + mapping, resolve ``title`` → numeric node IDs."""

    def __init__(self, paths: ProjectPaths, mapping: WorkflowMapping):
        self.paths = paths
        self.mapping = mapping

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "WorkflowResolver":
        from ..core.project_manager import ProjectManager  # local to avoid cycles
        pm = ProjectManager(paths.root.parent.parent if False else Path("/"))
        # Easier: load the mapping directly
        from ..utils.io import read_yaml
        if not paths.workflow_mapping_file.exists():
            mapping = WorkflowMapping()
        else:
            raw = read_yaml(paths.workflow_mapping_file) or {}
            mapping = WorkflowMapping.from_dict(raw)
        return cls(paths, mapping)

    def resolve(self) -> ResolvedWorkflow:
        workflow_path = self._resolve_workflow_path()
        if not workflow_path.exists():
            raise WorkflowNotFoundError(
                f"workflow JSON not found: {workflow_path}. "
                f"Drop your real ComfyUI workflow into the project's private/ "
                f"directory and update workflow.yaml (see docs/comfyui.md)."
            )
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValidationError(f"workflow JSON is malformed: {e}") from e
        if not isinstance(workflow, dict):
            raise ValidationError("workflow JSON must be an object at top level")
        title_to_id = self._build_title_index(workflow)
        prompt_id = self._lookup(title_to_id, self.mapping.prompt_node, "prompt_node")
        neg_id = self._lookup(title_to_id, self.mapping.negative_prompt_node, "negative_prompt_node")
        seed_id = (
            self._lookup(title_to_id, self.mapping.seed_node, "seed_node")
            if self.mapping.seed_node
            else None
        )
        output_id = self._lookup(title_to_id, self.mapping.output_node, "output_node")
        img_ids = {
            role: self._lookup(title_to_id, title_, f"image_input_nodes[{role!r}]")
            for role, title_ in self.mapping.image_input_nodes.items()
        }
        extra_ids = {
            k: self._lookup(title_to_id, v, f"extra_param_nodes[{k!r}]")
            for k, v in self.mapping.extra_param_nodes.items()
        }
        # NEW (2026-10-12, ref2v): each ref_image_N slot maps to a LoadImage
        # node in the workflow. The runner feeds an ordered list of ref
        # images (face, full, side, ...); the adapter routes entry i into
        # the node whose title is mapping.reference_image_nodes[f"ref_image_{i}"].
        ref_ids: dict[str, str] = {}
        for slot_key, title_ in (self.mapping.reference_image_nodes or {}).items():
            try:
                ref_ids[slot_key] = self._lookup(title_to_id, title_, f"reference_image_nodes[{slot_key!r}]")
            except ValidationError as e:
                # Workflow doesn't have this slot's node — that's fine, the
                # adapter stops routing at the first missing slot. Log and skip.
                _LOG.warning("skipping ref slot %s: %s", slot_key, e)
        return ResolvedWorkflow(
            workflow=workflow,
            prompt_node_id=prompt_id,
            negative_prompt_node_id=neg_id,
            seed_node_id=seed_id,
            output_node_id=output_id,
            image_input_node_ids=img_ids,
            extra_param_node_ids=extra_ids,
            reference_image_node_ids=ref_ids,
        )

    # ---- helpers -----------------------------------------------------

    def _resolve_workflow_path(self) -> Path:
        wf_path = self.mapping.workflow_path.strip()
        if not wf_path:
            # Default lookup under private/
            return self.paths.private_dir / "video_workflow.json"
        candidate = (self.paths.private_dir / wf_path).resolve()
        # Security: refuse to escape the project's private/ directory.
        try:
            candidate.relative_to(self.paths.private_dir.resolve())
        except ValueError as e:
            raise ValidationError(
                f"workflow_path {wf_path!r} escapes the project's private/ directory"
            ) from e
        return candidate

    @staticmethod
    def _build_title_index(workflow: Mapping[str, Any]) -> dict[str, str]:
        """Map ``node_title`` → numeric ``node_id`` for ComfyUI's UI-format.

        ComfyUI stores the workflow under one of:
          * API format: ``{"node_id": {"class_type": ..., "inputs": ...}}``
          * UI export: ``{"nodes": [{"id": ..., "title": "...", ...}], ...}``

        API-format node IDs can be either pure digits (``"42"``) or contain
        a colon (``"105:11"`` for a node inside a subgraph). We treat any
        top-level value that looks like a node payload — dict with
        ``class_type`` or ``_meta`` — as API format.

        We normalise both into the title index.
        """
        title_to_id: dict[str, str] = {}
        # API format detection: top-level keys are node IDs (digit-only or
        # subgraph-qualified like "105:11"), and values are node payloads.
        if workflow and all(
            isinstance(v, dict) and ("class_type" in v or "_meta" in v)
            for v in workflow.values()
        ):
            for node_id, payload in workflow.items():
                if not isinstance(payload, dict):
                    continue
                meta = payload.get("_meta")
                title = (
                    meta.get("title")
                    if isinstance(meta, dict)
                    else None
                )
                if title:
                    title_to_id[str(title)] = str(node_id)
            return title_to_id
        # UI format
        nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            title = node.get("title") or node.get("properties", {}).get("title")
            if nid is not None and title:
                title_to_id[str(title)] = str(nid)
        return title_to_id

    @staticmethod
    def _lookup(index: dict[str, str], title: str, label: str) -> str:
        if not title:
            raise ValidationError(f"workflow mapping missing required node: {label}")
        if title not in index:
            raise ValidationError(
                f"workflow mapping references {label}={title!r} but no node "
                f"with that title exists. Available: {sorted(index)}"
            )
        return index[title]