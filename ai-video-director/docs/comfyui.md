# Wiring up your real ComfyUI workflow

This is the step where users get tripped up. Read carefully.

## 1. Design your workflow in ComfyUI

Build the workflow you want for video generation. For example:

```
LoadImage (hero) ─┐
LoadImage (face) ─┼─► IPAdapter ──► KSampler ──► VHS_VideoCombine ──► output
CLIPTextEncode ──┘
```

You can make it as simple or complex as you like; the framework only
cares about the **nodes it needs to patch**:

- a **positive prompt** input
- a **negative prompt** input
- a **seed** input (optional)
- one or more **image** inputs (for character / scene references)
- a few **extra params** (optional — e.g. steps, cfg, sampler name)
- one **output** node (typically `VHS_VideoCombine` or `SaveVideo`)

## 2. Export the workflow

In ComfyUI:

- **File → Export → API** (recommended) — produces `workflow_api.json`.
  This is what `WorkflowResolver` prefers.
- **File → Export** — produces `workflow_ui.json`. Also supported.

Save the file as:

```
<project>/private/video_workflow.json
```

## 3. Find the node titles

Open the exported JSON in a text editor.

### API format

Keys are numeric IDs; each value is the node's spec. Look for `_meta.title`:

```json
{
  "1": {
    "class_type": "CLIPTextEncode",
    "_meta": { "title": "PositivePrompt" },
    "inputs": { "text": "" }
  },
  ...
}
```

The `_meta.title` is what you put in `workflow.yaml`. Note that it's
human-set; rename your nodes in ComfyUI to memorable titles before
exporting.

### UI format

Look for `title` directly on each node:

```json
{
  "nodes": [
    {
      "id": 1,
      "type": "CLIPTextEncode",
      "title": "PositivePrompt",
      ...
    }
  ]
}
```

## 4. Edit `workflow.yaml`

Open `projects/<story>/workflow.yaml`. Map each role to a node title:

```yaml
workflow_name: my_video_workflow
workflow_path: video_workflow.json       # relative to project's private/
prompt_node: PositivePrompt              # <-- title from step 3
negative_prompt_node: NegativePrompt
seed_node: KSampler
output_node: VHS_VideoCombine

image_input_nodes:
  hero: LoadImageHero                    # <-- character hero reference
  face: LoadImageFace                    # <-- character face reference

extra_param_nodes:
  steps: KSampler                        # <-- optional param override

notes: |
  Notes go here.
```

If a role doesn't apply, leave its entry blank or omit it.

## 5. Validate

```bash
video-director validate my_story
```

You should see no errors. If the resolver can't find a titled node, it
will say so explicitly.

## 6. Generate one test shot first

The CLI doesn't have a one-shot command yet, but you can scope to a
single shot:

```bash
video-director generate my_story --only scene_001_shot_001
```

If that works end-to-end, run the full batch.

## 7. Common pitfalls

### Title changes when you re-export

If you rename a node in ComfyUI and re-export, the title in the JSON
changes, and `workflow.yaml` stops matching. Re-edit `workflow.yaml`.

### Image path resolution

`workflow_mapping.image_input_nodes.<role>` sets which ComfyUI `LoadImage`
node receives which role. The backend receives the **relative path**
(e.g. `alice/hero.png`); ComfyUI resolves it relative to its own
`input/` directory. So in your project, `references/alice/hero.png`
needs to be in ComfyUI's `input/alice/hero.png` for the standard
`LoadImage` node to find it. Some custom loaders can take an absolute
path; check yours.

### Multiple video outputs

If your workflow produces both a video and images, point `output_node`
at the video node. The framework expects exactly one media file from
the resolved output node.

### The workflow JSON is private

**Never** commit your real workflow JSON. The pre-commit
`scripts/check_git_safety.py` will refuse. Keep it in
`<project>/private/` only.

## 8. Where to look when things break

- The runner logs every HTTP call. Set
  `VIDEO_DIRECTOR_LOG_LEVEL=DEBUG` to see request bodies.
- `state/jobs/<job_id>.json` records every attempt's error class and
  message.
- The ComfyUI server has its own log — check `~/.local/share/ComfyUI/log`
  or wherever your install puts it.
