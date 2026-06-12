# FIFA World Cup 2026 — Daily Preview

A static single-page web app that shows the day's and next day's 2026 FIFA
World Cup matches in your local timezone (default `America/Chicago`).
Auto-updates three times a day via GitHub Actions; deployed on GitHub Pages.

## Live

https://hanyunfan.github.io/hermes/world-cup-2026/

## How it works

```
ESPN scoreboard API
        ↓
scripts/fetch_matches.py  ─── GH Actions (cron, 3×/day) ─── commits data/matches.json
        ↓
data/matches.json
        ↓
index.html + app.js + style.css  ─── GH Pages ─── static delivery
```

- **Data source:** ESPN's public scoreboard API (no key, CORS-friendly).
  Endpoint: `https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard`
- **Schedule:** three refreshes per day (07:00 / 16:00 / 22:00 CDT) — covers
  morning, evening, and final scores. Also runs on `workflow_dispatch` for
  manual refresh.
- **Timezone:** all times in `matches.json` are pre-converted to the
  configured tz; the page header shows the active zone.
- **Refresh:** the page re-fetches `data/matches.json` every 5 minutes and
  caches in `sessionStorage` for instant nav.

## Local development

```bash
cd world-cup-2026
python3 scripts/fetch_matches.py --tz America/Chicago
python3 -m http.server 8000
# open http://localhost:8000/
```

## Layout

```
world-cup-2026/
├── index.html            # single page, templates inline
├── app.js                # data loader + renderer
├── style.css             # dark theme
├── data/
│   └── matches.json      # auto-generated, do not edit
├── scripts/
│   └── fetch_matches.py  # ESPN → normalized JSON
└── .github/workflows/
    ├── fetch-matches.yml # daily refresh
    └── pages.yml         # deploy to GH Pages
```

## Schema (v1)

```jsonc
{
  "schema_version": 1,
  "generated_at": "ISO-8601 UTC",
  "timezone": "America/Chicago",
  "now_local": "ISO-8601 with offset",
  "tournament": {
    "name": "FIFA World Cup 2026",
    "host": "USA / Canada / Mexico",
    "dates": "Jun 11 – Jul 19, 2026",
    "edition": "23rd"
  },
  "days": [
    {
      "date": "2026-06-11",
      "label": "Today" | "Tomorrow",
      "match_count": 2,
      "matches": [
        {
          "id": "760415",
          "kickoff_utc": "2026-06-11T19:00:00+00:00",
          "kickoff_local": "2026-06-11T14:00:00-05:00",
          "kickoff_time": "2:00 PM",
          "status": "FINAL" | "LIVE" | "SCHEDULED",
          "stage": "Group Stage",
          "home": { "name": "Mexico", "flag": "🇲🇽", "logo": "...", "score": 2 },
          "away": { "name": "South Africa", "flag": "🇿🇦", "logo": "...", "score": 0 },
          "venue": { "name": "Estadio Banorte", "city": "Mexico City", "country": "Mexico" },
          "broadcasts": ["FOX", "Tele", "Peacock"],
          "espn_url": "https://www.espn.com/soccer/match/_/gameId/.../...",
          "fox_url": "https://www.foxsports.com/search?q=..."
        }
      ]
    }
  ]
}
```
