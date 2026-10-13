# `test_r2v/` — ref2v smoke test (2026-10-12)

This is a **scaffold test project** I used to verify that the new ref2v
pipeline works end-to-end. It's a copy of `../template2/` with one
character (young_woman) and one shot.

## Why this lives in the repo

It serves three purposes:

1. **Regression**: if anyone breaks the ref2v pipeline, this project
   is the fastest way to reproduce. `video-director generate test_r2v
   --backend comfyui --only shot_001` should always succeed.
2. **Documentation**: the JSON files (story.json, shots.json, etc.)
   show the minimum viable input shape for a ref2v project.
3. **Reference image**: `imports/references/young_woman/hero.jpg` is a
   placeholder that anyone can re-use to verify the pipeline without
   needing their own ref image.

## What it does

The single shot (`shot_001`) generates a 5-second cinematic close-up
of a young woman, using `hero.jpg` as the reference image. The output
should preserve the character's general appearance across the 5
seconds (intra-shot consistency).

## Running it

```bash
video-director validate-imports test_r2v
video-director build test_r2v
video-director generate test_r2v --backend comfyui --only shot_001
```

The output goes to `output/clips/shot_001.mp4` (gitignored).

## How to use it as a starting point

```bash
cp -R projects/test_r2v projects/<your_project_id>
# Edit project.yaml, characters/*.yaml, imports/*, refs
```
