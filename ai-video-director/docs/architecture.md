# Architecture

## Mental model

The framework is a **state machine over a project directory**.

```
                       ┌──────────────────────────────────┐
                       │         Project Directory         │
                       │   projects/<story_id>/           │
                       │     story.yaml                   │
                       │     characters/  scenes/  shots/ │
                       │     references/  private/        │
                       │     output/  state/              │
                       └──────────────────────────────────┘
                                    ▲        │
                                    │        │ reads / writes
                                    │        ▼
┌──────────┐    ┌─────────────────┐  │  ┌─────────────────┐
│  Hermes  │ ── │   CLI / Skill   │──┘  │  Backends       │
│  Agent   │    │  (orchestrator) │     │  (mock / comfyui)│
└──────────┘    └─────────────────┘     └─────────────────┘
                          │                       │
                          ▼                       ▼
                ┌──────────────────────────────────────┐
                │           Python Core                │
                │  models · story · continuity · jobs   │
                │  quality · assembly                   │
                └──────────────────────────────────────┘
```

* **Project directory** — the unit of isolation. Each story is fully self-contained.
* **CLI / Skill** — orchestrates the pipeline. Stateless; reads everything from disk.
* **Python core** — does the actual work: parsing, scheduling, FFmpeg, ComfyUI calls.
* **Backends** — pluggable video generators. The framework is backend-agnostic.

## Pipeline

```
script (story.yaml)
   ↓ StoryAnalyzer
StoryBible
   ↓ ScenePlanner
Scenes[]
   ↓ ShotPlanner
ShotPlan[] → persisted as shots/<id>.yaml
   ↓ GenerationRunner.run()
   │  for each shot:
   │     - resolve workflow (UI / API format)
   │     - patch prompt / negative / seed / images
   │     - submit to backend
   │     - poll for completion
   │     - persist job + clip state
   ↓ QAChecker
   │  - per-clip: exists / size / decode / duration / resolution / fps
   ↓ FFmpegBuilder.run()
   │  - concat clips with scale/fps normalisation
   │  - optionally mix audio (voice / bgm / sfx)
   ↓
output/final/final.mp4
```

## Key design decisions

### 1. State on disk, not in memory

Every meaningful state change is **atomically** written to disk:

- `state/generation_state.json` — top-level run state + counters
- `state/jobs/<job_id>.json` — one file per attempt
- `state/clips/<shot_id>.json` — successful clip metadata
- `state/last_run_summary.json` — last run's outcome
- `state/story_bible.json` — compiled story
- `state/assembly_manifest.json` — assembly inputs

Writes use `tmp-file + os.replace()` so a crash mid-write can never leave a
half-written JSON. Reads tolerate missing files (return `None`) so first-run
bootstrapping is a no-op.

This means: kill the runner mid-batch, restart it, and it picks up exactly
where it left off. No in-memory state to lose.

### 2. Workflow adapter via title lookup

ComfyUI users export their workflow JSON in either **API format**
(`{"1": {"_meta": {"title": "..."}, ...}}`) or **UI format**
(`{"nodes": [{"id": 1, "title": "..."}]}`). Node IDs are renumbered every
time you edit the workflow.

We solve this by mapping **node titles** (which survive renumbering) to
runtime IDs at resolve time. The mapping is a simple YAML:

```yaml
prompt_node: PositivePrompt
negative_prompt_node: NegativePrompt
seed_node: KSampler
output_node: VHS_VideoCombine
image_input_nodes:
  hero: LoadImageHero
extra_param_nodes:
  steps: KSamplerSteps
```

### 3. VideoGenerator interface

```python
class VideoGenerator(ABC):
    capabilities: GeneratorCapabilities
    def generate(shot, *, output_dir, references, seed_override, context) -> GenerationOutcome: ...
    def cancel(shot_id) -> bool: ...
```

Two built-in backends:

- **MockVideoGenerator** — produces a real MP4 via FFmpeg with the shot id
  baked in as text overlay. Deterministic given the shot's seed. **Offline.**
- **ComfyUIGenerator** — uses the workflow adapter to call a ComfyUI HTTP
  server. Configurable base URL, timeout, polling interval.

The runner talks to backends via this interface so swapping is free.
Adding a new backend (e.g. cloud API) is a small class.

### 4. Per-project isolation, gitignored

The framework ships `projects/template/` as a complete scaffold. Every
other project is created by copying that scaffold:

```bash
video-director init my_story
```

…and then lives under `projects/my_story/`. That directory is **gitignored**.
Only the framework + template are committed. The pre-commit
`scripts/check_git_safety.py` enforces this even if a contributor's
`.gitignore` is wrong.

### 5. Continuity as static analysis

The ContinuityManager doesn't call a vision model. It walks the shot list
in order, tracks per-character state (outfit, location, lighting), and
flags inconsistencies:

- A shot references an unknown character.
- A character's outfit changes without the action mentioning a wardrobe
  change.
- Per-character continuity rules from `characters/<id>.yaml` are listed
  as low-severity reminders.
- Consecutive shots get their `previous_shot` / `next_shot` fields
  populated, plus a hint to use the previous shot's last frame as the
  next shot's start frame.

Vision-based QA is pluggable — drop a custom rule into
`quality/checker.py:DEFAULT_RULES`.

### 6. Resumability as a first-class concern

The runner never re-runs a shot that already has a COMPLETED job in state.
Retry policy is configurable:

- `max_retries` — total attempts per shot (default 3)
- `retry_with_new_seed` — rotate seed across retries (default true) so a
  bad seed doesn't repeat
- `video-director retry --shot <id>` — clear one shot's state, rerun
- `video-director retry --reset-all` — wipe everything, start over

## What's intentionally out of scope (v0)

- Distributed scheduling / web frontend
- LLM-driven story analysis (we ship a deterministic rule-based analyzer;
  LLM analysis is pluggable behind the same interface)
- Cloud video APIs (ComfyUI is the production path; the interface supports
  others)
- AI vision QA (the rule-based QA is shipped; vision is pluggable)
- Subtitle rendering (the assembler accepts subtitles as input; we don't
  yet transcribe audio)

Each of these can be added without changing the framework's spine.
