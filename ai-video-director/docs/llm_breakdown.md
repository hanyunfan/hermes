# Story breakdown: rule-based vs LLM-driven

This framework has **two ways** to turn a screenplay into scenes and shots:

| Path                          | Quality               | Cost                | When to use                                          |
|-------------------------------|-----------------------|---------------------|------------------------------------------------------|
| `video-director analyze`      | Shallow / generic     | Free / instant      | CI smoke tests; tiny placeholder scripts.            |
| `video-director storyboard`   | Rule-based, mechanical| Free / instant      | First-pass scaffolding before you hand-edit.        |
| **LLM-driven via Hermes**     | High / nuanced        | One LLM call        | **Production. Recommended for real stories.**       |

The LLM-driven path is **the recommended way to create `StoryBible`,
`scenes/`, and `shots/`**. The rule-based path exists so the framework
is still usable without an LLM, and so you can re-run `analyze` /
`storyboard` after hand-editing `story.yaml` to regenerate the bible
deterministically.

The good news: **both paths produce the same files in the same shape**.
You can mix them — e.g. let Hermes write the bible, hand-tune a few
shots, then run `analyze` to validate the bible is consistent.

---

## The two phases

### Phase 1 — Story analysis (story → StoryBible)

Output: `state/story_bible.json` and a rendered copy of useful fields
back into each `characters/*.yaml` and `scene/*.yaml`.

Schema (see `src/video_director/models/story.py`):

```yaml
title: <story title>
logline: <one-sentence hook>
themes: [theme1, theme2]                  # optional
acts:                                     # 3-5 act split
  - act: 1
    summary: ...
    beats: [beat, beat, beat]
beats: [beat1, beat2, ...]                # flat list, also OK
characters: [alice, bob]                   # canonical names
locations: [cafe, rooftop, ...]
```

### Phase 2 — Storyboard (StoryBible + story → scenes + shots)

Output: `scenes/<scene_id>.yaml` + `shots/<shot_id>.yaml`.

Each scene (see `src/video_director/models/scene.py`):

```yaml
scene_id: scene_001
title: Opening
location: cafe
time: morning
characters: [alice]
description: 1-3 sentences setting the scene
duration_sec: 60
style: cinematic
continuity_requirements:
  - Lighting stays warm throughout.
```

Each shot (see `src/video_director/models/shot.py`):

```yaml
shot_id: scene_001_shot_001
scene_id: scene_001
shot_index: 1
duration_sec: 5
shot_type: medium                # wide | medium | close_up | over_shoulder | insert | pov | establishing | aerial
camera: 50mm eye-level
camera_motion: static             # static | pan | tilt | dolly | tracking | handheld
characters: [alice]
action: Alice pushes open the cafe door and looks around.
emotion: curious
environment: small cafe, morning light, empty tables
lighting: warm key from window, soft fill
prompt: A medium shot of Alice entering a small cafe...
negative_prompt: blurry, deformed
seed: 12345
reference_images: [alice/hero.png]
workflow_overrides: {}
status: pending
output_clip: ""
```

A 10-minute video at 5 s/shot ≈ 120 shots. Plan for 1–3 shots per scene
on average; longer scenes for big moments, single shots for transitions.

---

## Recommended workflow: LLM-driven via Hermes

You can either invoke the Hermes skill directly in a chat, or run
`hermes` once with the prompts below. Both produce identical files.

### Step 1 — Have Hermes produce the StoryBible

Paste this into a chat with the `video-director` skill loaded:

```
Project: <project id under projects/>
Story file: projects/<project>/story.yaml
Read it, then write state/story_bible.json with this exact shape:

{
  "title": "...",
  "logline": "...",
  "themes": ["..."],
  "acts": [{"act": 1, "summary": "...", "beats": ["..."]}],
  "beats": ["..."],
  "characters": ["..."],
  "locations": ["..."]
}

Rules:
- characters[] must contain every name that appears in any section.characters.
- locations[] must contain every location mentioned.
- beats[] is a flat list of dramatic beats, one per scene.
- acts[] must split beats into 3-5 acts (try 3 for short stories, 5 for long).
- Write JSON only — no markdown fence, no commentary.
```

Then in the same chat:

```
Save that JSON to projects/<project>/state/story_bible.json.
After writing, run: VIDEO_DIRECTOR_ROOT=. python -m video_director.cli.main validate <project>
Report any warnings.
```

### Step 2 — Have Hermes produce scenes + shots

```
Using the StoryBible you just wrote + projects/<project>/story.yaml,
produce two file sets:

A) scenes/<scene_id>.yaml  (one per scene, 5-15 scenes total)
B) shots/<shot_id>.yaml    (one per shot, 1-4 per scene, id format: <scene_id>_shot_NNN)

Schemas are in:
  src/video_director/models/scene.py
  src/video_director/models/shot.py

Critical rules:
- Total target shot count should approximate target_duration_sec / 5.
- Each shot must list exactly the characters present in that frame.
- action/emotion/environment/lighting MUST be specific prose — not
  placeholders. The renderer's prompt is auto-generated from these.
- prompt is what the video model sees. Write it as if directing the
  model: "A medium shot, eye-level, of Alice entering a small morning
  cafe, warm window light, ...".
- continuity_requirements on scenes should flag visual invariants
  (e.g. "lighting stays warm" or "Alice's outfit unchanged").

After writing both sets, run:
  VIDEO_DIRECTOR_ROOT=. python -m video_director.cli.main validate <project>
Fix anything it flags, then confirm.
```

### Step 3 — Hand-tune, then commit story.yaml + state/ to your project

Once the scene/shot YAML files are written, edit any shot's `prompt`,
`action`, or `emotion` directly. The YAML files are the source of
truth for `generate` — no re-running analyze is needed.

If you change `story.yaml` materially, run
`video-director analyze` to regenerate `state/story_bible.json`, then
re-run the LLM step if you want a re-derived scene/shot list.

### Step 4 — Optional: rule-based regeneration

`video-director storyboard` (no flags) regenerates scenes + shots from
`story.yaml` + `story_bible.json` using the rule-based planner. It
will OVERWRITE your LLM-written shots unless you've saved backups
somewhere. Use it only when:

- You wrote `story.yaml` by hand and want a quick first draft.
- You want to deterministically regenerate after a script edit.
- You're testing the pipeline end-to-end without an LLM.

---

## Recommended workflow: rule-based only (no LLM)

If you don't want to invoke an LLM:

```bash
# 1. Write story.yaml by hand
$EDITOR projects/<project>/story.yaml

# 2. Rule-based analyzer — produces state/story_bible.json
video-director analyze <project>

# 3. Rule-based planner — produces scenes/*.yaml + shots/*.yaml
video-director storyboard <project>

# 4. Hand-edit every shot's prompt/action — the rule-based default
#    prompts are too generic for a real video model.
$EDITOR projects/<project>/shots/*.yaml

# 5. Validate
video-director validate <project>
```

You will likely need to hand-tune every shot prompt. The rule-based
planner is only there to get a skeleton on disk quickly.

---

## What "good" prompts look like

The shot's `prompt` field is what the video model sees. Concretely:

**Bad** (too generic):
```
A shot of a person in a room.
```

**Good** (specific, dense, directing the model):
```
A medium shot, eye-level, of a young woman with short dark hair
(Alice, mid-20s) pushing open the door of a small morning cafe,
warm golden key light from a side window, soft fill, cinematic
shallow depth of field, the cafe is nearly empty with a few
wooden tables visible behind her, she pauses at the threshold
looking around with a curious expression, 24fps, photorealistic.
```

Conventions to keep prompts consistent across shots:

1. Start with shot type + camera + subject: "A medium shot, eye-level,
   of <character>..."
2. State the action in concrete, visual terms — no internal monologue.
3. Describe lighting explicitly.
4. Specify style/quality keywords at the end ("cinematic",
   "photorealistic", "shallow DOF").
5. Mirror the `style` field from `scene.yaml`.

The `negative_prompt` should list things you don't want:
`blurry, deformed, extra fingers, low quality, watermark, text`.

---

## Quick checklist before running `generate`

- [ ] `story.yaml` is filled in
- [ ] `state/story_bible.json` exists (LLM-written or via `analyze`)
- [ ] `scenes/*.yaml` exists with concrete descriptions
- [ ] `shots/*.yaml` exists with hand-tuned prompts
- [ ] `characters/*.yaml` has at least one `reference_images[].path`
- [ ] `references/<char>/*.png` actually exist on disk
- [ ] `private/video_workflow.json` exists
- [ ] `workflow.yaml` has titles matching the workflow's nodes
- [ ] `video-director validate <project>` returns 0 errors

Then:

```bash
video-director generate <project> --backend comfyui
```
