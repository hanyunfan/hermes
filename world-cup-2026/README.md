# FIFA World Cup 2026 — Daily Preview

Single-page web app showing every 2026 FIFA World Cup match in your
local timezone, plus group standings and the full knockout bracket.
Auto-updated 6× per day. Deployed on GitHub Pages. Bilingual EN / 中.

🌐 **Live:** https://hanyunfan.github.io/hermes/world-cup-2026/

## Features

- **Match list** — every match from kickoff day 1 through the final
- **Butterfly view** — auto-bucketed by day (Today / Tomorrow / Day +2…)
  in a two-column wing layout
- **Standings** — group tables with W/D/L/GF/GA/GD/pts
- **Knockout bracket** — double-wing butterfly with SVG connecting
  lines; placeholders fill in as the group stage completes
- **Filters** — time range, status, multi-team search, multi-venue
- **Timezone picker** — 12 zones, defaults to browser
- **i18n** — English / 中文
- **Live "Updated Xm ago" indicator** in the header

## How it works

```
ESPN public scoreboard API
        ↓
scripts/fetch_matches.py  ──── fetch & normalize to America/Chicago
        ↓
data/matches.json          ──── committed to repo
        ↓
index.html + app.js + style.css  ──── GH Pages
```

### Refresh triggers (priority order)

1. **External cron** *(primary)* — `cron-job.org` hits the repository
   dispatch API 6× daily in `America/Chicago`. Fires within seconds.
2. **GitHub Actions `schedule`** *(fallback)* — 6 cron expressions in
   UTC map to the same CT windows. Will run within 1–3 hours of
   schedule in practice; off-hours crons can be delayed further.
3. **`workflow_dispatch`** — manual run from the Actions tab.
4. **`push`** to `scripts/fetch_matches.py` or this workflow file.

### Schedule (all times America/Chicago)

| Local  | UTC         | Catches match window that ended ≈  |
|--------|-------------|-------------------------------------|
| 07:00  | 12:00 UTC   | 23:00 CT (overnight wrap)           |
| 13:30  | 18:30 UTC   | 13:00 CT                            |
| 16:30  | 21:30 UTC   | 16:00 CT                            |
| 19:30  | 00:30 UTC   | 19:00 CT                            |
| 22:30  | 03:30 UTC   | 22:00 CT                            |
| 01:00  | 06:00 UTC   | 23:00 CT (extra-time / late goals)  |

Each fire lands ≈30 min after its target window so ESPN has published
the latest scores. Group-stage matches kick off at 11/14/17/20/23 CT
and run ~2h05m.

## External cron setup (one-time)

1. Create a free account at **[cron-job.org](https://cron-job.org)**.
2. Create a GitHub PAT with `repo` scope at
   <https://github.com/settings/tokens/new>. Copy the token.
3. For each of the 6 times, create a cronjob with:
   - **Timezone:** `America/Chicago`
   - **Cron expression:** `0 7 * * *`, `30 13 * * *`, `30 16 * * *`,
     `30 19 * * *`, `30 22 * * *`, `0 1 * * *`
   - **URL:** `https://api.github.com/repos/hanyunfan/hermes/dispatches`
   - **Method:** `POST`
   - **Headers:**
     ```
     Accept: application/vnd.github+json
     Authorization: Bearer ghp_…your-PAT…
     X-GitHub-Api-Version: 2022-11-28
     ```
   - **Body:** `{"event_type":"refresh-wc2026"}`

If you want to verify the workflow can receive the dispatch, run from
your terminal:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ghp_…your-PAT…" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/hanyunfan/hermes/dispatches \
  -d '{"event_type":"refresh-wc2026"}'
```

A `204 No Content` means success; check the Actions tab for the run.

## Local development

```bash
cd world-cup-2026
python3 scripts/fetch_matches.py --tz America/Chicago
python3 -m http.server 8000
# open http://localhost:8000/
```

Pass any IANA zone to `--tz` (e.g. `Europe/London`) to preview from
another fan's perspective.

## Layout

```
world-cup-2026/
├── index.html            # single page, inline <template> blocks
├── app.js                # data loader, i18n, renderer, filters
├── style.css             # dark theme
├── data/
│   └── matches.json      # auto-generated, do not edit
└── scripts/
    └── fetch_matches.py  # ESPN → normalized JSON (schema v2)
```

Workflows live at the repo root (GitHub Pages requirement — subdir
workflows are silently ignored):

```
.github/workflows/
├── fetch-wc2026.yml      # 6× daily refresh
├── pages.yml             # deploy whole repo to GH Pages
└── sync-machines.yml     # unrelated
```

## Data schema (v2)

```jsonc
{
  "schema_version": 2,
  "generated_at": "2026-06-13T09:26:09+00:00",        // UTC ISO
  "timezone": "America/Chicago",
  "now_local": "2026-06-13T04:26:09-05:00",          // for sanity checks
  "tournament": {
    "name": "FIFA World Cup 2026",
    "host": "USA / Canada / Mexico",
    "dates": "Jun 11 – Jul 19, 2026",
    "edition": "23rd",
    "start": "2026-06-12",
    "end":   "2026-07-19"
  },
  "facets": {
    "teams":  [{ "id", "name", "short", "abbr", "flag", "first_seen", "group_count" }],
    "venues": [{ "id", "name", "city", "country", "capacity" }],
    "stages": ["Group Stage", "Round of 32", "Round of 16", "Quarterfinals",
               "Semifinals", "3rd Place Match", "Final"]
  },
  "groups": [
    {
      "id": "1", "name": "Group A", "abbreviation": "Group A",
      "entries": [
        {
          "team": { "id", "name", "short", "abbr", "flag", "logo" },
          "rank": 1, "mp": 1, "w": 1, "d": 0, "l": 0,
          "gf": 2, "ga": 0, "gd": 2, "pts": 3,
          "advance": false, "advance_comment": ""
        }
      ]
    }
  ],
  "days": [
    {
      "date": "2026-06-12",
      "label": "Fri",
      "match_count": 2,
      "matches": [
        {
          "id": "760416",
          "kickoff_utc":        "2026-06-12T19:00:00+00:00",
          "kickoff_local":      "2026-06-12T14:00:00-05:00",
          "kickoff_local_date": "2026-06-12",
          "kickoff_time":       "2:00 PM",
          "kickoff_weekday":    "Fri",
          "status":       "FINAL",  // SCHEDULED | LIVE | FINAL
          "status_short": "FT",
          "stage": "Group Stage",
          "stage_slug": "group-stage",  // group-stage | round-of-32 | round-of-16
                                      // | quarterfinals | semifinals
                                      // | 3rd-place-match | final
          "home": { "id", "name", "short", "abbr", "flag", "logo", "color",
                    "home_away": "home", "score": 1, "winner": false },
          "away": { … same shape, home_away: "away" … },
          "venue":      { "name", "city", "country" },
          "broadcasts": ["FOX", "Tele", "Peacock"],
          "espn_url":   "https://www.espn.com/soccer/match/_/gameId/…",
          "fox_url":    "https://www.foxsports.com/search?q=…",
          "slug":       "bosnia-herzegovina-at-canada"
        }
      ]
    }
  ]
}
```

## Notes

- The "Updated Xm ago" label in the header is timezone-agnostic
  (relative to `new Date()`); the tooltip on hover shows the absolute
  time in your browser's local zone.
- Knockout bracket SVG uses an affine transform on the y-axis
  (`y' = y*0.9 + 5`) to give the topmost card breathing room from
  the column-labels row while preserving the midpoint relationships
  the connecting curves rely on.

## License

Code: MIT. Match data: ESPN (public scoreboard API, no key required).
