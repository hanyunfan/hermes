#!/bin/bash
# Pollen Report - Daily Cron Job
# Run as frank user every morning at 7:00 AM
# Add to crontab: 0 7 * * * /path/to/run_daily.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/data/cron.log"
DATE="$(date '+%Y-%m-%d %H:%M')"

echo "[$DATE] Running pollen report..." >> "$LOG"

cd "$SCRIPT_DIR"

# Run the scraper with OpenClaw browser
python3 scrape.py --gps --html "$SCRIPT_DIR/data/today.html" >> "$LOG" 2>&1

# If email is configured, send the report
if [ -f "$SCRIPT_DIR/send_email.py" ]; then
    python3 send_email.py >> "$LOG" 2>&1
fi

echo "[$DATE] Done." >> "$LOG"
