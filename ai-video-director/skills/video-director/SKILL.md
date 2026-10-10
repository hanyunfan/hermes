---
name: video-director
description: |
  Reusable framework for AI long-form story video production. Run script-to-video pipelines,
  manage per-project state with checkpoint/resume, swap video backends (mock, ComfyUI).
version: 0.1.0
---

# video-director skill

This skill teaches Hermes to drive the `video-director` framework as a
director/producer: it understands the pipeline, asks the user for missing
inputs, runs the right commands, and persists state so conversations don't
have to hold it.

The Python implementation does the heavy lifting (FFmpeg, ComfyUI, retry,
checkpoint). Hermes orchestrates, records decisions in the project's files,
and refuses to leak private content into Git.

## When to use this skill

Use when the user says any of:

- "Generate a video from this script"
- "Produce a 10-minute story video"
- "Run the next batch of shots"
- "Resume my video project"
- "Assemble the final video"
- "Validate my project"
- "Retry the failed shots"

Do **not** use for: short-form clips, voice-over-only work, or anything
where the user does not have a multi-shot story pipeline in mind.

## Mental model

```
script/story.yaml
       ↓ StoryAnalyzer
   story_bible
       ↓ ScenePlanner + ShotPlanner
   scenes/*.yaml  +  shots/*.yaml
       ↓ GenerationRunner (loop)
   output/clips/<shot_id>.mp4  +  state/jobs/*.json
       ↓ QAChecker
   state/qa/*.json
       ↓ FFmpegBuilder
   output/final/final.mp4
```

Everything is a file. Hermes never needs to remember the plan in
conversation — re-running `video-director status <project>` shows the truth.

## The commands Hermes runs

| Command                                   | When Hermes runs it                                          |
|-------------------------------------------|--------------------------------------------------------------|
| `video-director init <project>`           | First time a story is mentioned.                             |
| `video-director validate-imports <p>`     | After Grok (or any LLM) outputs JSON into `imports/`. Stops the build if any schema/reference/chain errors. |
| `video-director build <p>`                | After `validate-imports` passes. Converts `imports/*.json` into `story.yaml` / `characters/*.yaml` / `scenes/*.yaml` / `shots/*.yaml`. |
| `video-director analyze <p>`              | Optional: regenerate `state/story_bible.json` from `story.yaml`. Use LLM pass for quality (see below). |
| `video-director storyboard <p>`           | Optional: regenerate scenes + shots via the rule-based planner. **Usually skipped in favor of the Grok-driven flow.** |
| `video-director validate <p>`              | Before each generation run; catches missing refs/workflow.   |
| `video-director generate <p>`             | To actually produce clips. Resumable — re-run safely. Use `--force` to overwrite existing mp4 (default: skip). |
| `video-director status <p>`               | Whenever the user asks "where are we?" or after a crash.     |
| `video-director retry <p>`                | After fixing a config / workflow / reference image.          |
| `video-director assemble <p>`             | Once every shot is generated (or with `--allow-qa-fail`). Now **strict**: refuses to include orphan mp4 files that don't have a matching `shots/*.yaml`. |
| `video-director run <p>`                  | One-shot full pipeline. Only for tiny test projects.         |

## Director workflow

When the user says "make a 10-minute video from this script":

1. Create the project: `video-director init <name> --title "..." --duration 600`.
2. Tell the user what to put where (concrete files; never invent content):
   - `story.yaml` — the screenplay
   - `characters/*.yaml` — character descriptions + reference images
   - `private/video_workflow.json` — their real ComfyUI workflow
   - `workflow.yaml` — the mapping from shot fields to node titles
3. After they confirm the assets exist, run `validate`. Fix anything it warns about.
4. **Run the LLM breakdown pass** (see below) — Hermes reads `story.yaml`
   and writes `state/story_bible.json` + `scenes/*.yaml` + `shots/*.yaml`.
   The user can hand-tune shots afterwards; that's expected.
5. Run `generate --backend comfyui`. Tell the user this can take a long time; suggest running in the background.
6. If the user comes back later saying "where are we?" → `status`.
7. If something failed and the user fixed the underlying cause (added a ref, fixed the workflow) → `retry --shot <id>` (or `--reset-all` for a full restart).
8. When all shots are COMPLETED → `assemble`.
9. Send the user the path to `output/final/final.mp4`.

## Story breakdown — LLM-driven vs rule-based

The CLI's `analyze` and `storyboard` commands are **rule-based and
generic**. They produce shallow output and are mainly there for CI
smoke tests and deterministic regeneration after `story.yaml` edits.

For a real story, **Hermes should drive the breakdown itself** rather
than calling those commands. The full protocol is in
`docs/llm_breakdown.md`. Short version:

- **StoryBible phase** — Hermes reads `projects/<p>/story.yaml`,
  writes `projects/<p>/state/story_bible.json` (title, logline,
  acts, beats, characters, locations).
- **Storyboard phase** — Hermes reads both files and writes
  `scenes/<scene_id>.yaml` and `shots/<shot_id>.yaml`, one per
  scene and one per shot. Total shot count ≈ `target_duration_sec / 5`.
- **Hand-tune phase** — the user can edit any shot's `prompt`,
  `action`, `emotion`, `lighting`, etc. directly. The shot YAML files
  are the source of truth for `generate`.

When to use the rule-based commands instead:

- CI / smoke tests
- The user wants a starting skeleton they'll rewrite anyway
- The user explicitly asks for "the default breakdown"

When to use the LLM-driven flow:

- Any production story
- Anything longer than 1 minute
- Anything with character continuity requirements

The `validate` command works against either path's output — same
schemas, same checks.

## Conversation discipline

Hermes should keep answers short and write decisions into the project:

- Long status summaries → `state/run_state.json` (write it; tell the user the path)
- Continuity questions → `state/story_bible.json` (already written by `analyze`)
- Failed jobs → read `state/jobs/<job_id>.json` for the actual error
- Resumability → never suggest "start over"; always `retry` or `--reset`

## Hard rules (safety)

1. **Never** copy `private/`, `references/`, or any video/audio into the Git
   working tree. These directories are `.gitignore`d by the template.
2. **Never** commit a real ComfyUI workflow JSON. The framework ships a
   `workflows/video_workflow.template.json` placeholder; the user drops their
   real workflow under `<project>/private/`.
3. Before any commit, run `python scripts/check_git_safety.py` and act on its
   output. If it flags private files, abort the commit.
4. Never paste real character descriptions / reference image paths into chat
   if the user might be sharing with others; refer to file paths instead.
5. If `validate` reports high-severity continuity issues (unknown
   characters, broken references), stop and ask the user before generating.

## Failure recovery cheatsheet

| Symptom                                                | First action                                                                |
|--------------------------------------------------------|-----------------------------------------------------------------------------|
| Generation stuck on one shot                           | `status <p>` → look at the latest job → `retry --shot <id>`                 |
| "workflow_not_found" error                            | Confirm `private/video_workflow.json` exists; check `workflow.yaml` mapping |
| Mock clips in production run                          | Check `--backend comfyui` was passed                                         |
| Final video is shorter than expected                   | `assemble --allow-qa-fail` to see which shots are missing                   |
| FFmpeg error during assembly                           | Inspect clip dimensions in `state/clips/*.json`; pass `--width/--height`    |
| User says "I changed the workflow"                    | `retry --reset-all --backend comfyui`                                       |

## Arguments Hermes should know

`--backend mock` is the default and produces a deterministic colour clip per
shot via FFmpeg — useful for testing the pipeline without a GPU. Production
runs must use `--backend comfyui`.

`--max-retries N` controls how many times the runner re-attempts a failed
shot. Default is 3. Higher values make sense when the backend is flaky.

`--no-new-seed` keeps the original seed across retries; default behaviour
rotates the seed so a transient bad seed doesn't repeat.

## What this skill does NOT do

- It does **not** write screenplays. The user supplies `story.yaml`.
- It does **not** generate reference images. The user supplies them.
- It does **not** own the ComfyUI server. The user runs it (or `scripts/` may
  add a launcher later — out of scope for v0).
- It does **not** make a web frontend. CLI + filesystem only.


## Grok-driven workflow (recommended for production)

For real stories, **do not** use `analyze` / `storyboard` (they're rule-based
placeholders). Use Grok (or ChatGPT / Claude / any LLM) to produce a structured
JSON tree, drop it into the project's `imports/` directory, validate it, then
build the framework yaml from it.

### Step 1 — give Grok the prompt template

The framework ships with the exact prompt to paste into Grok at:

```
prompts/grok_storyboard.md
```

Read that file (always read fresh — Hermes never inlines it into chat). It tells
the LLM to output **5 separate JSON files**, each with a fixed schema and field
set. The user's story text is appended at the bottom of that prompt.

### Step 2 — save Grok's output to the right paths

Each `[FILE: foo.json]` block Grok emits is saved to:

| Grok emits                | Goes to                                          |
|---------------------------|--------------------------------------------------|
| `[FILE: story.json]`      | `projects/<id>/imports/story.json`               |
| `[FILE: characters.json]` | `projects/<id>/imports/characters.json`          |
| `[FILE: scenes.json]`     | `projects/<id>/imports/scenes.json`              |
| `[FILE: shots.json]`      | `projects/<id>/imports/shots.json`               |
| `[FILE: dialogues.json]`  | `projects/<id>/imports/dialogues.json` (optional)|

Reference images (per character) — see "Reference picture layout" below.

### Step 3 — validate

```bash
video-director validate-imports <project_id>
```

This runs every schema + reference + chain check. The checker distinguishes
ERRORs (must fix) from WARNINGs (advisory). If it reports anything other than
`[ok] ALL CHECKS PASSED`, the user fixes `imports/*.json` and re-runs.

### Step 4 — build yaml

```bash
video-director build <project_id>
```

Refuses to write if `validate-imports` would still fail. Overwrites existing
yaml (imports/ is the source of truth).

### Step 5 — cross-check + generate

```bash
video-director validate <project_id>
video-director generate <project_id> --backend mock      # dry run, no GPU
video-director generate <project_id> --backend comfyui   # real
video-director assemble <project_id>
```

### Hard guarantees (this is the "framework" part)

The framework enforces several invariants the user explicitly cares about:

1. **Strict clip count** — `assemble` only includes mp4 files in `output/clips/`
   whose names match a `shots/*.yaml` filename. Orphan mp4s (e.g. from a previous
   run that crashed mid-generation, or from shots that were deleted from yaml
   after they were already generated) are **reported and refused**.
2. **Idempotent runner** — re-running `generate` for a shot whose mp4 already
   exists is a no-op. To overwrite, pass `--force`. This prevents the
   "75-shot run turned into 200-shot run" problem.
3. **Atomic write** — every mp4 is downloaded to `<name>.mp4.part` first, then
   renamed atomically. A crash mid-download leaves the previous successful mp4
   in place instead of a half-corrupted one.
4. **Shot chain** — every shot has `previous_shot` / `next_shot` references,
   validated bidirectionally. The validator refuses builds where the chain is
   broken or has multiple starts/ends.
5. **start_frame continuity** — when a shot's `start_frame_source` is
   `previous_shot`, the runner uses ffmpeg to extract the last frame of the
   previous shot's mp4 into ComfyUI's input directory and uses it as the
   start frame. Falls back to a reference image if extraction fails.

### What "framework" means here

Hermes does **not** generate the story, the JSON, or the prompts. The user
supplies all of those via `prompts/grok_storyboard.md`. Hermes runs the
validation, runs the build, runs the generation, reports failures with
specific check codes, and never silently produces extra clips.

## Argument reference (cheat sheet)

```text
video-director init <project>
    [--title <t>] [--description <d>] [--language <zh|en>] [--duration <sec>]

video-director validate-imports <project>

video-director build <project>

video-director validate <project>

video-director generate <project>
    --backend {mock,comfyui}            (default: mock)
    --max-concurrent-jobs N             (default: 1)
    --max-retries N                     (default: 3)
    --no-new-seed                       (keep seed across retries)
    --only <id[,id,...]>                (re-run these shots)
    --reset                             (wipe all jobs/clips first)
    --force                             (overwrite existing mp4; default: skip)

video-director retry <project>
    --shot <id[,id,...]>                (clear + rerun these)
    --reset-all                         (clear everything)
    --backend {mock,comfyui}
    --max-retries N

video-director assemble <project>
    --skip-qa
    --allow-qa-fail
    --width N --height N                (override resolution)
    --audio <path>                      (extra audio track; repeatable)
    --audio-kind {voice,bgm,sfx}        (pairs with --audio)

video-director status <project> [--json]
video-director list
video-director run <project>            (analyze + storyboard + generate + assemble)
```



## Reference picture layout

The user supplies character reference images that the video model uses as a
visual anchor for each character (face, clothing, etc.). There are two layouts
the framework accepts:

### Layout A — directory name = `character_id` (recommended)

```
projects/<id>/imports/references/
├── lin_xi/
│   ├── hero.jpg
│   └── face.png        (optional, only-for close-ups)
└── lao_seng/
    └── hero.jpg
```

`characters.json` references match the directory:

```json
[
  {"character_id": "lin_xi",   "reference_image": "imports/references/lin_xi/hero.jpg"},
  {"character_id": "lao_seng", "reference_image": "imports/references/lao_seng/hero.jpg"}
]
```

### Layout B — numeric or generic directories

If the user already placed files under `1/`, `2/`, `main_guy/`, etc.:

```
projects/<id>/imports/references/
├── 1/
│   └── hero.jpg
└── 2/
    └── hero.jpg
```

`characters.json` must point at the same path — Grok outputs whatever the
real layout is, and `validate-imports` only requires the file to exist:

```json
[
  {"character_id": "young_woman", "reference_image": "imports/references/1/hero.jpg"},
  {"character_id": "young_man",   "reference_image": "imports/references/2/hero.jpg"}
]
```

### Validation

`video-director validate-imports` enforces two reference-image rules:

| Code | Severity | Meaning |
|---|---|---|
| `MISSING_REFERENCE_IMAGE` | ERROR | `characters[i].reference_image` points to a path that doesn't exist on disk. The runner would silently generate the video WITHOUT a visual anchor — the resulting character's face is random. **This must fail the build.** |
| `REFERENCE_DIR_MISMATCH` | WARNING | The directory part of the path doesn't match `character_id`. Allowed but suspicious — it's usually a mistake. |

The user's responsibility:
1. Place reference images under `projects/<id>/imports/references/<something>/`
2. Run `ls imports/references/` and tell the LLM what the actual layout is

The framework's responsibility:
1. The reference image is uploaded to ComfyUI input dir and used as
   `LoadImage.image` on the i2v workflow
2. The `hero` role is the default; `face` is used when a close-up shot
   references `face` role specifically (not yet wired into runner v0.1)

## Character name ↔ ID convention (Chinese)

Every character needs a stable `character_id` slug referenced by `scene`,
`shot`, and `dialogue` records. For Chinese stories, the convention is:

| 中文名 | 拼音 | character_id |
|---|---|---|
| 林夕 | linxi | `lin_xi` |
| 苏清 | suqing | `su_qing` |
| 长安 | changan | `changan` |
| 王二狗 | wangergou | `wang_er_gou` |
| 主角(无名) | — | `hero` / `protagonist` |

Rules:
1. Take the **full pinyin** of each Chinese character (no tones): 林夕 → `linxi`
2. Join by underscores, one syllable per character: 林夕 → `lin_xi`
3. Lowercase ASCII, only `[a-z0-9_]` (no spaces, no hyphens, no caps)
4. Two characters with the same pinyin → add disambiguating suffix:
   `zhang_san` vs `zhang_shan`
5. For unnamed roles ("老人", "路人甲") → use role-based slug: `old_man`, `passerby_a`
6. If the same character has multiple names ("李公子" / "李郎中"), use the
   most formal one as `character_id` and mention aliases in `appearance`/`personality`

`video-director validate-imports` enforces slug format (`INVALID_SLUG` if
the id contains uppercase, hyphens, spaces, or non-ASCII).
