# ai-video-director scripts/

This directory holds reusable scripts that operate on **any** project under
`projects/<id>/`. They are independent of the framework's Python code and
can be invoked by hand, cron, systemd timers, or wrappers.

## `sync_clips.py`

Mirror newly produced ComfyUI mp4 files into
`projects/<id>/output/clips/<shot_id>.mp4`.

```bash
# dry-run first to see what would change
.venv/bin/python scripts/sync_clips.py <project_id> --dry-run

# actually sync
.venv/bin/python scripts/sync_clips.py <project_id>

# if ComfyUI writes somewhere other than /home/frank/ComfyUI/output/video
.venv/bin/python scripts/sync_clips.py <project_id> --comfyui-video-dir /elsewhere
```

It walks `state/jobs/*.json`, looks for `status=completed` jobs whose mp4
hasn't been copied into the project's `output/clips/` yet, and copies them
in. It also recomputes `generation_state.json` counters afterwards.

If the runner crashed before writing `output_path`, the script falls back
to a timestamp-window match between the job's `started_at`/`finished_at`
and the mtime of every mp4 in ComfyUI's output dir. This recovers the
"runner crashed mid-download" case where the mp4 exists but the framework
record doesn't.

## `monitor.sh`

One-line status snapshot suitable for cron / systemd timer invocation.
Idempotent and silent when nothing changed.

```bash
# run from anywhere — paths are absolute
bash scripts/monitor.sh <project_id>

# custom ComfyUI output dir
bash scripts/monitor.sh <project_id> /custom/comfyui/output/video
```

Emits ONE of these to stdout and writes the same to
`projects/<id>/output/logs/monitor.last_status`:

| Condition | Message |
|---|---|
| New shots completed since last run | `+N shot(s) completed: now A/B` |
| Runner dead, work still to do | `WARNING: runner not running, A/B shots done, F failed` |
| Any failed shots | `F failed shots, A/B done` |
| All quiet | `[SILENT]` |

Exit code is always 0 except on usage errors.

## Recommended scheduling

System cron or systemd timer (NOT Hermes cron — these scripts belong to
the project, not the agent):

```cron
# /etc/cron.d/ai-video-director (per-project line)
*/15 * * * * frank /home/frank/hermes/ai-video-director/scripts/monitor.sh story_chang_an > /home/frank/hermes/ai-video-director/projects/story_chang_an/output/logs/monitor.cron.log 2>&1
```

```ini
# ~/.config/systemd/user/ai-video-director-monitor.service
[Service]
Type=oneshot
ExecStart=/home/frank/hermes/ai-video-director/scripts/monitor.sh story_chang_an

# ~/.config/systemd/user/ai-video-director-monitor.timer
[Timer]
OnCalendar=*:0/15
Persistent=true
[Install]
WantedBy=timers.target
```

## `check_git_safety.py`

Pre-commit safety net that scans the working tree for files that should
never be committed (real workflow JSONs, *.mp4, *.env, etc.).

```bash
.venv/bin/python scripts/check_git_safety.py        # warn only
.venv/bin/python scripts/check_git_safety.py --strict # exit 1 on any finding
```
