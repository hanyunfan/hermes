#!/usr/bin/env python3
"""
Fetch FIFA World Cup 2026 matches from ESPN and emit a normalized JSON
file scoped to "today" and "tomorrow" in a target local timezone
(defaults to America/Chicago).

Output: data/matches.json

The schema is intentionally small and stable so the static front-end
can render it without a build step.

Usage:
    python3 fetch_matches.py
    python3 fetch_matches.py --tz America/Chicago
    python3 fetch_matches.py --tz Europe/London --out data/matches.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
USER_AGENT = "hermes-world-cup-2026/1.0 (+https://github.com/hanyunfan/hermes)"
DEFAULT_TZ = "America/Chicago"

# ESPN caps the scoreboard endpoint at ~100 events per request. The 2026
# World Cup has 104 matches over 39 days, so we chunk into ~14-day windows.
ESPN_MAX_RANGE_DAYS = 14
ESPN_HARD_CAP_EVENTS = 100


def fetch_events(dates: str, timeout: int = 20) -> list[dict]:
    url = f"{ESPN_BASE}?dates={dates}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    return payload.get("events") or []


def fetch_full_tournament(start_utc: datetime, end_utc: datetime) -> list[dict]:
    """Fetch every match in [start_utc, end_utc] by chunking on
    ESPN_MAX_RANGE_DAYS. If a chunk still hits the hard cap we split it
    further and warn, so the pipeline is robust to future schedule growth.
    """
    seen: dict[str, dict] = {}  # dedupe by event id
    cursor = start_utc
    chunk_size = ESPN_MAX_RANGE_DAYS
    while cursor <= end_utc:
        chunk_end = min(cursor + timedelta(days=chunk_size - 1), end_utc)
        dates_arg = f"{cursor.strftime('%Y%m%d')}-{chunk_end.strftime('%Y%m%d')}"
        events = fetch_events(dates_arg)
        # Hit the cap? Halve the chunk and retry.
        if len(events) >= ESPN_HARD_CAP_EVENTS and (chunk_end - cursor).days > 1:
            if chunk_size <= 1:
                print(
                    f"WARNING: chunk {dates_arg} still at the {ESPN_HARD_CAP_EVENTS} cap "
                    f"after min-size; some matches may be missing.",
                    file=sys.stderr,
                )
            else:
                chunk_size = max(1, chunk_size // 2)
                continue
        for e in events:
            eid = e.get("id")
            if eid is not None:
                seen[eid] = e
        cursor = chunk_end + timedelta(days=1)
        if chunk_size < ESPN_MAX_RANGE_DAYS:
            chunk_size = ESPN_MAX_RANGE_DAYS
    return list(seen.values())


def parse_competitor(comp: dict) -> dict:
    team = comp.get("team") or {}
    score_val = comp.get("score")
    try:
        score_int = int(score_val) if score_val is not None else None
    except (TypeError, ValueError):
        score_int = None
    return {
        "id": team.get("id"),
        "name": team.get("displayName") or team.get("name") or "?",
        "short": team.get("shortDisplayName") or team.get("abbreviation") or "?",
        "abbr": team.get("abbreviation") or "",
        "flag": _flag_for_abbr(team.get("abbreviation") or ""),
        "logo": team.get("logo") or "",
        "color": team.get("color") or "",
        "home_away": comp.get("homeAway"),
        "score": score_int,
        "winner": comp.get("winner"),
    }


def _flag_for_abbr(abbr: str) -> str:
    """Map a few common 2-3 letter FIFA codes to a flag emoji. Falls back
    to the trigram so we always render *something* on the card."""
    if not abbr:
        return "🏳️"
    overrides = {
        "USA": "🇺🇸", "MEX": "🇲🇽", "CAN": "🇨🇦", "BRA": "🇧🇷", "ARG": "🇦🇷",
        "ENG": "🏴", "FRA": "🇫🇷", "GER": "🇩🇪", "ESP": "🇪🇸", "POR": "🇵🇹",
        "ITA": "🇮🇹", "NED": "🇳🇱", "BEL": "🇧🇪", "CRO": "🇭🇷", "URU": "🇺🇾",
        "COL": "🇨🇴", "CHI": "🇨🇱", "JPN": "🇯🇵", "KOR": "🇰🇷", "IRN": "🇮🇷",
        "IRQ": "🇮🇶", "KSA": "🇸🇦", "AUS": "🇦🇺", "NZL": "🇳🇿", "QAT": "🇶🇦",
        "RSA": "🇿🇦", "EGY": "🇪🇬", "GHA": "🇬🇭", "SEN": "🇸🇳", "MAR": "🇲🇦",
        "NGA": "🇳🇬", "CMR": "🇨🇲", "ALG": "🇩🇿", "TUN": "🇹🇳", "CIV": "🇨🇮",
        "COD": "🇨🇩", "CPV": "🇨🇻", "AUT": "🇦🇹", "SUI": "🇨🇭", "DEN": "🇩🇰",
        "SWE": "🇸🇪", "NOR": "🇳🇴", "POL": "🇵🇱", "UKR": "🇺🇦", "SRB": "🇷🇸",
        "WAL": "🏴", "SCO": "🏴", "IRL": "🇮🇪", "TUR": "🇹🇷", "GRE": "🇬🇷",
        "CZE": "🇨🇿", "BIH": "🇧🇦", "SVK": "🇸🇰", "SVN": "🇸🇮", "HUN": "🇭🇺",
        "ROU": "🇷🇴", "BUL": "🇧🇬", "ALB": "🇦🇱", "MKD": "🇲🇰", "MNE": "🇲🇪",
        "GEO": "🇬🇪", "ARM": "🇦🇲", "AZE": "🇦🇿", "ISR": "🇮🇱", "JOR": "🇯🇴",
        "UZB": "🇺🇿", "CHN": "🇨🇳", "HKG": "🇭🇰", "TPE": "🇹🇼", "IND": "🇮🇳",
        "THA": "🇹🇭", "VIE": "🇻🇳", "MAS": "🇲🇾", "IDN": "🇮🇩", "SIN": "🇸🇬",
        "PHI": "🇵🇭", "MYA": "🇲🇲", "CAM": "🇰🇭", "LAO": "🇱🇦", "PLE": "🇵🇸",
        "SYR": "🇸🇾", "LIB": "🇱🇧", "KUW": "🇰🇼", "UAE": "🇦🇪", "OMA": "🇴🇲",
        "BAH": "🇧🇸", "JAM": "🇯🇲", "HAI": "🇭🇹", "CRC": "🇨🇷", "PAN": "🇵🇦",
        "HON": "🇭🇳", "GUA": "🇬🇹", "SLV": "🇸🇻", "NCA": "🇳🇮", "PUR": "🇵🇷",
        "CUB": "🇨🇺", "DOM": "🇩🇴", "TRI": "🇹🇹", "GUY": "🇬🇾", "SUR": "🇸🇷",
        "VEN": "🇻🇪", "ECU": "🇪🇨", "PER": "🇵🇪", "BOL": "🇧🇴", "PAR": "🇵🇾",
        "URG": "🇺🇾",
    }
    return overrides.get(abbr.upper(), "🏳️")


def slugify(s: str) -> str:
    return (
        s.lower()
        .replace("'", "")
        .replace(".", "")
        .replace("ı", "i")
        .replace("ã", "a").replace("á", "a").replace("â", "a").replace("à", "a")
        .replace("é", "e").replace("ê", "e").replace("è", "e")
        .replace("í", "i").replace("î", "i")
        .replace("ó", "o").replace("ô", "o").replace("õ", "o").replace("ò", "o")
        .replace("ú", "u").replace("û", "u").replace("ü", "u")
        .replace("ñ", "n")
        .replace("ć", "c").replace("č", "c")
        .replace("š", "s").replace("ş", "s")
        .replace("ž", "z")
        .replace("đ", "d")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def parse_event(event: dict, tz: ZoneInfo) -> dict | None:
    try:
        kickoff_utc = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None

    kickoff_local = kickoff_utc.astimezone(tz)
    comps = (event.get("competitions") or [])
    if not comps:
        return None
    comp = comps[0]

    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    venue = comp.get("venue") or {}
    venue_address = venue.get("address") or {}
    venue_city = venue_address.get("city") or ""
    venue_country = venue_address.get("country") or ""

    broadcasts: list[str] = []
    for b in comp.get("geoBroadcasts") or []:
        m = (b.get("media") or {}).get("shortName")
        if m and m not in broadcasts:
            broadcasts.append(m)
    if not broadcasts and comp.get("broadcast"):
        broadcasts = [s.strip() for s in comp["broadcast"].split(",") if s.strip()]

    season = (event.get("season") or comp.get("season") or {})
    stage_slug = season.get("slug") or ""
    stage_label = {
        "group-stage": "Group Stage",
        "round-of-32": "Round of 32",
        "round-of-16": "Round of 16",
        "quarterfinals": "Quarterfinals",
        "semifinals": "Semifinals",
        "third-place": "Third Place",
        "final": "Final",
    }.get(stage_slug, stage_slug.replace("-", " ").title() or "World Cup")

    status_obj = (event.get("status") or {}).get("type") or {}
    status_state = (status_obj.get("state") or "").lower()
    status_short = status_obj.get("shortDetail") or status_obj.get("description") or ""
    if status_state == "pre":
        status = "SCHEDULED"
    elif status_state == "in":
        status = "LIVE"
    else:
        status = "FINAL"

    espn_links = event.get("links") or []
    espn_url = ""
    for link in espn_links:
        if (link.get("rel") or [""])[0] == "summary":
            espn_url = link.get("href") or espn_url
    if not espn_url:
        gid = event.get("id")
        if gid:
            a = slugify(away.get("team", {}).get("displayName") or "")
            h = slugify(home.get("team", {}).get("displayName") or "")
            espn_url = f"https://www.espn.com/soccer/match/_/gameId/{gid}/{a}-{h}"

    home_team = parse_competitor(home)
    away_team = parse_competitor(away)

    slug = f"{slugify(away_team['name'])}-at-{slugify(home_team['name'])}"
    fox_query = f"FIFA World Cup 2026 {home_team['name']} vs {away_team['name']}"
    fox_url = f"https://www.foxsports.com/search?q={urllib.parse.quote(fox_query)}"

    return {
        "id": event.get("id"),
        "kickoff_utc": kickoff_utc.isoformat(),
        "kickoff_local": kickoff_local.isoformat(),
        "kickoff_local_date": kickoff_local.date().isoformat(),
        "kickoff_time": kickoff_local.strftime("%-I:%M %p").strip(),
        "kickoff_weekday": kickoff_local.strftime("%a"),
        "status": status,
        "status_short": status_short,
        "stage": stage_label,
        "stage_slug": stage_slug,
        "home": home_team,
        "away": away_team,
        "venue": {
            "name": venue.get("fullName") or venue.get("displayName") or "",
            "city": venue_city,
            "country": venue_country,
        },
        "broadcasts": broadcasts,
        "espn_url": espn_url,
        "fox_url": fox_url,
        "slug": slug,
    }


def build_payload(tz_name: str) -> dict:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today_local = now_local.date()
    tomorrow_local = today_local + timedelta(days=1)

    # Fetch the full World Cup window. 2026 runs Jun 11 – Jul 19, but we
    # also pad ±1 day to absorb any tz wrap-around edge cases.
    start_local = today_local - timedelta(days=1)
    end_local = today_local + timedelta(days=45)  # safely past Jul 19
    start_utc = datetime.combine(start_local, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    end_utc = datetime.combine(end_local, datetime.max.time(), tzinfo=tz).astimezone(timezone.utc)

    raw_events = fetch_full_tournament(start_utc, end_utc)

    parsed: list[dict] = []
    for ev in raw_events:
        m = parse_event(ev, tz)
        if m:
            parsed.append(m)
    parsed.sort(key=lambda m: m["kickoff_utc"])

    # Build one bucket per local-date with a match, in chronological order.
    seen_dates: dict[str, list[dict]] = {}
    for m in parsed:
        seen_dates.setdefault(m["kickoff_local_date"], []).append(m)
    for items in seen_dates.values():
        items.sort(key=lambda m: m["kickoff_utc"])

    def label_for(date_str: str) -> str:
        d = datetime.fromisoformat(date_str).date()
        if d == today_local:
            return "Today"
        if d == tomorrow_local:
            return "Tomorrow"
        return d.strftime("%a")  # Mon, Tue, ...

    days = [
        {
            "date": ds,
            "label": label_for(ds),
            "match_count": len(items),
            "matches": items,
        }
        for ds, items in sorted(seen_dates.items())
    ]

    # Facets for the front-end filter UI.
    # Only real teams (group stage) show up in the team facet; knockout
    # "X Winner" placeholders are filtered out so the picker stays clean.
    team_index: dict[str, dict] = {}
    venue_index: dict[str, dict] = {}
    for m in parsed:
        for side in (m["home"], m["away"]):
            tid = str(side["id"])
            name = side["name"] or ""
            is_placeholder = (
                "Winner" in name
                or "Loser" in name
                or "2nd Place" in name
                or "Third Place" in name
            )
            if is_placeholder:
                continue
            existing = team_index.get(tid)
            if existing is None or m["kickoff_local_date"] < existing["first_seen"]:
                team_index[tid] = {
                    "id": tid,
                    "name": name,
                    "short": side["short"],
                    "abbr": side["abbr"],
                    "flag": side["flag"],
                    "first_seen": m["kickoff_local_date"],
                    "group_count": 0,
                }
            if m["stage_slug"] == "group-stage":
                team_index[tid]["group_count"] += 1
        v = m["venue"]
        if v["name"]:
            key = v["name"]
            venue_index.setdefault(key, {
                "id": key,
                "name": v["name"],
                "city": v["city"],
                "country": v["country"],
                "match_count": 0,
            })
            venue_index[key]["match_count"] += 1

    teams = sorted(team_index.values(), key=lambda t: t["name"])
    venues = sorted(venue_index.values(), key=lambda v: v["name"])

    tournament_start = days[0]["date"] if days else today_local.isoformat()
    tournament_end = days[-1]["date"] if days else today_local.isoformat()

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": tz_name,
        "now_local": now_local.isoformat(),
        "tournament": {
            "name": "FIFA World Cup 2026",
            "host": "USA / Canada / Mexico",
            "dates": "Jun 11 – Jul 19, 2026",
            "edition": "23rd",
            "start": tournament_start,
            "end": tournament_end,
        },
        "facets": {
            "teams": teams,
            "venues": venues,
            "stages": sorted({m["stage_slug"] for m in parsed if m.get("stage_slug")}),
        },
        "days": days,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=DEFAULT_TZ, help="IANA timezone name")
    ap.add_argument("--out", default="data/matches.json", help="output path")
    ap.add_argument("--print", action="store_true", help="print JSON to stdout")
    args = ap.parse_args()

    try:
        payload = build_payload(args.tz)
    except urllib.error.URLError as e:
        print(f"ERROR: failed to fetch ESPN scoreboard: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.print:
        print(text)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        match_count = sum(d["match_count"] for d in payload["days"])
        team_count = len(payload.get("facets", {}).get("teams", []))
        venue_count = len(payload.get("facets", {}).get("venues", []))
        print(
            f"wrote {out} ({match_count} matches across "
            f"{len(payload['days'])} days, {team_count} teams, "
            f"{venue_count} venues, tz={args.tz})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
