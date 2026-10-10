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
    # NEW: carry the mapping so the adapter knows input-slot names without
    # having to thread the mapping object through every call.
    prompt_input_key: str = "text"
    negative_prompt_input_key: str = "text"
    seed_input_key: str = "seed"
    image_input_keys: dict[str, str] = field(default_factory=dict)
    extra_param_input_keys: dict[str, str] = field(default_factory=dict)
    duration_param: str = ""
    start_frame_role: str = "start_frame"

    def image_input_key(self, role: str) -> str:
        return self.image_input_keys.get(role, "image")

    def extra_param_input_key(self, key: str) -> str:
        return self.extra_param_input_keys.get(key, key)


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
        mapping: WorkflowMapping | None = None,
    ) -> GenerationRequest:
        ref_map = dict(references or {})
        req = GenerationRequest(
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
        # Carry mapping-side configuration onto the request so patch_workflow
        # stays self-contained.
        if mapping is not None:
            req.prompt_input_key = mapping.prompt_input_key
            req.negative_prompt_input_key = mapping.negative_prompt_input_key
            req.seed_input_key = mapping.seed_input_key
            req.image_input_keys = dict(mapping.image_input_keys)
            req.extra_param_input_keys = dict(mapping.extra_param_input_keys)
            req.duration_param = mapping.duration_param
            req.start_frame_role = mapping.start_frame_role
        return req

    def patch_workflow(self, request: GenerationRequest) -> GenerationRequest:
        wf = request.workflow
        req = request

        # ---- prompt (slot name is configurable) -----------------------
        self._set_input(
            wf, req.prompt_node_id, req.prompt_input_key, req.shot.prompt
        )
        # ---- negative prompt: skip unless the target is actually
        # different from the positive prompt. Many nodes (e.g.
        # MiniMaxH3ImageToVideo) don't have a separate negative prompt
        # port — if the mapping points neg_prompt at the same node /
        # slot as the positive prompt, writing shot.negative_prompt
        # would clobber the positive prompt we just wrote.
        # Shot authors can still embed negation in shot.prompt itself.
        if (
            req.negative_prompt_node_id != req.prompt_node_id
            or req.negative_prompt_input_key != req.prompt_input_key
        ):
            self._set_input(
                wf,
                req.negative_prompt_node_id,
                req.negative_prompt_input_key,
                req.shot.negative_prompt,
            )

        # ---- seed (slot name is configurable) --------------------------
        seed = (
            req.seed_override
            if req.seed_override is not None
            else req.shot.seed
        )
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        if req.seed_node_id:
            self._set_input(wf, req.seed_node_id, req.seed_input_key, int(seed))

        # ---- image inputs ---------------------------------------------
        # Roles from character_references; slot name is configurable.
        for role, node_id in req.image_input_node_ids.items():
            path = req.character_references.get(role)
            if path:
                self._set_input(wf, node_id, req.image_input_key(role), path)

        # ---- start_frame: auto-wire shot.start_frame → start_frame_role
        # References win (explicit override); fall back to shot.start_frame.
        sf_ref = req.character_references.get(req.start_frame_role)
        if not sf_ref and req.shot.start_frame:
            sf_ref = req.shot.start_frame
        if sf_ref and req.start_frame_role in req.image_input_node_ids:
            self._set_input(
                wf,
                req.image_input_node_ids[req.start_frame_role],
                req.image_input_key(req.start_frame_role),
                sf_ref,
            )

        # ---- duration: auto-wire shot.duration_sec → duration_param node
        if req.duration_param and req.duration_param in req.extra_param_node_ids:
            dur_node_id = req.extra_param_node_ids[req.duration_param]
            dur_key = req.extra_param_input_key(req.duration_param)
            self._set_input(wf, dur_node_id, dur_key, float(req.shot.duration_sec))

        # ---- extra params from shot.workflow_overrides -----------------
        for k, node_id in req.extra_param_node_ids.items():
            # Skip the duration slot — handled above so it's not shadowed
            # by a stale workflow_overrides entry.
            if k == req.duration_param:
                continue
            if k in req.shot.workflow_overrides:
                self._set_input(
                    wf,
                    node_id,
                    req.extra_param_input_key(k),
                    req.shot.workflow_overrides[k],
                )

        req.seed_used = int(seed)
        req.prompt_used = req.shot.prompt
        return req

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
        fname = first.get("filename")
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
        # Use caller-supplied filename for on-disk path; default to the ComfyUI-returned name.
        on_disk_name = filename or fname
        dest_path = dest_dir / on_disk_name
        # Atomic write: download to a temp file first, then rename. This way a
        # crash mid-download never leaves a corrupt half-written mp4 that the
        # runner would mistake for a successful clip on the next run.
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
        tmp_path.write_bytes(resp.content)
        # Sanity check the temp file before swap — refuse to overwrite if the
        # download is empty or suspiciously tiny.
        if tmp_path.stat().st_size < 10_000:
            tmp_path.unlink(missing_ok=True)
            raise GenerationError(
                f"ComfyUI download for {dest_path.name} is suspiciously small "
                f"({tmp_path.stat().st_size if tmp_path.exists() else 0} bytes); refusing to overwrite"
            )
        tmp_path.replace(dest_path)
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
        req = self.prepare_request(shot, resolved, references, seed_override, mapping)
        self.patch_workflow(req)
        prompt_id = self.submit(req)
        entry = self.poll(prompt_id)
        downloader = download_fn or self.fetch_output
        output_path = downloader(entry, resolved.output_node_id, output_dir, filename=f"{shot.shot_id}.mp4")
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