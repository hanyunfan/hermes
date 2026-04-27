# 🌿 Pollen Report Scraper (Linux)

Austin, TX 78750 — Daily pollen, mold, and air quality report.

**Source:** pollencount.app (AccuWeather API) + WAQI AQI

## Setup

```bash
cd ~/hermes/pollen-report
pip install -r requirements.txt
mkdir -p data
```

## Usage

```bash
# Generate today's report (saves JSON + HTML)
python3 scrape.py

# Print HTML to stdout
python3 scrape.py --test

# Custom output paths
python3 scrape.py --output mydata.json --html myreport.html
```

## Cron — Daily Email at 7 AM

```bash
crontab -e
# Add:
0 7 * * * /home/frank/hermes/pollen-report/run_daily.sh >> /home/frank/hermes/pollen-report/data/cron.log 2>&1
```

## Files

- `scrape.py` — Main scraper, generates JSON + HTML report
- `run_daily.sh` — Cron wrapper script
- `send_email.py` — Email delivery (SMTP)
- `data/` — JSON + HTML output
- `data/cron.log` — Cron execution log

## Sample Output

```
🌳 Tree:    750 (High)
🌾 Grass:      0 (Low)
🌼 Ragweed:    5 (Low)
🍄 Mold:   3250 (Low)
💨 AQI:       97 (Moderate)
```

## How It Works

1. Calls `pollencount.app/api/getForecast` with GPS coordinates
2. Parses AccuWeather `AirAndPollen` data for tree/grass/ragweed/mold counts
3. Fetches AQI from WAQI (World Air Quality Index) API
4. Generates a dark-themed HTML report

## Requirements

- Python 3.10+
- `requests` or stdlib `urllib`
- Optional: SMTP access for email delivery
