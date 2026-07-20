#!/usr/bin/env python3
"""
capture_session.py — One-time login capture for UTR / USTA / ANC.

Usage:
    python scripts/capture_session.py utr
    python scripts/capture_session.py usta
    python scripts/capture_session.py anc

What it does:
  1. Opens a headed Chromium browser.
  2. Navigates to the service's login URL.
  3. You log in manually (including any 2FA).
  4. Press ENTER in the terminal when the dashboard / events page loads.
  5. The script saves cookies + localStorage to scripts/storage_state/<name>.json

The captured session is then reused by fetch_tournaments.py and book_court.py
without ever re-prompting for credentials. Sessions typically last 60-90 days.

Security:
  - The storage_state file contains session cookies and localStorage values.
    It is git-ignored by default (.gitignore lists storage_state/).
  - Never commit it; never share it.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORAGE = HERE / "storage_state"

LOGIN_URLS = {
    "utr":  "https://app.utrsports.net/login",
    "usta": "https://tennislink.usta.com/member/Home.aspx",
    "anc":  "https://anc.apm.activecommunities.com/andersonmill/signin",
}

POST_LOGIN_HINTS = {
    "utr":  "https://app.utrsports.net/",
    "usta": "https://tennislink.usta.com/member/Home.aspx",
    "anc":  "https://anc.apm.activecommunities.com/andersonmill/home",
}


def capture(name: str) -> int:
    if name not in LOGIN_URLS:
        print(f"Unknown service '{name}'. Valid: {', '.join(LOGIN_URLS)}", file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed:\n  pip install -r requirements.txt\n  playwright install chromium", file=sys.stderr)
        return 1

    STORAGE.mkdir(parents=True, exist_ok=True)
    out = STORAGE / f"{name}.json"

    print(f"Opening headed browser to {LOGIN_URLS[name]}")
    print(f"Log in, complete any 2FA, then come back here and press ENTER.")
    print(f"(Session will be saved to {out})\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(LOGIN_URLS[name], wait_until="domcontentloaded", timeout=60_000)

        # Wait for user to finish logging in.
        input(">>> Press ENTER here after login completes <<<\n")

        ctx.storage_state(path=str(out))
        browser.close()

    print(f"\nSaved {out}")
    print("You can now run fetch_tournaments.py / book_court.py without logging in again.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a login session")
    parser.add_argument("service", choices=list(LOGIN_URLS))
    args = parser.parse_args()
    return capture(args.service)


if __name__ == "__main__":
    sys.exit(main())