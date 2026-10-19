# state/ — checkpoint files (gitignored)

The StateManager writes here so generation can be interrupted and resumed.

```
state/
├── generation_state.json       # top-level run state + counters
├── story_bible.json            # from `video-director analyze`
├── last_run_summary.json       # from `video-director generate`
├── assembly_manifest.json      # from `video-director assemble`
├── jobs/<job_id>.json          # one per generation attempt
├── clips/<shot_id>.json        # one per successful clip
└── qa/<shot_id>.json           # QA verdicts
```

All files are auto-generated. You should not need to edit them manually.
If state gets corrupted, `video-director retry --reset-all` will rebuild.