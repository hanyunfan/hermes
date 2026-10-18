# 🌿 Pollen Report Scraper

Daily pollen allergy report for any US address — geocodes the address to lat/lng/zip, then fetches pollen + air quality data.

**Sources:**
- **AccuWeather** (pollencount.app): tree/grass/ragweed/mold counts + severity categories
- **pollen.com** (via headless Chrome CDP): species-level allergen breakdown (Hickory, Willow, Oak, etc.)
- **WAQI**: Air Quality Index (PM2.5)

## Usage

```bash
# Default — uses built-in default address (10625 Glass Mountain Trl, Austin TX 78750)
python3 scrape.py

# Custom address — any US street address
python3 scrape.py --address "123 Main St, Austin TX 78701"

# IP-based location detection (optional fallback)
python3 scrape.py --detect-ip

# Custom output paths
python3 scrape.py --output mydata.json --html myreport.html

# Print to stdout
python3 scrape.py --test
```

### Three usage modes

| Mode | Command | Description |
|------|---------|-------------|
| **Address (default)** | `--address "10625 Glass Mountain Trl, Austin TX 78750"` | Geocodes address via Nominatim → lat/lng/zip → AccuWeather + pollen.com |
| **IP detection** | `--detect-ip` | Auto-detects current location via ip-api.com (no address needed) |
| **Default address** | Just run `python3 scrape.py` | Uses built-in Austin TX 78750 default without needing to specify |

## How It Works

1. **Geocode** address → lat/lng/zip via [Nominatim (OpenStreetMap)](https://nominatim.openstreetmap.org) (rate-limited 1 req/s)
2. **GPS data** from AccuWeather using lat/lng
3. **Species data** from pollen.com using ZIP code (via headless Chrome CDP)
4. **AQI** from WAQI using lat/lng
5. Falls back to default address if geocoding fails

## Report Features

- **Key Allergens** — Tree 🌳 / Grass 🌾 / Ragweed 🌼 / Mold 🍄 sorted by severity
- **Species Breakdown** — Hickory / Willow / Oak from pollen.com (CDP)
- **AQI** — PM2.5 + Air Quality category
- **5-Day Forecast** — Tree + Grass counts

## Project Structure

```
pollen-report/
├── scrape.py              # Main scraper — address geocoding + data fetch + HTML/JSON output
├── pollen_com_cdp.py      # Chrome CDP species fetcher (ZIP code passed as arg)
├── requirements.txt       # requests + websockets
├── README.md
└── data/
    ├── pollen-data.json    # Structured JSON output
    └── today.html         # HTML report
```

## Setup

```bash
pip install -r requirements.txt
python3 scrape.py
# Open data/today.html in browser
```

## Cron — Daily at 7 AM

Managed by OpenClaw cron job (`e6bfdbad-1b6f-45eb-abbf-8c47239866ff`) — no crontab entry needed.

## Alternative: Google Pollen point report (`google_pollen_report.py`)

A lightweight variant that skips the browser scraping entirely:

- **Google Pollen API** for point-accurate (lat/lng) pollen — no ZIP-level averaging
- **Open-Meteo** for AQI — no key required
- Standard library only, prints a compact graded report (every value as `X/5（等级）`,
  one aligned line per pollen type with its active species in Chinese + English)

```bash
export GOOGLE_POLLEN_API_KEY=...   # key with the Pollen API enabled
python3 google_pollen_report.py
python3 google_pollen_report.py --lat 30.44 --lng -97.80 --label "Austin, TX"
```
