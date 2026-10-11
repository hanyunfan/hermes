# `private/` — operator-supplied ComfyUI workflow JSON

This template (`template2/`) expects a ComfyUI workflow JSON file that
accepts **multiple** reference images (one per character).

The template ships a **fallback** workflow JSON (`video_workflow_api.json`)
that was copied from `projects/template/private/` — it is a **single**-
image MiniMax-H3 workflow and only supports one `start_frame` reference
per shot. Use it for prototyping.

## Replace the fallback with a multi-image workflow

To enable multi-character reference images per shot, replace
`video_workflow_api.json` with one that has:

* One `LoadImage` node per character role, OR one stack of nodes per
  character (`LoadImage -> IPAdapter -> ...`) wired into the I2V model.
  Node titles must match `workflow.yaml:image_input_nodes`.

The replacement file must keep the **same filename** (`video_workflow_api.json`)
unless you also update `workflow.yaml:workflow_path`.

## Required structure (for the multi-image workflow)

1. **One `LoadImage` node per character**, with titles referenced from
   `workflow.yaml:image_input_nodes`:

   ```
   image_input_nodes:
     character_a: "Load Image Character A"
     character_b: "Load Image Character B"
   ```

   Titles must **exactly** match the node titles in the JSON (the
   `title` field, not `class_type`).

2. **An I2V model node** (e.g. `MiniMaxH3ImageToVideo`) wired downstream
   from each LoadImage node, so all character references feed into the
   video generation. Model-specific — see the model node's docs.

3. **A `SaveVideo` (or equivalent) output node** — referenced from
   `workflow.yaml:output_node`.

## When you only have the fallback

Generation works in single-image mode (one `start_frame` per shot).
That's fine for prototyping; swap in the real multi-image workflow
when you have one.

## Naming convention for character roles

Once your multi-image workflow is in place:

* Each character card under `characters/` should declare
  `reference_images[].role` matching the role key in
  `workflow.yaml:image_input_nodes` (e.g. `character_a`).
* Each shot's `reference_images` field is a list of paths to reference
  images. The framework resolves them via
  `ProjectPaths.references_dir / path` (project-relative paths work).
* The `image_input_keys` map in `workflow.yaml` lets you override the
  input port name per role if your model node uses non-standard port
  names (e.g. `image_1` instead of `image`).

## Testing the wiring

Run `video-director analyze <project>` after editing `workflow.yaml`.
The command prints the resolved `image_input_nodes` mapping. If a node
title is misspelled or the JSON has no matching node, the framework
raises a clear `GenerationError` at the first generate attempt —
not silently.