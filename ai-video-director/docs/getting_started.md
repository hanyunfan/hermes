# Getting started

A 10-minute walkthrough from `pip install` to a final video.

## 0. Prerequisites

- Python 3.10+
- FFmpeg in `$PATH` (`ffmpeg -version` should work)
- A ComfyUI server reachable at `http://127.0.0.1:8188` (or any URL you
  configure — see `config/comfyui.example.yaml`). If you don't have one,
  skip steps 4–5 and use `--backend mock` for the rest.

## 1. Install

```bash
git clone <this-repo>
cd ai-video-director
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Smoke test:

```bash
video-director --help
pytest tests/ -q
```

## 2. Create a project

```bash
video-director init my_first_story --title "My First Story" --duration 600
```

This copies `projects/template/` into `projects/my_first_story/`. Inspect:

```bash
tree projects/my_first_story -L 2
```

```
projects/my_first_story/
├── project.yaml
├── story.yaml             ← edit me
├── workflow.yaml          ← edit me
├── characters/            ← drop character references here
│   └── example_character_a.yaml
├── scenes/                ← populated by `storyboard`
├── shots/                 ← populated by `storyboard`
├── references/            ← gitignored, drop images here
├── private/               ← gitignored, drop your workflow here
├── output/                ← gitignored, generated clips land here
└── state/                 ← gitignored, checkpoints land here
```

## 3. Write the story

`story.yaml`:

```yaml
story_id: my_first_story
title: My First Story
story_summary: A short example.
target_duration_sec: 600
script:
  - section_id: intro
    title: Opening
    body: The protagonist walks into a quiet room.
    characters: [alice]
    location: room
  - section_id: middle
    title: Middle
    body: A friend joins them.
    characters: [alice, bob]
    location: room
```

## 4. Drop in character references

For each character in your `characters/*.yaml`, put reference images at
`references/<character_id>/hero.png` (and optionally `face.png`,
`costume_01.png`, …).

The runner reads these paths and hands them to the backend. ComfyUI
loads them via `LoadImage` nodes; you map which node corresponds to
which role in `workflow.yaml`.

## 5. Wire up your ComfyUI workflow

This is the only tricky step. See `docs/comfyui.md` for details. Quick
version:

1. In ComfyUI, design your video workflow.
2. **File → Export → API** (recommended) — saves `workflow_api.json`.
3. Save it as `projects/my_first_story/private/video_workflow.json`.
4. Open the JSON; for each node you want to control, note its
   `_meta.title` field.
5. Edit `projects/my_first_story/workflow.yaml` to map titles → roles.

If you don't have ComfyUI yet, use `--backend mock` for now.

## 6. Break down the story

The framework offers two paths:

### Recommended: LLM-driven via Hermes

Ask Hermes (with the `video-director` skill loaded) to do this for you:

> Break down `projects/my_first_story/story.yaml` into a StoryBible and
> scene/shot YAML files. Follow `docs/llm_breakdown.md` for the exact
> protocol.

Hermes will:

1. Read `story.yaml`.
2. Write `state/story_bible.json` (logline, acts, beats, characters, locations).
3. Write `scenes/<scene_id>.yaml` for each scene.
4. Write `shots/<shot_id>.yaml` for each shot, with hand-quality prompts.

You can then hand-edit any shot's prompt / action / emotion / lighting.

### Alternative: rule-based

```bash
video-director analyze   my_first_story
video-director storyboard my_first_story
```

This produces a shallow first draft using deterministic heuristics
(proper-noun extraction, one-scene-per-section, 8 default shots per
scene). Useful for CI smoke tests or as a starting skeleton, but
**you will need to hand-tune every shot's prompt before generating**.

See `docs/llm_breakdown.md` for the full prompt templates and good/bad
prompt examples.

## 7. Run the pipeline

Your final video is at:

```
projects/my_first_story/output/final/final.mp4
```

## 7. Or: one-shot

```bash
video-director run my_first_story --backend mock --max-retries 1
```

…runs analyze + storyboard + generate + assemble in one go. Useful for
small test projects. For real projects you'll want fine-grained control.

## 8. Next: another story

```bash
video-director init my_second_story
```

…and edit the same files. Both projects live independently; deleting
one doesn't touch the other.

## Common mistakes

- **Forgetting to drop the real workflow under `private/`.** You'll see
  `WorkflowNotFoundError`. The framework never reads workflows from
  anywhere else.
- **Wrong node title in `workflow.yaml`.** You'll see
  `ValidationError: workflow mapping references ...`. Re-check the
  titles in your exported JSON.
- **Reference image path doesn't exist.** `validate` will warn. The
  runner will still proceed (we warn rather than fail so partial setups
  are usable).
- **You edited `state/*.json` by hand and broke it.** Run
  `video-director retry --reset-all` to rebuild from scratch.