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
    # NEW (2026-10-13): independent poll budget. Previously poll()
    # multiplied timeout_sec by 60, which only gave 30 minutes of
    # total polling per shot — enough for cold start, but
    # insufficient for shots running after VRAM has fragmented over
    # many prior shots (we observed 30-40 min renders by shot 7+
    # because unet/CLIP caches accumulate). The new default of 90
    # minutes is generous; the actual cap is the user's GPU / wall
    # clock patience. Set explicitly via ComfyUIConfig to override.
    poll_timeout_sec: float = 90.0 * 60.0
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
    # NEW (2026-10-12, ref2v): ordered list of reference image dicts that
    # patch_workflow routes into ``ref_image_node_ids`` slots.
    # Each entry: {"basename": str, "image_type": str, "weight": float,
    #              "character_id": str, "role": str}
    # NEW (2026-10-12, ref2v): when set, the adapter writes a derived
    # INT frame count (= 24 * duration_sec, snapped to a 17-multiple)
    # into this node's slot. Used by MiniMaxH3ReferenceToVideo where
    # `length` is INT and we can't pass seconds directly.
    frame_count_param: str = ""
    reference_images_ordered: list[dict[str, Any]] = field(default_factory=list)
    # NEW (2026-10-12, ref2v): slot_key -> node_id, e.g.
    # {"ref_image_0": "10", "ref_image_1": "11", ...}. The mapping object
    # is parsed from workflow.yaml:reference_image_nodes.
    reference_image_node_ids: dict[str, str] = field(default_factory=dict)
    # NEW (2026-10-12, prev-shot chain): same shape for video refs. The
    # runner fills ``reference_videos_ordered`` with one entry per
    # ``ref_video_<i>`` slot, e.g.
    # [{"basename": "shot_001.mp4", "role": "previous_shot"}]. The
    # adapter routes each into the matching node's image slot. The node
    # is wired into MiniMaxH3ReferenceToVideo's ref_videos.ref_video_<i>
    # input, which ComfyUI's LoadImage handles via pyav
    # (InputImpl.VideoFromFile).
    reference_videos_ordered: list[dict[str, Any]] = field(default_factory=list)
    reference_video_node_ids: dict[str, str] = field(default_factory=dict)

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
        reference_images_ordered: list[dict[str, Any]] | None = None,
        reference_videos_ordered: list[dict[str, Any]] | None = None,
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
            req.frame_count_param = mapping.frame_count_param
            req.start_frame_role = mapping.start_frame_role
        # Carry multi-reference image routing (ref2v).
        if reference_images_ordered is not None:
            req.reference_images_ordered = list(reference_images_ordered)
        if mapping is not None and getattr(mapping, "reference_image_nodes", None):
            req.reference_image_node_ids = dict(mapping.reference_image_nodes)
        # If the resolver already mapped slot_key → node_id, prefer those
        # (they have the *numeric* node IDs, which the adapter needs to
        # patch the right node; the mapping object only carries titles).
        if getattr(resolved, "reference_image_node_ids", None):
            req.reference_image_node_ids = dict(resolved.reference_image_node_ids)
        # NEW (2026-10-12, prev-shot chain): same propagation for video refs.
        if reference_videos_ordered is not None:
            req.reference_videos_ordered = list(reference_videos_ordered)
        if mapping is not None and getattr(mapping, "reference_video_nodes", None):
            req.reference_video_node_ids = dict(mapping.reference_video_nodes)
        if getattr(resolved, "reference_video_node_ids", None):
            req.reference_video_node_ids = dict(resolved.reference_video_node_ids)
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

        # ---- multi-reference image routing (ref2v / MultiIPAdapter) ---
        # When the workflow exposes a `reference_image_nodes` map (e.g.
        # ``ref_image_0: "Load Image (Ref 0)"`` for the MiniMax-H3
        # MiniMaxH3ReferenceToVideo workflow), the adapter patches each
        # list entry in `req.reference_images_ordered` into the matching
        # node's image slot. This is the new multi-character / multi-type
        # (face/full/side/back/costume) ref2v path that supersedes the
        # single-image `start_frame` path.
        ordered_refs = getattr(req, "reference_images_ordered", None) or []
        ref_node_map = getattr(req, "reference_image_node_ids", {}) or {}
        for idx, ref in enumerate(ordered_refs):
            slot_key = f"ref_image_{idx}"
            node_id = ref_node_map.get(slot_key)
            if not node_id:
                # workflow doesn't accept this many refs — stop silently.
                break
            self._set_input(wf, node_id, "image", ref["basename"])

        # ---- multi-reference VIDEO routing (prev-shot chain) ---------
        # When the workflow exposes a `reference_video_nodes` map
        # (e.g. ``ref_video_0: "Load Video Ref (previous shot)"``), the
        # adapter uploads each previous-shot mp4 to ComfyUI's input
        # dir and patches the resulting basename into the matching
        # node's image slot. The node is wired into
        # MiniMaxH3ReferenceToVideo's ref_videos.ref_video_<i>, which
        # ComfyUI's LoadImage loads via pyav
        # (InputImpl.VideoFromFile -> IMAGE batch of all frames).
        ordered_videos = getattr(req, "reference_videos_ordered", None) or []
        ref_video_node_map = getattr(req, "reference_video_node_ids", {}) or {}
        for idx, vref in enumerate(ordered_videos):
            slot_key = f"ref_video_{idx}"
            node_id = ref_video_node_map.get(slot_key)
            if not node_id:
                break
            basename = vref.get("basename")
            if basename:
                self._set_input(wf, node_id, "image", basename)

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

        # ---- frame_count: auto-wire derived int frame count → ref2v node
        # The ref2v node's `length` slot takes INT (frame count at 24 fps),
        # not seconds. The runner passes a string param key (e.g. "frame_count")
        # via mapping.frame_count_param; we compute the int here and patch
        # the matching PrimitiveInt node's `value` input.
        frame_count_param = getattr(req, "frame_count_param", "") or ""
        if frame_count_param and frame_count_param in req.extra_param_node_ids:
            fc_node_id = req.extra_param_node_ids[frame_count_param]
            fc_key = req.extra_param_input_key(frame_count_param)
            # 24 fps × duration, rounded to the nearest 17-multiple (H3
            # training constraint, per the node's `step: 17` widget).
            n = int(round(float(req.shot.duration_sec) * 24))
            n = max(5, n)  # node's `min: 5`
            # snap up to next 17-multiple
            if n % 17 != 5:
                n += (17 - (n % 17)) % 17
            self._set_input(wf, fc_node_id, fc_key, int(n))
        elif "frame_count" in (req.extra_param_node_ids or {}):
            # Always allow mapping with bare "frame_count" key without
            # needing frame_count_param; works the same way.
            fc_node_id = req.extra_param_node_ids["frame_count"]
            fc_key = req.extra_param_input_key("frame_count")
            n = int(round(float(req.shot.duration_sec) * 24))
            n = max(5, n)
            if n % 17 != 5:
                n += (17 - (n % 17)) % 17
            self._set_input(wf, fc_node_id, fc_key, int(n))

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
        """POST the workflow and return the ComfyUI prompt_id.

        Before submitting, calls ComfyUI's ``/free`` endpoint to unload
        any in-memory models and free caches. Without this, unet/CLIP
        state fragments across successive shots and renders slow from
        ~5 min (cold) to ~40 min (after 10+ shots on a single GPU).
        The /free call is best-effort: a failure here is logged and
        ignored because the new prompt itself will trigger ComfyUI's
        internal model_management.
        """
        # Free VRAM before submitting the new prompt.
        free_url = f"{self.config.base_url.rstrip('/')}/free"
        try:
            requests.post(
                free_url,
                json={"unload_models": True, "free_memory": True},
                timeout=self.config.timeout_sec,
            )
        except requests.RequestException as e:
            _LOG.warning("ComfyUI /free pre-submit failed: %s", e)

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

        Polling budget is governed by ``config.poll_timeout_sec`` (default
        90 minutes, was previously derived from ``config.timeout_sec * 60``).
        The 30-minute default was too tight: we measured render times
        climbing from ~5 min to ~40 min as the unet/CLIP caches
        fragmented across successive shots on a single GPU. 90 min
        leaves headroom for the worst case while still failing fast
        on a hung job.
        """
        url = f"{self.config.base_url.rstrip('/')}/history/{prompt_id}"
        deadline = time.monotonic() + self.config.poll_timeout_sec
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
        reference_images_ordered: list[dict[str, Any]] | None = None,
        reference_videos_ordered: list[dict[str, Any]] | None = None,
    ) -> GenerationResult:
        """End-to-end: resolve workflow → patch → submit → poll → download.

        ``download_fn`` is optional; if provided, it overrides the default
        :meth:`fetch_output` for testing.

        ``reference_images_ordered`` is the new (2026-10-12) ref2v path:
        when the workflow exposes ``reference_image_nodes`` (slot_key →
        node title), the adapter routes each list entry into the matching
        node's image slot. For backwards compatibility, when this is None
        the legacy single-LoadImage path is used.

        ``reference_videos_ordered`` is the 2026-10-12 prev-shot chain:
        the runner fills it with the previous shot's uploaded mp4
        basename(s), and the adapter routes each into the matching
        ``ref_video_<i>`` node wired to MiniMaxH3ReferenceToVideo's
        ref_videos slot. ComfyUI's LoadImage decodes the mp4 to an
        IMAGE batch via pyav.
        """
        resolver = WorkflowResolver(paths, mapping)
        resolved = resolver.resolve()
        req = self.prepare_request(
            shot,
            resolved,
            references,
            seed_override,
            mapping,
            reference_images_ordered=reference_images_ordered,
            reference_videos_ordered=reference_videos_ordered,
        )
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