#!/bin/bash
TOKEN="__REAL_TOKEN_PLACEHOLDER__"
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

# Status strings — pinned to scrape.py gps_status values.
# Lets the message say *why* Google data is missing instead of a generic "GPS down".
gps_status = d.get("gps_status", "ok" if gps_ok else "empty")
GPS_STATUS_NOTES = {
    "ok":          "",  # no extra note when data is present
    "empty":       "no index data returned (Google omits indexInfo when pollen is out of season)",
    "no_key":      "API key not configured (set GOOGLE_POLLEN_API_KEY)",
    "error":       "API call failed (network/HTTP error)",
    "no_daily":    "API responded but no daily forecast in payload",
    "parse_error": "API response could not be parsed",
}
gps_note = GPS_STATUS_NOTES.get(gps_status, "GPS data unavailable")

lines = []
lines.append(f"🌿 <b>Austin Pollen Report</b>")
lines.append(f"📍 {loc}  |  {ts}")
lines.append("")

# Top Allergen: prefer GPS, fall back to ZIP when GPS is empty so the line is
# never blank when *any* source has data. Only show the literal "unavailable"
# when both sources are down.
if top and top != "N/A":
    lines.append(f"<b>⚠️ Top Allergen: {top} ({top_val}/5, {top_cat})</b>")
elif zip_ok:
    zip_top = zip_["top_allergens"][0]
    lines.append(
        f"<b>⚠️ Top Allergen: {zip_top['name']} ({zip_top['plantType']})</b>"
        f"\n  <i>via pollen.com ZIP — Google Pollen API: {gps_note}</i>"
    )
else:
    lines.append(f"<b>⚠️ Top Allergen: unavailable</b>")
    if gps_note:
        lines.append(f"  <i>Google Pollen API: {gps_note}</i>")

lines.append("")

if gps_ok:
    lines.append("🌡️ <b>Key Allergens (Google Pollen API)</b>")
    shown = False
    reported = []  # (val, cat) for categories actually rendered
    for key, label in [("tree","Tree"), ("grass","Grass"), ("weed","Weed")]:
        val = gps.get(key)
        cat = gps.get(f"{key}_category", "?")
        if val is not None:
            lines.append(f"  {label}: {val}/5 {cat_emoji(cat)}")
            shown = True
            reported.append((val, cat))
    if not shown:
        lines.append("  (no data available)")
    elif all(v == 1 and c == "Very Low" for v, c in reported):
        # All reported categories at the API minimum. Distinguish from
        # out-of-season (which would omit indexInfo and show N/A, not 1/5).
        lines.append("  <i>ℹ️ All at minimum (1/5 Very Low). Out-of-season would show as N/A.</i>")
else:
    lines.append("🌡️ <b>Key Allergens (Google Pollen API)</b>")
    # Show the specific reason instead of the generic "GPS data unavailable".
    lines.append(f"  ({gps_note} — see pollen.com below)")

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

# ─── Idempotency guard ──────────────────────────────────────────────────────────
# Cron retry after LLM timeout can fire this script twice within minutes; Telegram
# messages aren't idempotent, so dedupe by content hash of MSG. State lives outside
# the repo to avoid polluting git status.
#
# Hash strategy: hash the JSON *data content* (not the raw file) with volatile
# real-time fields stripped. scrape.py rewrites `timestamp` every run, and AQI
# from WAQI fluctuates every few minutes — neither change makes the message
# substantively different from the user's perspective within a few-minute
# retry window. Two runs seconds apart with unchanged pollen data will share a
# hash and dedupe correctly.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/pollen-report"
LAST_SENT="$STATE_DIR/last_sent.json"
mkdir -p "$STATE_DIR"
MSG_HASH=$(python3 -c "
import json, hashlib, sys
with open('/home/frank/hermes/pollen-report/data/pollen-data.json') as f:
    d = json.load(f)
d.pop('timestamp', None)
d.pop('aqi', None)
sys.stdout.write(hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest())
")

if [ -f "$LAST_SENT" ]; then
    LAST_HASH=$(jq -r '.msg_hash // ""' "$LAST_SENT" 2>/dev/null || true)
    if [ -n "$LAST_HASH" ] && [ "$LAST_HASH" = "$MSG_HASH" ]; then
        LAST_TS=$(jq -r '.ts // "?"' "$LAST_SENT" 2>/dev/null || echo "?")
        echo "Skip: identical message already sent (hash $MSG_HASH, prior ts=$LAST_TS)"
        exit 0
    fi
fi

# Send via Telegram. -f fails on HTTP errors; also parse the JSON body because
# Telegram returns 200 with ok:false on API errors.
RESP=$(curl -sf -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="$CHAT_ID" \
    -d text="$MSG" \
    -d parse_mode="HTML" \
    -d disable_web_page_preview="true")
CURL_EXIT=$?

if [ $CURL_EXIT -ne 0 ] || ! printf '%s' "$RESP" | jq -e '.ok == true' >/dev/null 2>&1; then
    echo "Telegram send failed (curl exit $CURL_EXIT): $RESP" >&2
    exit 1
fi

# Record success only after Telegram confirmed the message.
jq -n --arg ts "$(date -Iseconds)" --arg h "$MSG_HASH" \
    '{ts: $ts, msg_hash: $h}' > "$LAST_SENT"
echo "Sent at $(date) (hash $MSG_HASH)"