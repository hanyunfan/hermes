#!/usr/bin/env python3
"""
fetch_tournaments.py — Fetch upcoming UTR + USTA tournaments within
HOME_RADIUS_MILES of HOME_ZIP and write data/tournaments.json.

Auth strategy
-------------
UTR (api.utrsports.net) and USTA TennisLink both gate their event listings
behind login. We solve this with Playwright's storage_state: a one-time
manual login dumps cookies+localStorage into scripts/storage_state/, which
is git-ignored. The scraper re-uses that session for months at a time.

If no storage state exists (cold start), the scraper writes an empty
tournaments.json with status="needs_login" so the dashboard knows to
prompt for setup rather than silently failing.

Output schema (data/tournaments.json)
-------------------------------------
{
  "generated_at": "2026-07-20T14:00:00-05:00",
  "home": {"zip": "78750", "lat": 30.549, "lng": -97.7805, "radius_miles": 80},
  "sources": {
    "utr":   {"status": "ok" | "needs_login" | "error", "error": "..."},
    "usta":  {"status": "ok" | "needs_login" | "error", "error": "..."}
  },
  "tournaments": [
    {
      "id": "utr:12345",
      "source": "UTR" | "USTA",
      "name": "Austin Junior Open",
      "level": "Open" | "Level 3" | "Sectional" | ...,
      "start_date": "2026-08-15",
      "end_date": "2026-08-17",
      "venue": "North Austin Tennis Center",
      "city": "Austin",
      "state": "TX",
      "lat": 30.5123,
      "lng": -97.7234,
      "distance_miles": 7.2,
      "registration_deadline": "2026-08-10",
      "registration_url": "https://...",
      "surface": "Hard",
      "singles_draw": 32,
      "doubles_draw": 16,
      "age_division": "18U" | "12U" | ...
    }
  ]
}
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv optional in CI

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
STORAGE = HERE / "storage_state"
DATA.mkdir(parents=True, exist_ok=True)


# ---------- data model ----------

@dataclass
class Tournament:
    id: str
    source: str           # "UTR" | "USTA"
    name: str
    level: str = ""
    start_date: str = ""
    end_date: str = ""
    venue: str = ""
    city: str = ""
    state: str = ""
    lat: float | None = None
    lng: float | None = None
    distance_miles: float | None = None
    registration_deadline: str = ""
    registration_url: str = ""
    surface: str = ""
    age_division: str = ""
    notes: str = ""


# ---------- config ----------

def home() -> dict:
    zip_code = os.getenv("HOME_ZIP", "78750")
    lat = float(os.getenv("HOME_LAT") or 30.5490)
    lng = float(os.getenv("HOME_LNG") or -97.7805)
    radius = float(os.getenv("HOME_RADIUS_MILES") or 80)
    return {"zip": zip_code, "lat": lat, "lng": lng, "radius_miles": radius}


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (lat, lng) tuples."""
    R = 3958.7613
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def within_radius(t: Tournament, h: dict) -> bool:
    if t.lat is None or t.lng is None:
        return False
    return haversine((h["lat"], h["lng"]), (t.lat, t.lng)) <= h["radius_miles"]


# ---------- storage state helper ----------

def storage_state_file(source: str) -> Path:
    return STORAGE / f"{source}.json"


def has_session(source: str) -> bool:
    f = storage_state_file(source)
    if not f.exists():
        return False
    # Sessions are typically valid for months; no in-process expiry check.
    return True


def login_prompt(source: str, url: str) -> None:
    """Print instructions for the user to capture a session."""
    msg = f"""
[{source}] No saved session found. To enable {source} tournament data:

  1. Run a one-time login capture:
        python scripts/capture_session.py {source.lower()}

     This opens a headed browser, you log in manually, and the cookies +
     localStorage are saved to scripts/storage_state/{source.lower()}.json.

  2. The session will be reused on every future run (typically valid
     for 60-90 days before re-auth is required).

  Until then, {source} data will be skipped — the dashboard will show
  tournaments from the OTHER source plus a "needs login" banner.

  Login URL: {url}
"""
    print(msg, file=sys.stderr)


# ---------- UTR scraper ----------

UTR_LOGIN_URL = "https://app.utrsports.net/login"
UTR_EVENTS_URL = "https://app.utrsports.net/events?radiusMiles=80"


def fetch_utr(home_cfg: dict) -> tuple[list[Tournament], str, str | None]:
    if not has_session("utr"):
        login_prompt("UTR", UTR_LOGIN_URL)
        return [], "needs_login", "No saved UTR session — see setup instructions."

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], "error", "playwright not installed (run: pip install -r requirements.txt && playwright install chromium)"

    tournaments: list[Tournament] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=str(storage_state_file("utr")))
            page = ctx.new_page()
            # The events SPA loads tournament data via the v3/events/search API.
            # We let the SPA render and intercept the network response.
            api_responses: list[dict] = []

            def on_response(resp):
                if "/v3/events/search" in resp.url and resp.status == 200:
                    try:
                        api_responses.append(resp.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(UTR_EVENTS_URL, wait_until="networkidle", timeout=60_000)
            # The SPA renders incrementally; give it a few seconds to settle.
            page.wait_for_timeout(5_000)

            # Try to set the search distance by injecting lat/lng into the URL.
            # The SPA's event search is keyed on lat/lng + radiusMiles query params.
            page.goto(
                f"https://app.utrsports.net/events?"
                f"lat={home_cfg['lat']}&lng={home_cfg['lng']}"
                f"&radiusMiles={int(home_cfg['radius_miles'])}",
                wait_until="networkidle",
                timeout=60_000,
            )
            page.wait_for_timeout(8_000)
            browser.close()

        for payload in api_responses:
            for evt in payload.get("events") or payload.get("results") or []:
                t = _parse_utr_event(evt)
                if t:
                    tournaments.append(t)

        return tournaments, "ok", None
    except Exception as e:
        return [], "error", f"{type(e).__name__}: {e}"


def _parse_utr_event(evt: dict) -> Tournament | None:
    """Best-effort parse of one UTR event JSON record. Schema is version-volatile."""
    try:
        loc = evt.get("location") or evt.get("venueLocation") or {}
        lat = loc.get("lat") or (loc.get("latLng") or [None, None])[0]
        lng = loc.get("lng") or (loc.get("latLng") or [None, None])[1]
        start = evt.get("startDate") or evt.get("start_date") or ""
        end = evt.get("endDate") or evt.get("end_date") or start
        deadline = evt.get("registrationDeadline") or evt.get("registration_deadline") or ""
        ev_id = evt.get("id") or evt.get("eventId") or f"utr:{evt.get('name','')}:{start}"
        url = evt.get("url") or evt.get("registrationUrl") or ""
        return Tournament(
            id=f"utr:{ev_id}",
            source="UTR",
            name=evt.get("name") or evt.get("eventName") or "(untitled)",
            level=evt.get("level") or evt.get("eventLevel") or "",
            start_date=start[:10] if isinstance(start, str) else "",
            end_date=end[:10] if isinstance(end, str) else "",
            venue=loc.get("name") or evt.get("venueName") or "",
            city=loc.get("cityName") or loc.get("city") or "",
            state=loc.get("stateAbbr") or loc.get("state") or "",
            lat=float(lat) if lat else None,
            lng=float(lng) if lng else None,
            registration_deadline=deadline[:10] if isinstance(deadline, str) else "",
            registration_url=url,
            surface=evt.get("surface") or "",
            age_division=evt.get("ageDivision") or evt.get("division") or "",
            notes="",
        )
    except Exception:
        return None


# ---------- USTA scraper ----------

USTA_LOGIN_URL = "https://tennislink.usta.com/member/Home.aspx"
USTA_SEARCH_URL = "https://tennislink.usta.com/tournaments/SearchResults.aspx"


def fetch_usta(home_cfg: dict) -> tuple[list[Tournament], str, str | None]:
    if not has_session("usta"):
        login_prompt("USTA", USTA_LOGIN_URL)
        return [], "needs_login", "No saved USTA session — see setup instructions."

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], "error", "playwright not installed"

    tournaments: list[Tournament] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=str(storage_state_file("usta")))
            page = ctx.new_page()
            # TennisLink is ASP.NET WebForms; search uses a POST with __VIEWSTATE.
            # We navigate to the search page, fill the ZIP+radius form, submit,
            # and parse the resulting table.
            page.goto(USTA_SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
            page.fill('input[name*="Zip" i]', home_cfg["zip"])
            try:
                page.select_option('select[name*="Radius" i]', value=str(int(home_cfg["radius_miles"])))
            except Exception:
                pass  # select may not exist; default radius may already apply
            page.click('input[type="submit"][name*="Search" i], button[id*="Search" i]', timeout=10_000)
            page.wait_for_load_state("networkidle", timeout=30_000)

            rows = page.query_selector_all("table#ContentPlaceHolder1_gvResults tr, table[id*='Results'] tr")
            for row in rows[1:]:  # skip header
                cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                if len(cells) < 4:
                    continue
                link_el = row.query_selector("a")
                url = link_el.get_attribute("href") if link_el else ""
                if url and url.startswith("/"):
                    url = f"https://tennislink.usta.com{url}"

                # Cells: [0]=Tournament, [1]=Dates, [2]=Location, [3]=Level, ...
                name = cells[0] if cells else ""
                dates = cells[1] if len(cells) > 1 else ""
                location = cells[2] if len(cells) > 2 else ""
                level = cells[3] if len(cells) > 3 else ""

                start, end = _split_date_range(dates)
                city, state = _split_city_state(location)
                t = Tournament(
                    id=f"usta:{name}:{start}",
                    source="USTA",
                    name=name,
                    level=level,
                    start_date=start,
                    end_date=end,
                    city=city,
                    state=state,
                    registration_url=url or USTA_SEARCH_URL,
                )
                tournaments.append(t)
            browser.close()

        return tournaments, "ok", None
    except Exception as e:
        return [], "error", f"{type(e).__name__}: {e}"


def _split_date_range(s: str) -> tuple[str, str]:
    """'Aug 15-17, 2026' -> ('2026-08-15', '2026-08-17'). Best-effort."""
    s = (s or "").strip()
    if not s:
        return "", ""
    try:
        # Try common formats
        for fmt in ("%b %d-%d, %Y", "%b %d - %d, %Y", "%m/%d/%Y - %m/%d/%Y"):
            try:
                # Replace second date fragment with full date if fmt is single-date
                if "-" in s and "," in s and s.count(",") == 1:
                    # 'Aug 15-17, 2026'
                    month_day, year = s.rsplit(",", 1)
                    md1, md2 = month_day.split("-")
                    start = datetime.strptime(f"{md1.strip()},{year.strip()}", "%b %d, %Y")
                    end = datetime.strptime(f"{md2.strip()},{year.strip()}", "%b %d, %Y")
                    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
                d1, d2 = s.split("-")
                d1 = d1.strip()
                d2 = d2.strip()
                start = datetime.strptime(d1, fmt.split(" - ")[0])
                end = datetime.strptime(d2, fmt.split(" - ")[1])
                return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass
    return s, s


def _split_city_state(s: str) -> tuple[str, str]:
    s = (s or "").strip()
    if "," in s:
        city, _, state = s.rpartition(",")
        return city.strip(), state.strip()
    return s, ""


# ---------- main ----------

def main() -> int:
    cfg = home()
    print(f"[fetch_tournaments] home={cfg}", file=sys.stderr)

    utr_list, utr_status, utr_err = fetch_utr(cfg)
    print(f"[UTR]   status={utr_status} count={len(utr_list)} err={utr_err}", file=sys.stderr)

    usta_list, usta_status, usta_err = fetch_usta(cfg)
    print(f"[USTA]  status={usta_status} count={len(usta_list)} err={usta_err}", file=sys.stderr)

    all_tournaments = utr_list + usta_list

    # Compute distances from home, filter to radius
    annotated: list[Tournament] = []
    for t in all_tournaments:
        if t.lat is not None and t.lng is not None:
            t.distance_miles = round(haversine((cfg["lat"], cfg["lng"]), (t.lat, t.lng)), 1)
            if t.distance_miles > cfg["radius_miles"]:
                continue
        annotated.append(t)

    # Deduplicate (same tournament can show up under both sources)
    seen: dict[str, Tournament] = {}
    for t in annotated:
        key = f"{t.name.lower()}|{t.start_date}|{t.city.lower()}"
        if key not in seen:
            seen[key] = t
    deduped = sorted(
        seen.values(),
        key=lambda t: (t.start_date or "9999-99-99", t.distance_miles or 0),
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "home": cfg,
        "sources": {
            "utr":  {"status": utr_status,  "error": utr_err,  "count": len(utr_list)},
            "usta": {"status": usta_status, "error": usta_err, "count": len(usta_list)},
        },
        "tournaments": [asdict(t) for t in deduped],
    }

    out = DATA / "tournaments.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"[fetch_tournaments] wrote {len(deduped)} tournaments to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())