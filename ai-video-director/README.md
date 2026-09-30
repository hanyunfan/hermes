# ai-video-director

A reusable framework for **AI long-form story video production**.

`ai-video-director` is the skeleton, not a story. It does not write
screenplays, does not generate reference images, and does not ship a
real ComfyUI workflow — those are user-supplied per project. What it
*does* ship is a complete production pipeline you can point at any
new story and get a consistent, resumable, retry-aware generation +
assembly workflow out.

## Why this exists

You can build a 5-minute AI video by hand once. Building a 20-minute
video with consistent characters, scene continuity, and resumable
generation is a different problem — and the same code shouldn't have
to be rewritten for every story.

This framework:

* separates **framework code** (committed to git) from **per-project
  content** (stories, characters, references, real workflows) — the
  former is generic; the latter stays private.
* treats each story as an isolated project under `projects/<story_id>/`,
  copy-instantiated from `projects/template/`.
* ships a Hermes skill so an LLM director can drive the whole pipeline
  via the CLI without holding state in conversation.
* provides a `MockVideoGenerator` for CI / offline development; the
  ComfyUI backend is the production path.
* persists state per project so a crashed run resumes from the last
  successful shot.

## Repository layout

```
ai-video-director/
├── README.md                  ← this file
├── LICENSE
├── pyproject.toml
├── .gitignore                 ← aggressively protects private content
│
├── src/video_director/        ← framework code
│   ├── cli/                   ← CLI subcommands
│   ├── core/                  ← project manager, paths, errors
│   ├── models/                ← dataclasses + enums (schema)
│   ├── story/                 ← analyzer + planners
│   ├── characters/            ← character bible loader
│   ├── scenes/   shots/       ← thin wrappers for clarity
│   ├── continuity/            ← continuity manager
│   ├── workflow/              ← ComfyUI adapter + resolver
│   ├── generators/            ← VideoGenerator interface + backends
│   │   ├── mock.py            ← deterministic offline generator (CI)
│   │   └── comfyui/           ← ComfyUI backend
│   ├── jobs/                  ← checkpoint / retry / state
│   ├── quality/               ← QA checker
│   ├── assembly/              ← FFmpeg builder
│   └── utils/                 ← io, logging
│
├── skills/video-director/     ← Hermes SKILL.md
├── config/                    ← public config placeholders
├── workflows/                 ← public workflow placeholders
│
├── projects/template/         ← shippable scaffold (committed)
├── projects/story_*/          ← real projects (gitignored)
│
├── tests/                     ← unit + integration tests
├── scripts/check_git_safety.py ← pre-commit safety net
└── docs/                      ← architecture, getting started, etc.
```

## Quick start

```bash
# 1. Install (use a venv)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Create a new story project from the template
video-director init my_story --title "My Story" --duration 600

# 3. Edit the new project
$EDITOR projects/my_story/story.yaml
$EDITOR projects/my_story/characters/*.yaml
# Drop your real ComfyUI workflow JSON at:
#   projects/my_story/private/video_workflow.json
# Then map its nodes in projects/my_story/workflow.yaml
# (see docs/comfyui.md)

# 4. Run the full pipeline
video-director analyze  my_story     # build story bible
video-director storyboard my_story   # scenes + shots
video-director validate  my_story    # check everything is wired up
video-director generate  my_story --backend mock    # CI-friendly mock
video-director generate  my_story --backend comfyui # production
video-director status    my_story     # see what happened
video-director assemble  my_story     # concat to final.mp4
```

Or one-shot:

```bash
video-director run my_story --backend mock
```

## What gets committed vs ignored

**Committed (framework + scaffold only):**
- All Python code under `src/`
- All tests
- All docs
- The empty `projects/template/` scaffold
- Example placeholders under `config/` and `workflows/`
- `LICENSE`, `README.md`, `.gitignore`

**Ignored (per-project private content):**
- `projects/<not-template>/**` — real projects
- `*/references/` — character / scene reference images
- `*/private/` — real ComfyUI workflows, private notes
- `*/output/` — generated videos, intermediate files, logs
- `*/state/` — checkpoint files (regenerable from `retry --reset-all`)
- `local/`, `private/`, `runtime/` at the framework root
- `*.secret.*`, `*.local.*`, `.env`, `real_workflow.json`
- All media files (`*.mp4`, `*.mp3`, `*.png`, ...)

A pre-commit safety check (`scripts/check_git_safety.py`) refuses to
let risky files slip into git even if `.gitignore` is bypassed.

## Running tests

```bash
pytest tests/                 # 85 tests, ~10s, no GPU required
python scripts/check_git_safety.py --strict   # refuse if any private file is tracked
```

## Documentation

- `docs/architecture.md` — overall design
- `docs/getting_started.md` — detailed walkthrough
- `docs/comfyui.md` — wiring your real ComfyUI workflow
- `docs/project_structure.md` — what each file is for
- `docs/troubleshooting.md` — common failure modes

## Status

v0.1.0 — first end-to-end version. Suitable for personal use and as a
starting point for further development. Not yet battle-tested with
production ComfyUI workflows; please report issues.

## License

MIT. See `LICENSE`. The MIT license covers framework code only; your
project's stories, characters, and generated media remain yours.
