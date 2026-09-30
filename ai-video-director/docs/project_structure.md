# Project structure

Reference for every file and directory under `projects/<story_id>/`.

## `project.yaml`

Top-level project metadata. Edited by `video-director init` and the user.

```yaml
project_id: my_story
title: My Story
description: ...
language: en
target_duration_sec: 600
status: draft                  # draft | ready | generating | assembled | archived
story_path: story.yaml
characters_dir: characters
scenes_dir: scenes
shots_dir: shots
references_dir: references
output_dir: output
state_dir: state
workflow_config: workflow.yaml
```

## `story.yaml`

The screenplay, in a structured form. Each `script` entry is a
`ScriptSection`:

```yaml
script:
  - section_id: intro
    title: Opening
    summary: short
    body: full prose (used by analyzer)
    characters: [alice, bob]
    location: cafe
    notes: ""
```

The story analyzer reads this and produces `state/story_bible.json`.

## `workflow.yaml`

The **node title mapping** for your ComfyUI workflow. See `docs/comfyui.md`.

```yaml
workflow_name: my_workflow
workflow_path: video_workflow.json    # relative to private/
prompt_node: PositivePrompt
negative_prompt_node: NegativePrompt
seed_node: KSampler
output_node: VHS_VideoCombine
image_input_nodes:
  hero: LoadImageHero
  face: LoadImageFace
extra_param_nodes:
  steps: KSampler
```

## `characters/`

One YAML per character. Filename `<character_id>.yaml`.

```yaml
character_id: alice
name: Alice
description: ...
age: 30
gender: f
appearance: <single paragraph, the continuity bible>
hair: short dark
face: round, brown eyes
body: slim, average height
clothing_default: blue dress
clothing_variants: [red dress, winter coat]
personality: curious
reference_images:
  - role: hero
    path: alice/hero.png
  - role: face
    path: alice/face.png
continuity_rules:
  - Hair and outfit must remain stable unless the script overrides.
```

**`appearance` is the single source of truth.** The ContinuityManager
doesn't run a vision model — it relies on the prose you've written
here. Make it specific.

## `scenes/`

One YAML per scene. Populated by `video-director storyboard`, then
hand-edited.

```yaml
scene_id: scene_001
title: Opening
location: cafe
time: morning
characters: [alice]
description: ...
duration_sec: 60
style: cinematic
continuity_requirements:
  - Lighting matches every shot in the scene.
```

## `shots/`

One YAML per shot. Populated by `video-director storyboard`, then
hand-edited for prompts, action, emotion.

```yaml
shot_id: scene_001_shot_001
scene_id: scene_001
shot_index: 1
duration_sec: 5
shot_type: medium
camera: 50mm eye-level
camera_motion: static
characters: [alice]
action: Alice enters the cafe.
emotion: curious
environment: small cafe, morning light
lighting: warm key from window
prompt: A medium shot of Alice entering a small cafe...
negative_prompt: blurry, deformed
seed: 12345
reference_images: [alice/hero.png]
workflow_overrides: {}
status: pending
output_clip: ""
```

## `references/` — gitignored

Character and scene reference images. Layout:

```
references/
├── alice/
│   ├── hero.png        # full-body / primary
│   ├── face.png        # close-up face
│   └── costume_01.png  # optional variant
└── bob/
    └── hero.png
```

The runner reads `characters/<id>.yaml → reference_images[].path` and
hands those paths to the backend. ComfyUI's standard `LoadImage`
resolves them relative to its own `input/` directory, so make sure the
images live there too.

## `private/` — gitignored

Where **your real workflow JSON** goes. `private/video_workflow.json`
is the default path referenced from `workflow.yaml`. Add any other
private notes / configs here.

## `output/` — gitignored

```
output/
├── clips/<shot_id>.mp4     # raw generated clips
├── intermediate/           # stage outputs (transitions, etc.)
├── final/final.mp4         # final assembled video
└── logs/                   # run logs
```

## `state/` — gitignored

```
state/
├── generation_state.json   # top-level run state + counters
├── story_bible.json        # from `video-director analyze`
├── last_run_summary.json   # from `video-director generate`
├── assembly_manifest.json  # from `video-director assemble`
├── jobs/<job_id>.json      # one per generation attempt
├── clips/<shot_id>.json    # one per successful clip
└── qa/<shot_id>.json       # QA verdicts
```

All auto-generated. If state gets corrupted, `retry --reset-all`
rebuilds it from the shot files on disk.
