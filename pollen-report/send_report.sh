#!/bin/bash
TOKEN="8699881677:AAEM_6K6G2JAI5HIlujPY515_o2zPo-a91U"
CHAT_ID="8670077590"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
LOCKFILE="/tmp/pollen_report.lock"

# Ensure only one instance
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Already running"; exit 0; }

# Kill stale scrape.py
pkill -f "python3.*scrape.py" 2>/dev/null
sleep 1

# Load local env (API keys) — not tracked by git
if [ -f "$SCRIPT_DIR/.env.local" ]; then
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env.local"
fi

# Run scraper
cd "$SCRIPT_DIR" || exit
python3 scrape.py

# Build Telegram HTML message from JSON
MSG=$(python3 - <<'PYEOF'
import json, html

with open("/home/frank/hermes/pollen-report/data/pollen-data.json") as f:
    d = json.load(f)

loc = d["location"]
ts = d["timestamp"][:16]
gps = d.get("gps", {}) or {}
aqi = d.get("aqi", {})
zip_ = d.get("zip_data", {}) or {}
top = d.get("top_allergen") or "N/A"
top_val = d.get("top_allergen_value") or "?"
top_cat = d.get("top_allergen_category") or "?"

# AQI color
def cat_emoji(cat):
    return {"Very High": "🔴", "High": "🟠", "Moderate": "🟡", "Low": "🟢", "Very Low": "⚪"}.get(cat, cat)

gps_ok = bool(gps and any(gps.get(k) for k in ["tree", "grass", "weed"]))
zip_ok = bool(zip_ and zip_.get("top_allergens"))

lines = []
lines.append(f"🌿 <b>Austin Pollen Report</b>")
lines.append(f"📍 {loc}  |  {ts}")
lines.append("")

if top != "N/A":
    lines.append(f"<b>⚠️ Top Allergen: {top} ({top_val}/5, {top_cat})</b>")
else:
    lines.append("<b>⚠️ Top Allergen: unavailable (GPS data down)</b>")

lines.append("")

if gps_ok:
    lines.append("🌡️ <b>Key Allergens (Google Pollen API)</b>")
    shown = False
    for key, label in [("tree","Tree"), ("grass","Grass"), ("weed","Weed")]:
        val = gps.get(key)
        cat = gps.get(f"{key}_category", "?")
        if val is not None:
            lines.append(f"  {label}: {val}/5 {cat_emoji(cat)}")
            shown = True
    if not shown:
        lines.append("  (no data available)")
else:
    lines.append("🌡️ <b>Key Allergens (Google Pollen API)</b>")
    lines.append("  (GPS data unavailable — try ZIP source below)")

lines.append("")
lines.append("🌬️ <b>Air Quality</b>")
aqi_val = aqi.get("aqi") or 0
aqi_color = "🟢 Low" if aqi_val <= 50 else "🟡 Moderate" if aqi_val <= 100 else "🟠 Unhealthy for Sensitive" if aqi_val <= 150 else "🔴 Unhealthy"
lines.append(f"  AQI {aqi_val} (PM2.5 {aqi.get('pm25', '?')}) — {aqi_color}")
lines.append("")

if gps.get("temp_high"):
    lines.append("🌤️ <b>Weather</b>")
    lines.append(f"  {gps['temp_high']}°F / {gps.get('temp_low','?')}°F  ☀️ {gps.get('hours_of_sun','?')}h sun")
    lines.append("")

if gps.get("forecast"):
    lines.append("📅 <b>5-Day Forecast</b>")
    for f in gps["forecast"]:
        date = f.get("date","?")[5:]
        tr = f.get("tree")
        gr = f.get("grass")
        tr_cat = f.get("tree_category","")
        gr_cat = f.get("grass_category","")
        tr_str = f"{tr}/5 {tr_cat}" if tr is not None else "?"
        gr_str = f"{gr}/5 {gr_cat}" if gr is not None else "?"
        lines.append(f"  {date}: 🌳{tr_str}  🌾{gr_str}")
    lines.append("")

if zip_ok:
    lines.append("🗺️ <b>pollen.com (ZIP 78750)</b>")
    zip_allergens = ", ".join([f"{a['name']} ({a['plantType']})" for a in zip_["top_allergens"]])
    lines.append(f"  Overall: {zip_.get('overall_index','?')} ({zip_.get('overall_label','?')})")
    lines.append(f"  Top: {zip_allergens}")
else:
    lines.append("🗺️ <b>pollen.com (ZIP 78750)</b>")
    lines.append("  (ZIP data unavailable)")

print("\n".join(lines))
PYEOF
)

# Send via Telegram
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="$CHAT_ID" \
  -d text="$MSG" \
  -d parse_mode="HTML" \
  -d disable_web_page_preview="true"

echo ""
echo "Sent at $(date)"