"""Unit tests for the negative_prompt merge into prompt behavior (2026-10-17).

These tests cover the WorkflowMapping field defaults + the adapter's merge
behavior. The five-line check is:

* ``WorkflowMapping().merge_negative_into_prompt`` defaults to False
* The round-trip through ``to_dict`` / ``from_dict`` preserves the field
* When ``merge_negative_into_prompt=True`` and shot.negative_prompt is non-empty,
  the adapter concatenates ``"<prompt>\\n\\n<separator><negative_prompt>"``
* When ``merge_negative_into_prompt=False``, the adapter only writes shot.prompt
  (existing behavior; negative_prompt fall-through unchanged)
* When shot.negative_prompt is empty, the merged and unmerged paths produce
  identical output (no spurious separator artifact)
"""
from __future__ import annotations

import pytest

from video_director.models.workflow import WorkflowMapping
from video_director.workflow.adapter import ComfyUIWorkflowAdapter
from video_director.models.shot import Shot


def _workflow_default_prompt_node_id() -> str:
    """Build a tiny workflow dict with a Prompt node id '31'."""
    return "31"


def _make_workflow_with_prompt_node():
    """Return a workflow dict containing a primitive prompt node (id=31)."""
    return {
        "31": {
            "class_type": "PrimitiveStringMultiline",
            "_meta": {"title": "Prompt"},
            "inputs": {"value": "PLACEHOLDER"},
        }
    }


def test_workflow_mapping_default_is_false():
    """Backward compat: legacy projects without the marker get the old behavior."""
    m = WorkflowMapping()
    assert m.merge_negative_into_prompt is False
    # Default separator still has a usable value even when merging is off.
    assert m.merge_negative_separator == "Do not: "


def test_workflow_mapping_round_trip_preserves_marker():
    """to_dict -> from_dict keeps merge_negative_into_prompt + separator."""
    m = WorkflowMapping(
        merge_negative_into_prompt=True,
        merge_negative_separator="Avoid: ",
    )
    d = m.to_dict()
    assert d["merge_negative_into_prompt"] is True
    assert d["merge_negative_separator"] == "Avoid: "
    m2 = WorkflowMapping.from_dict(d)
    assert m2.merge_negative_into_prompt is True
    assert m2.merge_negative_separator == "Avoid: "


def _make_request(merge_neg: bool, prompt: str = "", negative: str = ""):
    """Build a GenerationRequest with one prompt node and the merge flag wired."""
    from video_director.workflow.adapter import GenerationRequest

    shot = Shot(
        shot_id="test_shot",
        scene_id="test_scene",
        shot_index=1,
        duration_sec=5.0,
        action="",
        emotion="",
        prompt=prompt,
        negative_prompt=negative,
    )
    wf = _make_workflow_with_prompt_node()
    req = GenerationRequest(
        shot=shot,
        workflow=wf,
        prompt_node_id="31",
        negative_prompt_node_id="31",
        seed_node_id=None,
        output_node_id="53",
        image_input_node_ids={},
        extra_param_node_ids={},
        character_references={},
        prompt_input_key="value",
        negative_prompt_input_key="value",
        seed_input_key="noise_seed",
        image_input_keys={},
        extra_param_input_keys={},
        duration_param="",
        frame_count_param="",
        start_frame_role="start_frame",
    )
    req.merge_negative_into_prompt = merge_neg
    req.merge_negative_separator = "Do not: "
    return req


def test_adapter_merges_when_marker_true_and_negative_nonempty():
    adapter = ComfyUIWorkflowAdapter()
    req = _make_request(
        merge_neg=True,
        prompt="A young woman stands near a doorway.",
        negative="blurry, distorted, low quality",
    )
    adapter.patch_workflow(req)
    written = req.workflow["31"]["inputs"]["value"]
    assert "A young woman stands near a doorway." in written
    assert "Do not: blurry, distorted, low quality" in written
    # Negative prompt must appear AFTER the positive prompt with a blank line
    # and a "Do not:" marker in between.
    assert written.index("A young woman stands near a doorway.") < written.index(
        "Do not:"
    )


def test_adapter_skips_merge_when_marker_false():
    adapter = ComfyUIWorkflowAdapter()
    req = _make_request(
        merge_neg=False,
        prompt="A young woman stands near a doorway.",
        negative="blurry, distorted, low quality",
    )
    adapter.patch_workflow(req)
    written = req.workflow["31"]["inputs"]["value"]
    # Without merge, only positive prompt is written to the prompt node.
    assert written == "A young woman stands near a doorway."
    # And the negative prompt is NOT present (it would have clobbered the
    # positive anyway because both nodes are the same; this is the legacy
    # behavior preserved by the adapter's existing guard).
    assert "blurry" not in written


def test_adapter_no_negative_when_marker_true_but_negative_empty():
    """If marker is on but shot has no negative_prompt, behave like a normal write."""
    adapter = ComfyUIWorkflowAdapter()
    req = _make_request(
        merge_neg=True,
        prompt="A young woman stands near a doorway.",
        negative="",
    )
    adapter.patch_workflow(req)
    written = req.workflow["31"]["inputs"]["value"]
    assert written == "A young woman stands near a doorway."
    # The separator must NOT appear when there is nothing to merge after it.
    assert "Do not:" not in written


def test_adapter_merge_with_custom_separator():
    adapter = ComfyUIWorkflowAdapter()
    req = _make_request(
        merge_neg=True,
        prompt="A young woman stands near a doorway.",
        negative="anime style",
    )
    req.merge_negative_separator = "Avoid these things: "
    adapter.patch_workflow(req)
    written = req.workflow["31"]["inputs"]["value"]
    assert "Avoid these things: anime style" in written
