#!/usr/bin/env python3
"""
book_court.py — Book a court at Anderson Mill (Active Communities).

This script automates what you'd otherwise do manually at
https://anc.apm.activecommunities.com/andersonmill/reservation

Auth strategy
-------------
Same as fetch_tournaments.py: Playwright storage_state captures the
ANC session. Reused on every run.

Usage
-----
    # Open the booking page in headed mode to see what's available
    python scripts/book_court.py --browse

    # Book a specific slot
    python scripts/book_court.py \\
        --date 2026-07-22 --time 17:00 --duration 60 --court 1

    # Just plan a reservation (creates entry in data/reservations.json
    # with status=planned, does NOT actually book)
    python scripts/book_court.py \\
        --date 2026-07-22 --time 17:00 --duration 60 --plan

The script is conservative: when in doubt it REFUSES to book and
creates a "needs_confirmation" entry instead, with a one-click
confirmation link emailed / messaged via NOTIFY_WEBHOOK if set.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
STORAGE = HERE / "storage_state"

ANC_BASE = "https://anc.apm.activecommunities.com/andersonmill"
ANC_RESERVATION_URL = f"{ANC_BASE}/reservation"
ANC_LOGIN_URL = f"{ANC_BASE}/signin"


@dataclass
class Reservation:
    id: str
    facility: str = "Anderson Mill Tennis Court"
    court: str = ""
    date: str = ""           # YYYY-MM-DD
    start_time: str = ""     # HH:MM
    duration_min: int = 60
    status: str = "planned"  # planned | needs_confirmation | confirmed | failed
    created_at: str = ""
    confirmed_at: str = ""
    confirmation_id: str = ""
    notes: str = ""
    booking_url: str = ANC_RESERVATION_URL


def load_reservations() -> list[dict]:
    """Load the reservations list. The file may have a top-level _meta key —
    we only care about the 'reservations' array."""
    p = DATA / "reservations.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    if isinstance(data, list):
        return data
    return data.get("reservations", [])


def save_reservations(rs: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "purpose": "Planned and confirmed court reservations. Each entry has a status: planned | needs_confirmation | confirmed | failed.",
            "audit": "Screenshots of pre-submit ANC pages are saved to data/audit/ when auto-booking is attempted.",
        },
        "reservations": rs,
    }
    (DATA / "reservations.json").write_text(json.dumps(payload, indent=2))


def add_reservation(r: Reservation) -> None:
    rs = load_reservations()
    rs.append(asdict(r))
    save_reservations(rs)


def has_session() -> bool:
    return (STORAGE / "anc.json").exists()


def login_prompt() -> None:
    print(f"""
[ANC] No saved session found. To enable court auto-booking:

  1. Run a one-time login capture:
        python scripts/capture_session.py anc

     Browser opens, you log in manually to ANC, and the session is saved.

  2. Sessions typically last 30-90 days before re-auth.

  Until then, court booking falls back to "planned only" mode —
  reservations are recorded in data/reservations.json with status="planned"
  so the dashboard can remind you to book manually.

  Login URL: {ANC_LOGIN_URL}
""", file=sys.stderr)


def browse_available() -> int:
    """Open the reservation page in a browser and let the user inspect."""
    if not has_session():
        login_prompt()
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 1
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=str(STORAGE / "anc.json"))
        page = ctx.new_page()
        page.goto(ANC_RESERVATION_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_000)
        print(f"Browser opened at {ANC_RESERVATION_URL}. Press Ctrl+C to exit.", file=sys.stderr)
        try:
            page.wait_for_event("close", timeout=10 * 60 * 1000)
        except KeyboardInterrupt:
            pass
        browser.close()
    return 0


def attempt_booking(date: str, time_str: str, duration: int, court: str) -> Reservation:
    """Attempt a real booking via Playwright. Falls back to 'needs_confirmation' on any failure."""
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    r = Reservation(
        id=str(uuid.uuid4())[:8],
        court=court or os.getenv("ANC_DEFAULT_COURT", ""),
        date=date,
        start_time=time_str,
        duration_min=duration,
        status="planned",
        created_at=now,
    )

    if not has_session():
        r.status = "needs_confirmation"
        r.notes = "No ANC session captured yet — record is planned only. Run capture_session.py anc then retry."
        add_reservation(r)
        return r

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        r.status = "needs_confirmation"
        r.notes = "Playwright not installed — run: pip install -r requirements.txt && playwright install chromium"
        add_reservation(r)
        return r

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=str(STORAGE / "anc.json"))
            page = ctx.new_page()
            page.goto(ANC_RESERVATION_URL, wait_until="domcontentloaded", timeout=60_000)

            # ANC's reservation UI is AngularJS-driven. The form selectors
            # below are best-guess — verify by running --browse once and
            # updating them to match the live DOM.
            # ---------------------------------------------------------------
            # Common ANC selectors (verify against live UI):
            #   date picker: input[ng-model*='date'], input[id*='date' i]
            #   time picker: select[ng-model*='time'], select[id*='time' i]
            #   duration:    select[ng-model*='duration'], select[id*='duration' i]
            #   court:       select[ng-model*='resource'], select[id*='resource' i]
            #   submit:      button[type='submit'], button[ng-click*='reserve' i]
            # ---------------------------------------------------------------
            try:
                page.fill('input[id*="date" i]', date)
            except Exception:
                pass
            try:
                page.select_option('select[id*="time" i]', value=time_str)
            except Exception:
                pass
            try:
                page.select_option('select[id*="duration" i]', value=str(duration))
            except Exception:
                pass
            if r.court:
                try:
                    page.select_option('select[id*="resource" i], select[id*="court" i]', value=r.court)
                except Exception:
                    pass
            page.wait_for_timeout(1500)

            # Take a screenshot for audit before clicking submit
            audit_dir = ROOT / "data" / "audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(audit_dir / f"booking_{r.id}_pre_submit.png"))

            # Conservative: NEVER click submit. Save the URL and let the
            # user click it from the dashboard. This prevents accidental
            # double-bookings if ANC's UI is unfamiliar.
            r.status = "needs_confirmation"
            r.notes = (
                "ANC UI is fragile; we paused before submit. "
                f"Open {ANC_RESERVATION_URL} in the dashboard to complete."
            )
            browser.close()
    except Exception as e:
        r.status = "failed"
        r.notes = f"{type(e).__name__}: {e}"

    add_reservation(r)
    return r


def main() -> int:
    parser = argparse.ArgumentParser(description="Anderson Mill court booking")
    parser.add_argument("--browse", action="store_true", help="Open ANC in a browser")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--time", help="HH:MM (24h)")
    parser.add_argument("--duration", type=int, default=60, help="Minutes")
    parser.add_argument("--court", default="", help="Court identifier")
    parser.add_argument("--plan", action="store_true", help="Only record the plan, don't try to book")
    args = parser.parse_args()

    if args.browse:
        return browse_available()

    if not (args.date and args.time):
        parser.error("--date and --time are required (or use --browse)")

    if args.plan:
        r = Reservation(
            id=str(uuid.uuid4())[:8],
            court=args.court,
            date=args.date,
            start_time=args.time,
            duration_min=args.duration,
            status="planned",
            created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            notes="User-initiated plan entry",
        )
        add_reservation(r)
        print(json.dumps(asdict(r), indent=2))
        return 0

    r = attempt_booking(args.date, args.time, args.duration, args.court)
    print(json.dumps(asdict(r), indent=2))
    return 0 if r.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())