"""YAML + JSON fixture strings for tests. Real data must NEVER appear here."""

from __future__ import annotations

PROJECT_YAML = """\
project_id: test_story
title: Test Story
description: A test project.
language: en
target_duration_sec: 60
status: draft
"""

STORY_YAML = """\
story_id: test_story
title: Test Story
story_summary: A two-character test.
genre: test
style: cinematic
tone: neutral
target_duration_sec: 60
language: en
script:
  - section_id: s1
    title: Opening
    summary: First scene.
    body: The protagonist enters the room.
    characters: [alice]
    location: room
  - section_id: s2
    title: Middle
    summary: Second scene.
    body: The protagonist meets a friend.
    characters: [alice, bob]
    location: room
"""

CHARACTER_YAML = """\
character_id: alice
name: Alice
description: Test character A.
age: 30
gender: f
appearance: short dark hair, brown eyes, slim build
hair: short dark
face: round face
body: slim
clothing_default: blue dress
personality: curious
reference_images:
  - role: hero
    path: alice/hero.png
    notes: ""
continuity_rules:
  - Always blue dress unless changed.
"""

CHARACTER_B_YAML = """\
character_id: bob
name: Bob
description: Test character B.
age: 32
gender: m
appearance: tall, glasses, beard
hair: short brown
face: square face
body: tall
clothing_default: grey suit
personality: thoughtful
reference_images:
  - role: hero
    path: bob/hero.png
    notes: ""
continuity_rules: []
"""

SHOT_YAML = """\
shot_id: test_shot_001
scene_id: scene_001
shot_index: 1
duration_sec: 0.5
shot_type: medium
camera: 50mm
camera_motion: static
characters: [alice]
action: Alice enters the room.
emotion: neutral
environment: simple room
lighting: soft
prompt: A test shot of alice in a room.
negative_prompt: blurry
seed: 42
reference_images: [alice/hero.png]
workflow_overrides: {}
status: pending
output_clip: ""
"""

WORKFLOW_MAPPING_YAML = """\
workflow_name: test_workflow
workflow_path: video_workflow.json
prompt_node: PositivePrompt
negative_prompt_node: NegativePrompt
seed_node: KSampler
output_node: VHS_VideoCombine
image_input_nodes:
  hero: LoadImageHero
extra_param_nodes:
  steps: KSamplerSteps
notes: test mapping
"""

WORKFLOW_UI_FORMAT = """\
{
  "last_node_id": 5,
  "last_link_id": 0,
  "nodes": [
    {"id": 1, "type": "CLIPTextEncode", "title": "PositivePrompt", "inputs": {"text": ""}},
    {"id": 2, "type": "CLIPTextEncode", "title": "NegativePrompt", "inputs": {"text": ""}},
    {"id": 3, "type": "KSampler", "title": "KSampler", "inputs": {"seed": 0, "steps": 20}},
    {"id": 4, "type": "LoadImage", "title": "LoadImageHero", "inputs": {"image": ""}},
    {"id": 5, "type": "VHS_VideoCombine", "title": "VHS_VideoCombine", "inputs": {}}
  ],
  "links": []
}
"""

WORKFLOW_API_FORMAT = """\
{
  "1": {"class_type": "CLIPTextEncode", "_meta": {"title": "PositivePrompt"}, "inputs": {"text": ""}},
  "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "NegativePrompt"}, "inputs": {"text": ""}},
  "3": {"class_type": "KSampler", "_meta": {"title": "KSampler"}, "inputs": {"seed": 0}},
  "4": {"class_type": "LoadImage", "_meta": {"title": "LoadImageHero"}, "inputs": {"image": ""}},
  "5": {"class_type": "VHS_VideoCombine", "_meta": {"title": "VHS_VideoCombine"}, "inputs": {}}
}
"""
