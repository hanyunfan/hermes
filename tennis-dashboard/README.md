# 🎾 Tennis Training Dashboard

A single-page dashboard for managing a junior tennis player's training:

1. **Court booking** at Anderson Mill (Active Communities, formerly "PerfectMind")
2. **Tournament discovery** — UTR + USTA events within 80 mi of ZIP **78750**

The dashboard is fully static (HTML/CSS/JS) and works as a GitHub Pages site.
Live data is refreshed by a daily GitHub Actions cron that runs the Python
fetchers in this repo.

```
tennis-dashboard/
├── index.html                 # the dashboard
├── style.css
├── app.js                     # UI logic, filters, status chips
├── data/
│   ├── tournaments.json       # UTR + USTA listings (refreshed daily)
│   └── reservations.json      # court booking history
├── scripts/
│   ├── fetch_tournaments.py   # UTR + USTA scraper (Playwright)
│   ├── book_court.py          # ANC auto-booker (Playwright)
│   ├── capture_session.py     # one-time login capture helper
│   └── geocode_zip.py         # ZIP → lat/lng (Census API + fallback table)
├── .github/workflows/
│   └── daily-fetch.yml        # 6am Central daily refresh
├── .env.example
├── requirements.txt
└── README.md
```

## Why this design

UTR (`api.utrsports.net`), USTA TennisLink (`tennislink.usta.com`), and
Active Communities (`anc.apm.activecommunities.com`) **all gate their event
listings behind login**. There is no public read API for tournament data in
the radius around 78750.

The honest, working approach:

1. **One-time login capture** — you log in to each service once in a real
   browser. We save the resulting cookies+localStorage as a
   Playwright `storage_state` file (git-ignored). This is the same mechanism
   that powers most production-grade scraping pipelines.
2. **Headless Playwright scraper** runs daily via GitHub Actions,
   re-using the captured session. Sessions typically last 60-90 days
   before re-auth is required.
3. **Court booking is conservative**: the auto-booker stages reservations
   (writes to `data/reservations.json` with `status="needs_confirmation"`)
   but **never clicks Submit on its own**. The final click is yours.

## Quick start (local)

```bash
# 1. Install
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# edit .env: set HOME_ZIP=78750 and the radius

# 3. One-time login capture (headed browser, you log in manually)
python scripts/capture_session.py utr
python scripts/capture_session.py usta
python scripts/capture_session.py anc

# 4. Refresh tournament data
python scripts/fetch_tournaments.py

# 5. Plan or book a court
python scripts/book_court.py --browse               # opens ANC in real browser
python scripts/book_court.py --date 2026-07-22 --time 17:00 --duration 60 --plan
python scripts/book_court.py --date 2026-07-22 --time 17:00 --duration 60
```

## CLI reference

| Command | What it does |
| --- | --- |
| `python scripts/fetch_tournaments.py` | Re-fetches UTR + USTA tournaments, writes `data/tournaments.json` |
| `python scripts/book_court.py --browse` | Opens ANC reservation page in a real browser |
| `python scripts/book_court.py --date YYYY-MM-DD --time HH:MM --duration 60 --plan` | Records a plan entry only |
| `python scripts/book_court.py --date YYYY-MM-DD --time HH:MM --duration 60` | Stages a real reservation (no submit) |
| `python scripts/capture_session.py {utr,usta,anc}` | One-time login capture |
| `python scripts/geocode_zip.py 78750` | Quick ZIP→coords sanity check |

## Security

- **Never commit `.env`** or `scripts/storage_state/*.json`. Both are
  git-ignored. Sessions contain authentication cookies equivalent to
  passwords — treat them accordingly.
- The scraper only reads tournament listing data; it never mutates UTR /
  USTA accounts.
- Court booking is intentionally a "staging" operation. To book for real,
  open the ANC link from the reservation entry in the dashboard and click
  submit yourself.

## How the daily refresh works

`.github/workflows/daily-fetch.yml` runs at **6am Central** every day:

```
.                       Run fetch_tournaments.py
.                       Validate JSON output
.                       Commit & push data/tournaments.json
```

Note: GitHub Actions runners don't have your personal UTR / USTA sessions,
so on CI the fetcher will record `status="needs_login"` and a warning
banner appears on the dashboard until you run the fetcher locally at
least once and commit the initial `tournaments.json`. (The CI cron still
helps by validating the schema and keeping the pipeline healthy — the
real data refresh is local.)

**Future improvement**: store Playwright storage_state as a GitHub Actions
encrypted secret, then the cron can refresh real data too. Out of scope
for v1.

## Data sources

| Source | Coverage | Auth | Status |
| --- | --- | --- | --- |
| UTR (Universal Tennis) | Junior + adult tennis events, UTR-rated | Login (one-time capture) | `needs_login` until captured |
| USTA TennisLink | Sanctioned USTA tournaments, all sections | Login (one-time capture) | `needs_login` until captured |
| Anderson Mill (ANC) | Court reservations | Login (one-time capture) | `needs_login` until captured |

## License

MIT — same as the rest of the hermes/ portfolio.