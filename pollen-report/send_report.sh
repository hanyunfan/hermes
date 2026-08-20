#!/bin/bash
# Resolve script directory first so we can find .env.local
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Load local env (API keys + Telegram token) — not tracked by git
if [ -f "$SCRIPT_DIR/.env.local" ]; then
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/.env.local"
fi

# Validate Telegram token BEFORE doing any work (no point scraping if we can't send)
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    cat >&2 <<EOF
ERROR: TELEGRAM_BOT_TOKEN is not set.

The Telegram bot token must be configured before running this script.
Add it to $SCRIPT_DIR/.env.local:

    export TELEGRAM_BOT_TOKEN="123456:ABC..."

(.env.local is gitignored, so the secret won't leak into git history.)
EOF
    exit 2
fi

# Configuration
CHAT_ID="8670077590"
LOCKFILE="/tmp/pollen_report.lock"

# Lockfile guard — only after we've validated config, so a bad-config run doesn't
# block the next attempt. flock prevents concurrent runs but doesn't dedupe
# sequential retries (idempotency check below handles that).
exec 200>"$LOCKFILE"
flock -n 200 || { echo "Already running"; exit 0; }

# Kill stale scrape.py from a prior interrupted run
pkill -f "python3.*scrape.py" 2>/dev/null
sleep 1

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

# Status strings — pinned to scrape.py gps_status values. Lets the message
# say *why* Google data is missing instead of a generic "GPS down".
# scrape.py: fetch_google_pollen() return values + parse_google_pollen() _status.
gps_status = d.get("gps_status", "ok" if gps_ok else "empty")
GPS_STATUS_NOTES = {
    "ok":           "",  # no extra note when data is present
    "empty":        "no index data returned (Google omits indexInfo when pollen is out of season)",
    "no_key":       "API key not configured (set GOOGLE_POLLEN_API_KEY in .env.local)",
    "auth_error":   "API key invalid, revoked, or lacks Pollen API permission (check GOOGLE_POLLEN_API_KEY)",
    "rate_limit":   "rate limited by Google (HTTP 429, will retry tomorrow)",
    "server_error": "Google server error (5xx)",
    "error":        "API call failed (network/HTTP error)",
    "no_daily":     "API responded but no daily forecast in payload",
    "parse_error":  "API response could not be parsed",
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
# messages aren't idempotent, so dedupe by content hash. State lives outside the
# repo to avoid polluting git status.
#
# Hash strategy: hash the JSON data content (not the raw file) with volatile
# real-time fields stripped. scrape.py rewrites `timestamp` every run, and AQI
# from WAQI fluctuates every few minutes — neither change makes the message
# substantively different from the user's perspective within a few-minute retry
# window. Two runs seconds apart with unchanged pollen data will share a hash
# and dedupe correctly.
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

# ─── Send via Telegram ──────────────────────────────────────────────────────────
# Use -s (NOT -f) so we get the JSON response body even on HTTP errors — Telegram
# returns 200 with {"ok":false, "error_code":N, "description":"..."} on errors,
# so -f would suppress the body and we couldn't distinguish auth/parse/chat errors.
RESP=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="$CHAT_ID" \
    -d text="$MSG" \
    -d parse_mode="HTML" \
    -d disable_web_page_preview="true")
CURL_EXIT=$?

# Parse Telegram JSON response
OK=$(printf '%s' "$RESP" | jq -r '.ok // empty' 2>/dev/null || true)
ERR_CODE=$(printf '%s' "$RESP" | jq -r '.error_code // empty' 2>/dev/null || true)
ERR_DESC=$(printf '%s' "$RESP" | jq -r '.description // empty' 2>/dev/null || true)

if [ "$OK" = "true" ]; then
    : # success — fall through to record
elif [ "$CURL_EXIT" -ne 0 ]; then
    # curl itself failed (DNS, network, TLS) — no Telegram JSON to parse
    echo "Telegram send failed: curl exit $CURL_EXIT (network error)" >&2
    echo "Response (raw): $RESP" >&2
    exit 10
elif [ -n "$ERR_CODE" ]; then
    # Telegram API returned a structured error — categorize for actionable feedback
    case "$ERR_CODE" in
        401|404)
            # Telegram returns 404 for "bot doesn't exist / token invalid format"
            # and 401 for "token valid but revoked / bot was deleted". Both mean
            # the bot token in .env.local is bad.
            echo "Telegram send failed: bot token invalid or revoked (HTTP $ERR_CODE: $ERR_DESC)" >&2
            echo "Check TELEGRAM_BOT_TOKEN in $SCRIPT_DIR/.env.local" >&2
            exit 11
            ;;
        403)
            echo "Telegram send failed: forbidden (HTTP 403: $ERR_DESC)" >&2
            exit 12
            ;;
        400)
            # 400 is the catch-all bad-request category — disambiguate by description
            case "$ERR_DESC" in
                *"chat not found"*)
                    echo "Telegram send failed: chat_id $CHAT_ID not found (HTTP 400)" >&2
                    echo "Verify CHAT_ID matches the Telegram account that should receive reports" >&2
                    exit 13
                    ;;
                *"can't parse entities"*|*"parse"*)
                    echo "Telegram send failed: HTML parse error in message (HTTP 400)" >&2
                    echo "Likely an unescaped & < > in the pollen data; offending excerpt:" >&2
                    echo "  $MSG" | head -c 400 >&2
                    echo >&2
                    exit 14
                    ;;
                *)
                    echo "Telegram send failed: bad request (HTTP 400: $ERR_DESC)" >&2
                    exit 15
                    ;;
            esac
            ;;
        429)
            echo "Telegram send failed: rate limited (HTTP 429: $ERR_DESC)" >&2
            exit 16
            ;;
        *)
            echo "Telegram send failed: HTTP $ERR_CODE: $ERR_DESC" >&2
            exit 17
            ;;
    esac
else
    # Got a response but couldn't parse it as Telegram JSON
    echo "Telegram send failed: unexpected response (curl exit $CURL_EXIT)" >&2
    echo "Response (raw): $RESP" >&2
    exit 18
fi

# Record success only after Telegram confirmed the message.
jq -n --arg ts "$(date -Iseconds)" --arg h "$MSG_HASH" \
    '{ts: $ts, msg_hash: $h}' > "$LAST_SENT"
echo "Sent at $(date) (hash $MSG_HASH)"