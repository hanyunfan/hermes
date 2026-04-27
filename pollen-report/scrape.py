#!/usr/bin/env python3
"""
Pollen Report Scraper - Linux Version
Austin, TX 78750 | lat=30.4403525, lng=-97.81407276

Data source: pollencount.app / AccuWeather API
Endpoint: https://pollencount.app/api/getForecast

Usage:
  python3 scrape.py [--output FILE] [--html FILE]
  python3 scrape.py --test    # dry run, print HTML to stdout
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime

# --- Config ---
GPS_LAT = 30.4403525
GPS_LNG = -97.81407276
ZIP_CODE = "78750"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "pollen-data.json")
DEFAULT_HTML = os.path.join(DATA_DIR, "today.html")

POLLEN_API = f"https://pollencount.app/api/getForecast?lat={GPS_LAT}&lng={GPS_LNG}"
AQI_API = "https://api.waqi.info/feed/geo:30.4403;-97.814/?token=demo"

# --- Data Fetching ---

def fetch_pollen_data():
    """Fetch pollen/weather data from pollencount.app AccuWeather API."""
    print(f"Fetching from pollencount.app API...")
    req = urllib.request.Request(
        POLLEN_API,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PollenReport/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return parse_forecast(data)
    except Exception as e:
        print(f"API fetch failed: {e}", file=sys.stderr)
        return None


def parse_forecast(raw):
    """Parse AccuWeather getForecast response into our data format."""
    result = {}

    # Pollen/air data is in DailyForecasts[0].AirAndPollen
    forecasts = raw.get("DailyForecasts", [])
    if not forecasts:
        return result

    today = forecasts[0]
    air_pollen = today.get("AirAndPollen", [])

    for item in air_pollen:
        name = item.get("Name", "")
        value = item.get("Value")
        category = item.get("Category", "Unknown")

        if name == "AirQuality":
            result["aqi"] = value
            result["aqi_category"] = category
        elif name == "Tree":
            result["tree"] = value
            result["tree_category"] = category
        elif name == "Grass":
            result["grass"] = value
            result["grass_category"] = category
        elif name == "Ragweed":
            result["ragweed"] = value
            result["ragweed_category"] = category
        elif name == "Mold":
            result["mold"] = value
            result["mold_category"] = category
        elif name == "UVIndex":
            result["uv"] = value
            result["uv_category"] = category

    # Weather
    temp = today.get("Temperature", {})
    result["temp_high"] = temp.get("Maximum", {}).get("Value")
    result["temp_low"] = temp.get("Minimum", {}).get("Value")
    result["hours_of_sun"] = today.get("HoursOfSun")
    result["headline"] = raw.get("Headline", {}).get("Text")

    # Forecast summary
    result["forecast"] = []
    for day in forecasts[:5]:
        date_str = day.get("Date", "")[:10]
        air = {i["Name"].lower(): i["Value"] for i in day.get("AirAndPollen", [])}
        result["forecast"].append({
            "date": date_str,
            "tree": air.get("tree"),
            "grass": air.get("grass"),
            "temp_high": day.get("Temperature", {}).get("Maximum", {}).get("Value"),
            "temp_low": day.get("Temperature", {}).get("Minimum", {}).get("Value"),
        })

    return result


def fetch_aqi():
    """Fetch AQI from WAQI (World Air Quality Index project)."""
    try:
        req = urllib.request.Request(
            AQI_API,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                iaqi = data["data"].get("iaqi", {})
                pm25 = iaqi.get("pm25", {}).get("v")
                aqi_val = data["data"].get("aqi")
                return {
                    "pm25": pm25,
                    "aqi": aqi_val,
                    "source": "WAQI / China Embassy"
                }
    except Exception as e:
        print(f"AQI fetch failed: {e}", file=sys.stderr)
    return {"pm25": None, "aqi": None, "source": "unavailable"}


# --- Report Generation ---

def severity_pollen(value, category, max_val=None):
    """Return (label, color_class, level_badge)."""
    if value is None:
        return "—", "gray", None
    cat = category.lower() if category else ""
    color_map = {"low": "green", "moderate": "yellow", "high": "orange", "very high": "red"}
    color = color_map.get(cat, "gray")
    return category, color, value


def severity_aqi(aqi):
    """Return (label, color_class) for AQI."""
    if aqi is None:
        return "—", "gray"
    if aqi <= 50:
        return "Good", "green"
    elif aqi <= 100:
        return "Moderate", "yellow"
    elif aqi <= 150:
        return "Unhealthy for Sensitive", "orange"
    elif aqi <= 200:
        return "Unhealthy", "red"
    elif aqi <= 300:
        return "Very Unhealthy", "purple"
    else:
        return "Hazardous", "maroon"


def generate_html(data, aqi):
    """Generate the HTML pollen report."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M %Z")

    t_cat, t_col, t_val = severity_pollen(data.get("tree"), data.get("tree_category"))
    g_cat, g_col, g_val = severity_pollen(data.get("grass"), data.get("grass_category"))
    r_cat, r_col, r_val = severity_pollen(data.get("ragweed"), data.get("ragweed_category"))
    m_cat, m_col, m_val = severity_pollen(data.get("mold"), data.get("mold_category"))

    uv_val = data.get("uv")
    uv_cat = data.get("uv_category", "")
    aqi_val = aqi.get("aqi")
    aqi_cat, aqi_col = severity_aqi(aqi_val)

    # Build forecast rows
    forecast_rows = ""
    for day in data.get("forecast", []):
        date_str = day.get("date", "?")[5:]  # MM-DD
        tree_v = day.get("tree", "—")
        grass_v = day.get("grass", "—")
        hi = day.get("temp_high", "—")
        lo = day.get("temp_low", "—")
        forecast_rows += f"""
        <div class="forecast-row">
            <span class="forecast-date">{date_str}</span>
            <span class="forecast-temps">{lo}° – {hi}°F</span>
            <span>🌳 {tree_v}</span>
            <span>🌾 {grass_v}</span>
        </div>"""

    # Weather headline
    headline = data.get("headline", "")
    weather_block = ""
    if data.get("temp_high"):
        weather_block = f"""
        <div class="card">
            <h2>Today's Weather</h2>
            <div class="weather-row">
                <span class="temp-big">{data['temp_high']}°F</span>
                <span class="temp-range">/ {data.get('temp_low', '?')}°F</span>
                <span class="sun-info">☀️ {data.get('hours_of_sun', '?')}h sun</span>
            </div>
            {f'<p class="headline">{headline}</p>' if headline else ''}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌿 Austin Pollen Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }}
        .container {{ max-width: 640px; margin: 0 auto; padding: 30px 16px; }}
        h1 {{ font-size: 1.6rem; color: #58a6ff; margin-bottom: 4px; }}
        .timestamp {{ color: #8b949e; font-size: 0.85rem; }}
        .location {{ color: #8b949e; font-size: 0.9rem; margin: 8px 0 24px; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
        .card h2 {{ font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }}
        .pollen-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #21262d; }}
        .pollen-row:last-child {{ border-bottom: none; }}
        .pollen-name {{ font-size: 1rem; }}
        .pollen-right {{ display: flex; align-items: center; gap: 10px; }}
        .pollen-num {{ font-size: 1.3rem; font-weight: 700; min-width: 36px; text-align: right; }}
        .badge {{ font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; color: #fff; font-weight: 600; }}
        .green {{ background: #238636; }} .yellow {{ background: #d29922; }}
        .orange {{ background: #db6d28; }} .red {{ background: #da3633; }}
        .gray {{ background: #484f58; }}
        .aqi-section {{ display: flex; align-items: center; gap: 16px; }}
        .aqi-num {{ font-size: 2.5rem; font-weight: 800; }}
        .forecast-row {{ display: grid; grid-template-columns: 60px 1fr 50px 50px; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 0.9rem; }}
        .forecast-row:last-child {{ border-bottom: none; }}
        .forecast-date {{ color: #8b949e; }}
        .forecast-temps {{ color: #8b949e; }}
        .weather-row {{ display: flex; align-items: baseline; gap: 12px; }}
        .temp-big {{ font-size: 2rem; font-weight: 800; }}
        .temp-range {{ color: #8b949e; }}
        .sun-info {{ color: #8b949e; font-size: 0.85rem; }}
        .headline {{ margin-top: 10px; color: #d29922; font-size: 0.9rem; }}
        .footer {{ text-align: center; color: #484f58; font-size: 0.8rem; margin-top: 24px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌿 Austin Pollen Report</h1>
        <p class="timestamp">{ts}</p>
        <p class="location">📍 10625 Glass Mountain Trl, Austin TX 78750</p>

        <div class="card">
            <h2>Pollen Levels</h2>
            <div class="pollen-row">
                <span class="pollen-name">🌳 Tree</span>
                <div class="pollen-right">
                    <span class="pollen-num">{t_val if t_val is not None else '—'}</span>
                    <span class="badge {t_col}">{t_cat}</span>
                </div>
            </div>
            <div class="pollen-row">
                <span class="pollen-name">🌾 Grass</span>
                <div class="pollen-right">
                    <span class="pollen-num">{g_val if g_val is not None else '—'}</span>
                    <span class="badge {g_col}">{g_cat}</span>
                </div>
            </div>
            <div class="pollen-row">
                <span class="pollen-name">🌼 Ragweed</span>
                <div class="pollen-right">
                    <span class="pollen-num">{r_val if r_val is not None else '—'}</span>
                    <span class="badge {r_col}">{r_cat}</span>
                </div>
            </div>
            <div class="pollen-row">
                <span class="pollen-name">🍄 Mold</span>
                <div class="pollen-right">
                    <span class="pollen-num">{m_val if m_val is not None else '—'}</span>
                    <span class="badge {m_col}">{m_cat}</span>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Air Quality Index</h2>
            <div class="aqi-section">
                <span class="aqi-num">{aqi_val if aqi_val else '—'}</span>
                <div>
                    <div class="badge {aqi_col}" style="font-size:0.85rem;padding:3px 10px;">{aqi_cat}</div>
                    <p style="color:#8b949e;font-size:0.8rem;margin-top:4px">Source: {aqi.get('source', 'N/A')}</p>
                </div>
            </div>
        </div>

        {weather_block}

        <div class="card">
            <h2>5-Day Forecast</h2>
            {forecast_rows}
        </div>

        <p class="footer">pollen-report · Austin TX · hanyunfan/hermes</p>
    </div>
</body>
</html>"""


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Austin TX Daily Pollen Report")
    parser.add_argument("--output", default=OUTPUT_JSON, help="JSON output path")
    parser.add_argument("--html", default=DEFAULT_HTML, help="HTML report output path")
    parser.add_argument("--test", action="store_true", help="Print HTML to stdout")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    # Fetch data
    data = fetch_pollen_data()
    if not data:
        print("ERROR: Could not fetch pollen data", file=sys.stderr)
        data = {}

    aqi = fetch_aqi()

    # Add metadata
    data["timestamp"] = datetime.now().isoformat()
    data["source"] = "pollencount.app (AccuWeather)"
    data["location"] = {"lat": GPS_LAT, "lng": GPS_LNG, "zip": ZIP_CODE}

    # Save JSON
    with open(args.output, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {args.output}")

    # Generate and save HTML
    html = generate_html(data, aqi)
    with open(args.html, "w") as f:
        f.write(html)
    print(f"Saved: {args.html}")

    if args.test:
        print(html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
