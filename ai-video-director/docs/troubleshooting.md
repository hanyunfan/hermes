# Troubleshooting

## CLI

### `ModuleNotFoundError: No module named 'video_director'`

You didn't `pip install -e .`, or your `PYTHONPATH` doesn't include `src/`.

```bash
pip install -e .
```

### `ProjectNotFoundError`

```bash
$ video-director status nope
[project-not-found] project not found: nope
```

Check `projects/` directory; the id must match a directory under it.
`video-director list` shows all known projects.

### `ProjectExistsError`

You tried `init` on an existing id. Either pick a new name or delete
the existing one (be careful — that wipes the project's state).

## Generation

### `WorkflowNotFoundError: workflow JSON not found`

The user-supplied workflow JSON is missing. Drop it at:

```
projects/<story>/private/video_workflow.json
```

Or wherever `workflow_path` in `workflow.yaml` points. **Default lookup
falls back to `private/video_workflow.json`.**

### `ValidationError: workflow mapping references prompt_node=... but no node with that title exists`

Open your exported workflow JSON and confirm the title matches exactly
(typos and case matter). Re-edit `workflow.yaml`.

### ComfyUI submit returns HTTP 400

Usually a bad workflow shape — ComfyUI rejected it before running.
Check the server's log; the runner's job record (`state/jobs/<id>.json`)
will have the HTTP body.

### ComfyUI execution_error

The workflow ran but a node errored. Check ComfyUI's UI / logs for the
node that failed. Common causes:

- A `LoadImage` node can't find the file — verify the image path.
- The KSampler's `seed` is the wrong type — it must be an integer.
- An IPAdapter node needs both the model and the image uploaded.

### Generation times out

ComfyUI didn't finish in the configured budget. Increase the timeout:

```bash
VIDEO_DIRECTOR_LOG_LEVEL=DEBUG video-director generate my_story
```

…to see the polling. If ComfyUI is just slow, edit
`config/comfyui.yaml` (or pass timeout via env var if you wire one up).

### Mock generator produces coloured clips

If you ran `--backend mock` accidentally, the clips are useless as
content but real as files. Run again with `--backend comfyui`.

## Continuity / QA

### `validate` reports many high-severity issues

You probably renamed characters in `characters/` but not in your shots.
Either revert or run `storyboard` again to regenerate the shots.

### QA fails on resolution / fps

Your mock clips or your ComfyUI output is below the threshold. Lower
`qa.min_resolution_long_edge` in `config/config.example.yaml` (or pass
through your own config) to accept them, or fix the backend.

## Assembly

### FFmpeg fails: "no clips to assemble"

Run `generate` first. The assembler needs clips to work with.

### FFmpeg fails: "filter graph too complex"

You have too many concurrent audio tracks. The default limit is sane;
if you've overridden it, dial it back.

### Final video is shorter than expected

Some shots didn't finish. Use `video-director status` to see which;
run `video-director retry --shot <id>` per missing shot.

### Final video is silently empty (zero bytes)

FFmpeg accepted the command but produced nothing. Check stderr in the
assembler logs (`output/logs/`).

## State

### I want to start over

```bash
video-director retry my_story --reset-all
```

Wipes state; keeps the project structure intact.

### I want to redo one shot

```bash
video-director retry my_story --shot scene_001_shot_001
```

Wipes that one shot's jobs and clip, then re-runs.

### State file is corrupted

Manually delete the offending file under `state/`, then `retry
--reset-all` to rebuild the rest.

## Tests

### `ffmpeg not found`

```bash
sudo apt-get install ffmpeg
```

### `ffprobe not found`

Same — `ffmpeg` package ships `ffprobe`.

### ComfyUI-related tests are skipped

We don't run ComfyUI in tests. The `MockVideoGenerator` covers the
plumbing; the `ComfyUIWorkflowAdapter` is unit-tested with a fake
HTTP server. Real ComfyUI integration is up to the user.
