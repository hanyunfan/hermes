#!/usr/bin/env python3
"""
Pollen Report Scraper - Linux Version
Geocodes a street address via Nominatim (OpenStreetMap) to get lat/lng/zip,
then fetches pollen data from AccuWeather + pollen.com.

Data sources:
  1. GPS (pollencount.app / AccuWeather): lat/lng based
  2. ZIP  (pollen.com via CDP): species-level data for the resolved ZIP code

Usage:
  python3 scrape.py [--address "Spicewood Elementary School, Austin TX 78750"]
  python3 scrape.py --detect-ip        # use IP-based detection instead of address
  python3 scrape.py --output FILE --html FILE
  python3 scrape.py --test
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# ─── Defaults ─────────────────────────────────────────────────────────────────────
DEFAULT_ADDRESS = "Spicewood Elementary School, Austin TX 78750"
# Actual GPS of Spicewood Elementary School (from Nominatim)
DEFAULT_LAT = 30.4446283
DEFAULT_LNG = -97.8039171
DEFAULT_ZIP = "78750"
DEFAULT_CITY = "Austin, Travis County"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "pollen-data.json")
DEFAULT_HTML = os.path.join(DATA_DIR, "today.html")
ZIP_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pollen_com_pw.py")


# ─── Address Geocoding ──────────────────────────────────────────────────────────

def geocode_address(address):
    """Convert a street address to lat/lng/zip via Nominatim (OpenStreetMap).
    Returns dict with lat, lng, zip, city, display_name on success; None on failure.
    Rate-limited: max 1 req/sec (Nominatim policy).
    """
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": address,
            "format": "json",
            "limit": "1",
            "addressdetails": "1",
        })
        req = urllib.request.Request(url, headers={"User-Agent": "PollenReport/1.0 (linux)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            results = json.loads(resp.read().decode())
        if not results:
            print(f"[Geocode] No results for: {address}")
            return None
        r = results[0]
        lat = float(r["lat"])
        lng = float(r["lon"])
        addr = r.get("address", {})
        # Prefer postcode from Nominatim, fallback to "zip" from addressdetails
        zip_code = (
            addr.get("postcode")
            or addr.get("zip")
            or (DEFAULT_ZIP if DEFAULT_ADDRESS == address else "")
        )
        # Build display city
        city_parts = [
            addr.get("city"),
            addr.get("town"),
            addr.get("village"),
            addr.get("municipality"),
            addr.get("county"),
        ]
        city = ", ".join(p for p in city_parts if p) or address
        print(f"[Geocode] {address} → {city} ({lat}, {lng}) ZIP {zip_code}")
        return {
            "lat": lat, "lng": lng,
            "zip": str(zip_code) if zip_code else DEFAULT_ZIP,
            "city": city,
            "display_name": r.get("display_name", ""),
        }
    except Exception as e:
        print(f"[Geocode] Error: {e}")
        return None


def detect_ip_location():
    """Detect lat/lng/zip from current IP via ip-api.com (free, no key needed).
    Falls back to defaults silently.
    """
    try:
        req = urllib.request.Request(
            "http://ip-api.com/json/?fields=status,country,region,regionName,city,zip,lat,lon",
            headers={"User-Agent": "Mozilla/5.0 (PollenReport/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") != "success":
            return None
        lat = data.get("lat")
        lng = data.get("lon")
        zip_code = data.get("zip") or ""
        city = f"{data.get('city', '')}, {data.get('regionName', '')} {zip_code}".strip()
        if lat and lng:
            print(f"[IP Detect] {city} ({lat}, {lng})")
            return {
                "lat": lat, "lng": lng,
                "zip": zip_code or DEFAULT_ZIP,
                "city": city,
            }
    except Exception as e:
        print(f"[IP Detect] Failed: {e}")
    return None


# ─── GPS source: Google Pollen API ─────────────────────────────────────────────────

# Google Pollen API (free tier: 10k req/month) — replaces dead pollencount.app
# Requires a Google Maps API key with Pollen API enabled.
# Get one at: https://console.cloud.google.com/google/maps-apis/start
# Set env var GOOGLE_POLLEN_API_KEY, or edit the key line below.
GOOGLE_POLLEN_URL = "https://pollen.googleapis.com/v1/forecast:lookup"
GOOGLE_POLLEN_KEY = os.environ.get("GOOGLE_POLLEN_API_KEY", "")  # <--- put your key here


def fetch_google_pollen(lat, lng):
    if not GOOGLE_POLLEN_KEY:
        print("Google Pollen API: no API key set (set GOOGLE_POLLEN_API_KEY env var)", file=sys.stderr)
        return None
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "days": 5,
        "languageCode": "en-US",
        "key": GOOGLE_POLLEN_KEY,
    }

    print("Fetching pollen data from Google Pollen API...")
    url = GOOGLE_POLLEN_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PollenReport/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Google Pollen API fetch failed: {e}", file=sys.stderr)
        return None

# ─── Replaced parse_google_pollen function ──────────────────────────────────────

def parse_google_pollen(raw, source_name):
    """Parse Google Pollen API response into the same dict shape as parse_gps_data()."""
    result = {"source": "Google Pollen API", "source_name": source_name}
    try:
        daily_forecasts = raw.get("dailyInfo", [])
        if not daily_forecasts:
            return result

        today = daily_forecasts[0]
        pollen_type_info = today.get("pollenTypeInfo", [])
        # Google uses string codes: "GRASS", "TREE", "WEED", "RAGWEED"
        code_map = {"GRASS": "grass", "TREE": "tree", "WEED": "weed", "RAGWEED": "ragweed"}
        for entry in pollen_type_info:
            code = entry.get("code", "")
            key = code_map.get(code, code.lower())
            index_info = entry.get("indexInfo", {})
            val = index_info.get("value")
            category = index_info.get("category", "")
            if key not in result:  # first entry wins
                result[key] = val
                result[key + "_category"] = category

        reco = today.get("healthRecommendations", [])
        if reco:
            result["headline"] = reco[0]

        # Temperature
        temp_info = today.get("temperatureInfo", {})
        if temp_info:
            result["temp_high"] = temp_info.get("max", {}).get("value") or temp_info.get("max")
            result["temp_low"] = temp_info.get("min", {}).get("value") or temp_info.get("min")

        # 5-day forecast
        result["forecast"] = []
        for day in daily_forecasts[:6]:
            d = day.get("date", {})
            date_str = f"{d.get('year','')}-{d.get('month',''):02d}-{d.get('day',''):02d}"
            temp_day = day.get("temperatureInfo", {})
            pollen_info = day.get("pollenTypeInfo", [])
            tree_val = None
            grass_val = None
            for entry in pollen_info:
                c = entry.get("code", "")
                v = entry.get("indexInfo", {}).get("value")
                if c == "TREE":
                    tree_val = v
                elif c == "GRASS":
                    grass_val = v
            result["forecast"].append({
                "date": date_str,
                "temp_high": (temp_day.get("max", {}).get("value") or temp_day.get("max")) if temp_day else None,
                "tree": tree_val,
                "grass": grass_val,
            })

        return result
    except Exception as e:
        print(f"Google Pollen parse error: {e}", file=sys.stderr)
        return result
# ─── ZIP source: pollen.com via Chrome CDP ──────────────────────────────────────

def fetch_zip_data(zip_code):
    print(f"Fetching ZIP data from pollen.com ({zip_code}) via CDP...")
    if not os.path.exists(ZIP_SCRIPT):
        print(f"  CDP script not found: {ZIP_SCRIPT}")
        return None
    try:
        result = subprocess.run(
            [sys.executable, ZIP_SCRIPT, zip_code],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != "null":
            data = json.loads(result.stdout.strip())
            print("  -> pollen.com CDP: success")
            return data
        else:
            print("  -> pollen.com CDP returned null or failed")
            return None
    except subprocess.TimeoutExpired:
        print("  -> CDP timed out (90s)")
        return None
    except Exception as e:
        print(f"  -> CDP failed: {e}")
        return None


def parse_zip_data(raw, zip_code):
    if raw is None:
        return {}
    result = {"source": "ZIP (pollen.com)", "source_name": f"pollen.com ({zip_code})"}
    if "overall_index" in raw or "top_allergens" in raw:
        result["overall_index"] = raw.get("overall_index")
        result["overall_label"] = raw.get("overall_label", "")
        result["top_allergens"] = raw.get("top_allergens", [])
        result["yesterday"] = raw.get("yesterday", {})
        result["tomorrow"] = raw.get("tomorrow", {})
        return result
    try:
        fc = raw.get("forecast", {})
        today = fc.get("today", fc.get("current", fc))
        if isinstance(today, list):
            today = today[0] if today else {}
        result["tree"] = today.get("Tree", today.get("tree", today.get("TreePollen")))
        result["grass"] = today.get("Grass", today.get("grass", today.get("GrassPollen")))
        result["ragweed"] = today.get("Ragweed", today.get("ragweed"))
        result["mold"] = today.get("Mold", today.get("mold"))
        for k in ["tree_category", "grass_category", "ragweed_category", "mold_category"]:
            v = today.get(k.title().replace("_", ""), today.get(k))
            if v is not None:
                result[k] = v
        result["forecast"] = [
            {"date": d.get("date", d.get("Date", ""))[:10],
             "tree": d.get("Tree", d.get("tree")),
             "grass": d.get("Grass", d.get("grass"))}
            for d in fc.get("extended", [])[:5]
        ]
    except Exception as e:
        print(f"ZIP parse error: {e}", file=sys.stderr)
    return result


# ─── AQI ───────────────────────────────────────────────────────────────────────

def fetch_aqi(lat, lng):
    url = f"https://api.waqi.info/feed/geo:{lat:.4f};{lng:.4f}/?token=demo"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                iaqi = data["data"].get("iaqi", {})
                return {
                    "pm25": iaqi.get("pm25", {}).get("v"),
                    "aqi": data["data"].get("aqi"),
                    "source": "WAQI (World Air Quality Index)",
                }
    except Exception as e:
        print(f"AQI fetch failed: {e}", file=sys.stderr)
    return {"pm25": None, "aqi": None, "source": "unavailable"}


# ─── Report Generation ────────────────────────────────────────────────────────────

CAT_ORDER = {"very high": 0, "high": 1, "moderate": 2, "low": 3, "very low": 4, "": 5}

def severity_pollen(value, category):
    if value is None:
        return "-", "gray"
    cat = (category or "").lower()
    color_map = {
        "very low": "lightgreen", "low": "green",
        "moderate": "yellow", "high": "orange", "very high": "red",
    }
    return category or "-", color_map.get(cat, "gray")


def top_allergens(gps):
    allergens = []
    for key, label in [("tree","Tree"), ("grass","Grass"), ("ragweed","Ragweed"), ("mold","Mold")]:
        val = gps.get(key)
        cat = gps.get(f"{key}_category", "")
        if val is not None:
            _, col = severity_pollen(val, cat)
            allergens.append((label, val, cat, col))
    allergens.sort(key=lambda x: (CAT_ORDER.get(x[2].lower(), 99), -(x[1] or 0)))
    return allergens


def severity_aqi(aqi):
    if aqi is None:
        return "-", "gray"
    if aqi <= 50: return "Good", "green"
    elif aqi <= 100: return "Moderate", "yellow"
    elif aqi <= 150: return "Unhealthy for Sensitive", "orange"
    elif aqi <= 200: return "Unhealthy", "red"
    elif aqi <= 300: return "Very Unhealthy", "purple"
    return "Hazardous", "maroon"


def source_block(data, is_gps=True):
    tag = "GPS" if is_gps else "ZIP"
    tag_class = "gps" if is_gps else "zip"
    loc = data.get("source_name", "Unknown location")
    src = "Google Pollen API" if is_gps else "pollen.com"
    allergen_vals = {k: data.get(k, 0) or 0 for k in ["tree","grass","ragweed","mold"]}
    top_key = max(allergen_vals, key=allergen_vals.get) if any(allergen_vals.values()) else None
    rows_html = ""
    for key, icon in [("tree","🌳"), ("grass","🌾"), ("ragweed","🌼"), ("mold","🍄")]:
        val = data.get(key)
        cat = data.get(f"{key}_category", "")
        cat_disp, col = severity_pollen(val, cat)
        v = val if val is not None else "-"
        star = " ⭐" if key == top_key and val is not None else ""
        rows_html += f"""
            <div class="pollen-row">
                <span class="pollen-name">{icon} {key.title()}{star}</span>
                <div class="pollen-right">
                    <span class="pollen-num">{v}</span>
                    <span class="badge {col}">{cat_disp}</span>
                </div>
            </div>"""
    return f"""
        <div class="source-card">
            <div class="source-header">
                <span class="source-tag {tag_class}">{tag}</span>
                <span class="source-name">{src}</span>
                <span class="source-loc">{loc}</span>
            </div>
            <div class="pollen-rows">{rows_html}
            </div>
        </div>"""


def zip_species_block(zipd):
    if not zipd or not zipd.get("top_allergens"):
        return ""
    allergens = zipd.get("top_allergens", [])
    overall_idx = zipd.get("overall_index")
    overall_lbl = zipd.get("overall_label", "")
    pt_colors = {"Tree":"#1f6feb","Grass":"#238636","Weed":"#d29922","":"#484f58"}
    allergen_rows = ""
    for t in allergens:
        pt = t.get("plantType", "")
        pt_col = pt_colors.get(pt, "#484f58")
        genus = t.get("genus", "")
        allergen_rows += f"""
            <div class="pollen-row">
                <span class="pollen-name">🌿 {t['name']} <span class="species-genus">({genus})</span></span>
                <span class="badge" style="background:{pt_col}">{pt}</span>
            </div>"""
    idx_str = f"{overall_idx}" if overall_idx is not None else "—"
    zip_src_name = zipd.get("source_name", "")
    return f"""
        <div class="source-card">
            <div class="source-header">
                <span class="source-tag zip">ZIP</span>
                <span class="source-name">pollen.com ({zip_src_name.split('(')[-1].rstrip(')')})</span>
            </div>
            <div class="pollen-rows">{allergen_rows}
            </div>
            <div class="zip-overall">
                <span class="zip-idx">{idx_str}</span>
                <span class="zip-lbl">{overall_lbl}</span>
            </div>
            <div class="zip-note">Species breakdown via pollen.com &middot; Today's top allergens</div>
        </div>"""


def generate_html(gps_data, zip_data, aqi, location):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M %Z")
    loc_display = location.get("city", DEFAULT_CITY)
    aqi_val = aqi.get("aqi")
    aqi_cat, aqi_col = severity_aqi(aqi_val)
    allergens = top_allergens(gps_data)
    allergen_rows = ""
    for label, val, cat, col in allergens:
        v = val if val is not None else "-"
        allergen_rows += f"""
            <div class="pollen-row">
                <span class="pollen-name">{label}</span>
                <div class="pollen-right">
                    <span class="pollen-num">{v}</span>
                    <span class="badge {col}">{cat}</span>
                </div>
            </div>"""
    gps_block = source_block(gps_data, is_gps=True)
    if zip_data and zip_data.get("top_allergens"):
        zip_block = zip_species_block(zip_data)
    elif zip_data and zip_data.get("tree") is not None:
        zip_block = source_block(zip_data, is_gps=False)
    else:
        zip_block = """
        <div class="source-card">
            <div class="source-header">
                <span class="source-tag zip">ZIP</span>
                <span class="source-name">pollen.com</span>
                <span class="source-loc">Species data unavailable</span>
            </div>
            <div class="pollen-unavailable">
                <p>pollen.com species data currently unavailable.</p>
            </div>
        </div>"""
    weather = ""
    if gps_data.get("temp_high"):
        weather = f"""
        <div class="card">
            <h2>Today's Weather</h2>
            <div class="weather-row">
                <span class="temp-big">{gps_data["temp_high"]}°F</span>
                <span class="temp-range">/ {gps_data.get("temp_low","?")}°F</span>
                <span class="sun-info">☀️ {gps_data.get("hours_of_sun","?")}h sun</span>
            </div>
            {('<p class="headline">' + gps_data["headline"] + '</p>') if gps_data.get("headline") else ''}
        </div>"""
    fc_rows = ""
    for day in gps_data.get("forecast", []):
        fc_rows += f"""
        <div class="forecast-row">
            <span class="forecast-date">{day.get("date","?")[5:]}</span>
            <span class="forecast-temps">{day.get("temp_low","?")}°–{day.get("temp_high","?")}°F</span>
            <span>🌳 {day.get("tree","?")}</span>
            <span>🌾 {day.get("grass","?")}</span>
        </div>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌿 Pollen Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }}
        .container {{ max-width: 640px; margin: 0 auto; padding: 30px 16px; }}
        h1 {{ font-size: 1.6rem; color: #58a6ff; margin-bottom: 4px; }}
        .timestamp {{ color: #8b949e; font-size: 0.85rem; }}
        .location {{ color: #8b949e; font-size: 0.9rem; margin: 8px 0 24px; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
        .card h2 {{ font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }}
        .source-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 12px; }}
        .source-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 14px; border-bottom: 1px solid #21262d; padding-bottom: 10px; }}
        .source-tag {{ font-size: 0.7rem; padding: 2px 8px; border-radius: 8px; font-weight: 700; }}
        .source-tag.gps {{ background: #1f6feb; }} .source-tag.zip {{ background: #238636; }}
        .source-name {{ font-weight: 700; font-size: 0.95rem; }}
        .source-loc {{ color: #8b949e; font-size: 0.8rem; margin-left: auto; }}
        .pollen-row {{ display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px solid #21262d; }}
        .pollen-row:last-child {{ border-bottom: none; }}
        .pollen-name {{ font-size: 0.95rem; }}
        .pollen-right {{ display: flex; align-items: center; gap: 8px; }}
        .pollen-num {{ font-size: 1.2rem; font-weight: 700; min-width: 36px; text-align: right; }}
        .pollen-unavailable {{ padding: 12px 0; color: #8b949e; font-size: 0.88rem; }}
        .species-genus {{ color: #8b949e; font-size: 0.8rem; font-weight: 400; }}
        .zip-overall {{ display: flex; align-items: center; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #21262d; }}
        .zip-idx {{ font-size: 1.5rem; font-weight: 800; }}
        .zip-lbl {{ color: #8b949e; font-size: 0.85rem; }}
        .zip-note {{ color: #484f58; font-size: 0.75rem; margin-top: 8px; }}
        .badge {{ font-size: 0.68rem; padding: 2px 7px; border-radius: 10px; color: #fff; font-weight: 600; }}
        .lightgreen {{ background: #3fb950; }} .green {{ background: #238636; }}
        .yellow {{ background: #d29922; }} .orange {{ background: #db6d28; }}
        .red {{ background: #da3633; }} .purple {{ background: #8957e5; }}
        .maroon {{ background: #b62324; }} .gray {{ background: #484f58; }}
        .aqi-section {{ display: flex; align-items: center; gap: 16px; }}
        .aqi-num {{ font-size: 2.5rem; font-weight: 800; }}
        .weather-row {{ display: flex; align-items: baseline; gap: 12px; }}
        .temp-big {{ font-size: 2rem; font-weight: 800; }}
        .temp-range {{ color: #8b949e; }}
        .sun-info {{ color: #8b949e; font-size: 0.85rem; }}
        .headline {{ margin-top: 10px; color: #d29922; font-size: 0.9rem; }}
        .forecast-row {{ display: grid; grid-template-columns: 60px 1fr 50px 50px; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 0.9rem; }}
        .forecast-row:last-child {{ border-bottom: none; }}
        .forecast-date {{ color: #8b949e; }}
        .forecast-temps {{ color: #8b949e; }}
        .footer {{ text-align: center; color: #484f58; font-size: 0.8rem; margin-top: 24px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌿 Pollen Report</h1>
        <p class="timestamp">{ts}</p>
        <p class="location">📍 {loc_display}</p>

        <div class="card">
            <h2>🌡️ Key Allergens Today</h2>
            <p style="color:#8b949e;font-size:0.82rem;margin-bottom:12px">Primary outdoor allergens - sorted by severity &nbsp;⭐ = top contributor</p>
            <div class="pollen-rows">{allergen_rows}
            </div>
        </div>

{gps_block}
{zip_block}

        <div class="card">
            <h2>🌬️ Air Quality</h2>
            <div class="aqi-section">
                <span class="aqi-num">{aqi.get("aqi") or "—"}</span>
                <span class="badge {aqi_col}">{aqi_cat}</span>
                {('<span style="color:#8b949e">PM2.5: ' + str(aqi.get("pm25") or "—") + '</span>') if aqi.get("pm25") else ''}
            </div>
        </div>

{weather}

        <div class="card">
            <h2>📅 5-Day Forecast</h2>
            <div class="forecast-row header">
                <span></span><span></span><span>🌳</span><span>🌾</span>
            </div>{fc_rows}
        </div>

        <p class="footer">Sources: Google Pollen API (GPS) + pollen.com (ZIP)</p>
    </div>
</body>
</html>"""


# ─── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pollen Report Scraper — geocodes an address to lat/lng/zip, fetches pollen data"
    )
    parser.add_argument("--address", default=DEFAULT_ADDRESS,
        help="Street address to geocode. Default: Spicewood Elementary School, Austin TX 78750")
    parser.add_argument("--detect-ip", action="store_true",
        help="Use IP-based location detection instead of address geocoding")
    parser.add_argument("--output", default=OUTPUT_JSON, help="Output JSON path")
    parser.add_argument("--html", default=DEFAULT_HTML, help="Output HTML path")
    parser.add_argument("--test", action="store_true", help="Print to stdout")
    args = parser.parse_args()

    # Resolve location
    if args.detect_ip:
        location = detect_ip_location()
        if not location:
            print("[Location] IP detection failed, using default address geocode")
            location = geocode_address(DEFAULT_ADDRESS)
            if not location:
                location = {"lat": DEFAULT_LAT, "lng": DEFAULT_LNG, "zip": DEFAULT_ZIP, "city": DEFAULT_CITY}
    else:
        location = geocode_address(args.address)
        if not location:
            print(f"[Location] Geocode failed for '{args.address}', falling back to default")
            location = geocode_address(DEFAULT_ADDRESS)
            if not location:
                location = {"lat": DEFAULT_LAT, "lng": DEFAULT_LNG, "zip": DEFAULT_ZIP, "city": DEFAULT_CITY}

    lat = location["lat"]
    lng = location["lng"]
    zip_code = location["zip"]

    # Fetch data
    gps_raw = fetch_google_pollen(lat, lng)
    gps_data = parse_google_pollen(gps_raw, location.get("city", DEFAULT_CITY)) if gps_raw else {}
    zip_raw = fetch_zip_data(zip_code)
    zip_data = parse_zip_data(zip_raw, zip_code)
    aqi = fetch_aqi(lat, lng)

    # Build output
    allergens = top_allergens(gps_data)
    top = allergens[0] if allergens else None
    output = {
        "timestamp": datetime.now().isoformat(),
        "location": location.get("city", DEFAULT_CITY),
        "address": args.address if not args.detect_ip else "IP-detected",
        "lat": lat, "lng": lng, "zip": zip_code,
        "gps": gps_data, "zip": zip_data, "aqi": aqi,
        "top_allergen": top[0] if top else None,
        "top_allergen_value": top[1] if top else None,
        "top_allergen_category": top[2] if top else None,
    }
    html = generate_html(gps_data, zip_data, aqi, location)

    if args.test:
        print(json.dumps(output, indent=2))
        print(html)
    else:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        with open(args.html, "w") as f:
            f.write(html)
        print(f"JSON: {args.output}")
        print(f"HTML: {args.html}")


if __name__ == "__main__":
    main()
