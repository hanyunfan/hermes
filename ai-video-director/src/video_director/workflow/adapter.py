"""ComfyUI Workflow Adapter.

Responsibilities:
  * Resolve the workflow JSON + mapping to concrete node IDs.
  * Patch prompts, negative prompts, seeds, and input images into the workflow.
  * Submit the workflow to a ComfyUI HTTP server.
  * Poll for completion and download the produced video clip.
  * Surface errors as :class:`GenerationError` so the runner can retry.

The adapter only deals with the *workflow JSON*, never with the project
metadata directly. The runner wires it up.
"""

from __future__ import annotations

import copy
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from ..core.errors import GenerationError, WorkflowNotFoundError, ValidationError
from ..models import Shot
from ..models.workflow import WorkflowMapping
from ..utils.logging import get_logger
from .workflow_resolver import ResolvedWorkflow, WorkflowResolver


_LOG = get_logger("video_director.workflow.adapter")


@dataclass
class ComfyUIConfig:
    """Connection settings for a ComfyUI instance."""

    base_url: str = "http://127.0.0.1:8188"
    timeout_sec: float = 30.0
    poll_interval_sec: float = 2.0
    client_id: str = "video-director"


@dataclass
class GenerationRequest:
    """Everything the adapter needs to materialise one workflow patch."""

    shot: Shot
    workflow: dict[str, Any]
    prompt_node_id: str
    negative_prompt_node_id: str
    seed_node_id: str | None
    output_node_id: str
    image_input_node_ids: dict[str, str] = field(default_factory=dict)
    extra_param_node_ids: dict[str, str] = field(default_factory=dict)
    character_references: dict[str, str] = field(default_factory=dict)
    continuity_references: dict[str, str] = field(default_factory=dict)
    seed_override: int | None = None


@dataclass
class GenerationResult:
    """What a backend returns when it succeeds."""

    output_path: Path
    seed_used: int
    prompt_used: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ComfyUIWorkflowAdapter:
    """Adapt a :class:`Shot` into a patched workflow, submit, and poll."""

    def __init__(self, config: ComfyUIConfig | None = None):
        self.config = config or ComfyUIConfig()

    # ---- prepare -----------------------------------------------------

    def prepare_request(
        self,
        shot: Shot,
        resolved: ResolvedWorkflow,
        references: Mapping[str, str] | None = None,
        seed_override: int | None = None,
    ) -> GenerationRequest:
        ref_map = dict(references or {})
        return GenerationRequest(
            shot=shot,
            workflow=copy.deepcopy(resolved.workflow),
            prompt_node_id=resolved.prompt_node_id,
            negative_prompt_node_id=resolved.negative_prompt_node_id,
            seed_node_id=resolved.seed_node_id,
            output_node_id=resolved.output_node_id,
            image_input_node_ids=dict(resolved.image_input_node_ids),
            extra_param_node_ids=dict(resolved.extra_param_node_ids),
            character_references=ref_map,
            seed_override=seed_override,
        )

    def patch_workflow(self, request: GenerationRequest) -> GenerationRequest:
        wf = request.workflow
        self._set_input(wf, request.prompt_node_id, "text", request.shot.prompt)
        self._set_input(
            wf,
            request.negative_prompt_node_id,
            "text",
            request.shot.negative_prompt,
        )
        seed = request.seed_override if request.seed_override is not None else request.shot.seed
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        if request.seed_node_id:
            self._set_input(wf, request.seed_node_id, "seed", int(seed))
        # Image inputs: each role's image path goes into the configured node.
        for role, node_id in request.image_input_node_ids.items():
            path = request.character_references.get(role)
            if path:
                self._set_input(wf, node_id, "image", path)
        # Continuity start frame as a fallback role
        start_frame = request.character_references.get("start_frame")
        if start_frame and "start_frame" in request.image_input_node_ids:
            self._set_input(
                wf,
                request.image_input_node_ids["start_frame"],
                "image",
                start_frame,
            )
        # Extra params (size, steps, cfg, ...) come from shot.workflow_overrides.
        for k, node_id in request.extra_param_node_ids.items():
            if k in request.shot.workflow_overrides:
                self._set_input(wf, node_id, k, request.shot.workflow_overrides[k])
        request.seed_used = int(seed)
        request.prompt_used = request.shot.prompt
        return request

    # ---- submit + poll ----------------------------------------------

    def submit(self, request: GenerationRequest) -> str:
        """POST the workflow and return the ComfyUI prompt_id."""
        url = f"{self.config.base_url.rstrip('/')}/prompt"
        body = {
            "prompt": request.workflow,
            "client_id": self.config.client_id,
        }
        try:
            resp = requests.post(url, json=body, timeout=self.config.timeout_sec)
        except requests.RequestException as e:
            raise GenerationError(f"ComfyUI submit failed: {e}") from e
        if resp.status_code >= 400:
            raise GenerationError(
                f"ComfyUI submit returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise GenerationError(f"ComfyUI submit returned non-JSON: {e}") from e
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise GenerationError(f"ComfyUI submit response missing prompt_id: {data}")
        return str(prompt_id)

    def poll(self, prompt_id: str) -> dict[str, Any]:
        """Poll the history endpoint until the job completes or fails.

        Returns the history entry on success. Raises :class:`GenerationError`
        on failure. ComfyUI exposes execution errors in the ``outputs`` dict
        or via WebSocket ``execution_error`` messages; we read the history.
        """
        url = f"{self.config.base_url.rstrip('/')}/history/{prompt_id}"
        deadline = time.monotonic() + self.config.timeout_sec * 60  # reuse timeout as poll budget * 60
        while time.monotonic() < deadline:
            try:
                resp = requests.get(url, timeout=self.config.timeout_sec)
            except requests.RequestException as e:
                _LOG.warning("poll failed: %s", e)
                time.sleep(self.config.poll_interval_sec)
                continue
            if resp.status_code == 200:
                data = resp.json()
                entry = data.get(prompt_id)
                if entry:
                    if entry.get("status", {}).get("completed"):
                        return entry
                    err = entry.get("status", {}).get("messages") or []
                    for msg in err:
                        if isinstance(msg, list) and msg and msg[0] == "execution_error":
                            raise GenerationError(f"ComfyUI execution_error: {msg[1]}")
                    # not done yet
            time.sleep(self.config.poll_interval_sec)
        raise GenerationError(f"ComfyUI job {prompt_id} did not complete within timeout")

    # ---- result download --------------------------------------------

    def fetch_output(
        self,
        history_entry: Mapping[str, Any],
        output_node_id: str,
        dest_dir: Path,
        filename: str | None = None,
    ) -> Path:
        outputs = history_entry.get("outputs", {})
        node_output = outputs.get(output_node_id) or outputs.get(str(output_node_id))
        if not node_output:
            raise GenerationError(
                f"ComfyUI history missing output for node {output_node_id}; "
                f"got nodes: {list(outputs)}"
            )
        # ComfyUI typically returns {'videos': [{'filename': ..., 'subfolder': ..., 'type': ...}]}
        # or {'images': [...]} depending on the workflow. Handle both.
        media = (
            node_output.get("videos")
            or node_output.get("images")
            or node_output.get("gifs")
            or []
        )
        if not media:
            raise GenerationError(
                f"ComfyUI node {output_node_id} returned no media: {node_output}"
            )
        first = media[0]
        fname = filename or first.get("filename")
        subfolder = first.get("subfolder", "")
        kind = first.get("type", "output")
        if not fname:
            raise GenerationError(f"ComfyUI media entry missing filename: {first}")
        # ComfyUI typically serves these under /view?filename=&subfolder=&type=
        view_url = f"{self.config.base_url.rstrip('/')}/view"
        params = {"filename": fname, "subfolder": subfolder, "type": kind}
        try:
            resp = requests.get(view_url, params=params, timeout=self.config.timeout_sec)
        except requests.RequestException as e:
            raise GenerationError(f"ComfyUI view fetch failed: {e}") from e
        if resp.status_code >= 400:
            raise GenerationError(
                f"ComfyUI view returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / fname
        dest_path.write_bytes(resp.content)
        return dest_path

    # ---- top-level helper -------------------------------------------

    def generate_clip(
        self,
        shot: Shot,
        paths,
        mapping: WorkflowMapping,
        output_dir: Path,
        references: Mapping[str, str] | None = None,
        seed_override: int | None = None,
        download_fn: Callable[[str, dict, str, Path], Path] | None = None,
    ) -> GenerationResult:
        """End-to-end: resolve workflow → patch → submit → poll → download.

        ``download_fn`` is optional; if provided, it overrides the default
        :meth:`fetch_output` for testing.
        """
        resolver = WorkflowResolver(paths, mapping)
        resolved = resolver.resolve()
        req = self.prepare_request(shot, resolved, references, seed_override)
        self.patch_workflow(req)
        prompt_id = self.submit(req)
        entry = self.poll(prompt_id)
        downloader = download_fn or self.fetch_output
        output_path = downloader(prompt_id, dict(entry), resolved.output_node_id, output_dir)
        return GenerationResult(
            output_path=output_path,
            seed_used=req.seed_used or 0,
            prompt_used=req.prompt_used,
            metadata={"prompt_id": prompt_id, "history_keys": list(entry.keys())},
        )

    # ---- helpers ----------------------------------------------------

    @staticmethod
    def _set_input(workflow: dict[str, Any], node_id: str, key: str, value: Any) -> None:
        node = ComfyUIWorkflowAdapter._node_lookup(workflow, node_id)
        if node is None:
            raise GenerationError(f"workflow has no node with id={node_id}")
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            raise GenerationError(f"node {node_id} inputs is not a mapping")
        inputs[key] = value

    @staticmethod
    def _node_lookup(workflow: dict[str, Any], node_id: str) -> dict[str, Any] | None:
        """Locate a node by id in either API or UI format.

        API: ``{"1": {"class_type": ..., "inputs": ...}}``
        UI:  ``{"nodes": [{"id": 1, ...}], ...}``
        """
        if node_id in workflow and isinstance(workflow[node_id], dict):
            return workflow[node_id]
        for n in workflow.get("nodes", []) or []:
            if isinstance(n, dict) and str(n.get("id")) == str(node_id):
                return n
        return None