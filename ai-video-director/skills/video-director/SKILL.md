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

## The 8 commands Hermes runs

| Command                          | When Hermes runs it                                          |
|----------------------------------|--------------------------------------------------------------|
| `video-director init <project>`  | First time a story is mentioned.                             |
| `video-director analyze <p>`     | Optional: regenerate `state/story_bible.json` from `story.yaml`. Use LLM pass for quality (see below). |
| `video-director storyboard <p>`  | Optional: regenerate scenes + shots via the rule-based planner. **Usually skipped in favor of the LLM-driven flow.** |
| `video-director validate  <p>`   | Before each generation run; catches missing refs/workflow.   |
| `video-director generate <p>`    | To actually produce clips. Resumable — re-run safely.       |
| `video-director status <p>`      | Whenever the user asks "where are we?" or after a crash.     |
| `video-director retry <p>`       | After fixing a config / workflow / reference image.          |
| `video-director assemble <p>`    | Once every shot is generated (or with `--allow-qa-fail`).    |
| `video-director run <p>`         | One-shot full pipeline. Only for tiny test projects.         |

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
