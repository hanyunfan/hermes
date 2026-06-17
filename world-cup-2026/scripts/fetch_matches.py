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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/fifa.world/standings"
USER_AGENT = "hermes-world-cup-2026/1.0 (+https://github.com/hanyunfan/hermes)"
DEFAULT_TZ = "America/Chicago"

# Tournament calendar — hard-coded so we always fetch the full
# window (including the opening match on day 1, which a rolling
# "today - 1" window would skip once we're days into the event).
TOURNAMENT_START = date(2026, 6, 11)
TOURNAMENT_END = date(2026, 7, 19)

# ESPN's public scoreboard API is English-only (displayName,
# shortDisplayName, abbreviation) — it carries no localized name.
# The 48 WC 2026 nations are well-known, so we ship a hand-curated
# 中文 mapping and surface it as `name_zh` on every team dict.
# Front-end swaps primary name based on the active language toggle.
# Knockout placeholders ("Group A Winner", etc.) intentionally have
# no entry here — they fall back to the English placeholder string.
COUNTRY_ZH = {
    "Algeria": "阿尔及利亚",
    "Argentina": "阿根廷",
    "Australia": "澳大利亚",
    "Austria": "奥地利",
    "Belgium": "比利时",
    "Bosnia-Herzegovina": "波黑",
    "Brazil": "巴西",
    "Canada": "加拿大",
    "Cape Verde": "佛得角",
    "Colombia": "哥伦比亚",
    "Congo DR": "刚果（金）",
    "Croatia": "克罗地亚",
    "Curaçao": "库拉索",
    "Czechia": "捷克",
    "Ecuador": "厄瓜多尔",
    "Egypt": "埃及",
    "England": "英格兰",
    "France": "法国",
    "Germany": "德国",
    "Ghana": "加纳",
    "Haiti": "海地",
    "Iran": "伊朗",
    "Iraq": "伊拉克",
    "Ivory Coast": "科特迪瓦",
    "Japan": "日本",
    "Jordan": "约旦",
    "Mexico": "墨西哥",
    "Morocco": "摩洛哥",
    "Netherlands": "荷兰",
    "New Zealand": "新西兰",
    "Norway": "挪威",
    "Panama": "巴拿马",
    "Paraguay": "巴拉圭",
    "Portugal": "葡萄牙",
    "Qatar": "卡塔尔",
    "Saudi Arabia": "沙特阿拉伯",
    "Scotland": "苏格兰",
    "Senegal": "塞内加尔",
    "South Africa": "南非",
    "South Korea": "韩国",
    "Spain": "西班牙",
    "Sweden": "瑞典",
    "Switzerland": "瑞士",
    "Tunisia": "突尼斯",
    "Türkiye": "土耳其",
    "United States": "美国",
    "Uruguay": "乌拉圭",
    "Uzbekistan": "乌兹别克斯坦",
}


def _name_zh(english: str) -> str:
    """Look up the Chinese display name for an ESPN team name.
    Returns "" for unknowns (knockout placeholders, future qualifiers)
    so the front-end can fall back to the English string."""
    return COUNTRY_ZH.get(english or "", "")


# All-time FIFA World Cup top scorers (men's, final tournament only —
# does not include qualifiers). Snapshot as of the end of the 2022
# tournament in Qatar, before WC 2026 kicks off. Verified against
# FIFA's official "All-time World Cup goal scorers" record.
#
# Each entry:
#   rank        — all-time rank by total goals (ties broken by span,
#                 then alphabetical for clarity in the front-end)
#   player      — display name in English (commonly used form)
#   player_zh   — Chinese display name (kept short; surnames suffice)
#   country     — nation represented in WC play (English)
#   country_zh  — Chinese name for that nation
#   flag        — emoji flag for the country
#   goals       — total WC tournament goals (1930–2022, final tournament)
#   tournaments — list of years the player appeared in the final tournament
#                 where they scored (subset of their WC appearances)
#   span        — first/last WC year with the player in the squad
#                 (covers all their WC appearances, including scoreless ones)
#
# Static data — no need to refetch; baked into matches.json so the
# Scorers tab renders from the same single blob the rest of the app
# already loads.
HISTORICAL_SCORERS = [
    {"rank": 1,  "player": "Miroslav Klose",     "player_zh": "克洛泽",     "country": "Germany",            "country_zh": "德国",   "flag": "🇩🇪", "goals": 16, "tournaments": [2002, 2006, 2010, 2014], "span": "2002–2014"},
    {"rank": 2,  "player": "Ronaldo",            "player_zh": "罗纳尔多",   "country": "Brazil",             "country_zh": "巴西",   "flag": "🇧🇷", "goals": 15, "tournaments": [1998, 2002, 2006],       "span": "1994–2006"},
    {"rank": 3,  "player": "Gerd Müller",        "player_zh": "盖德·穆勒",   "country": "West Germany",       "country_zh": "西德",   "flag": "🇩🇪", "goals": 14, "tournaments": [1970, 1974],             "span": "1970–1974"},
    {"rank": 4,  "player": "Just Fontaine",      "player_zh": "方丹",       "country": "France",             "country_zh": "法国",   "flag": "🇫🇷", "goals": 13, "tournaments": [1958],                   "span": "1958"},
    {"rank": 5,  "player": "Lionel Messi",       "player_zh": "梅西",       "country": "Argentina",          "country_zh": "阿根廷", "flag": "🇦🇷", "goals": 13, "tournaments": [2006, 2010, 2014, 2018, 2022], "span": "2006–2022"},
    {"rank": 6,  "player": "Kylian Mbappé",      "player_zh": "姆巴佩",     "country": "France",             "country_zh": "法国",   "flag": "🇫🇷", "goals": 12, "tournaments": [2018, 2022],             "span": "2018–2022"},
    {"rank": 7,  "player": "Pelé",               "player_zh": "贝利",       "country": "Brazil",             "country_zh": "巴西",   "flag": "🇧🇷", "goals": 12, "tournaments": [1958, 1962, 1966, 1970], "span": "1958–1970"},
    {"rank": 8,  "player": "Sándor Kocsis",      "player_zh": "柯奇什",     "country": "Hungary",            "country_zh": "匈牙利", "flag": "🇭🇺", "goals": 11, "tournaments": [1954],                   "span": "1954"},
    {"rank": 9,  "player": "Jürgen Klinsmann",   "player_zh": "克林斯曼",   "country": "Germany",            "country_zh": "德国",   "flag": "🇩🇪", "goals": 11, "tournaments": [1990, 1994, 1998],       "span": "1990–1998"},
    {"rank": 10, "player": "Helmut Rahn",        "player_zh": "拉恩",       "country": "West Germany",       "country_zh": "西德",   "flag": "🇩🇪", "goals": 10, "tournaments": [1954, 1958],             "span": "1954–1958"},
    {"rank": 11, "player": "Gary Lineker",       "player_zh": "莱因克尔",   "country": "England",            "country_zh": "英格兰", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "goals": 10, "tournaments": [1986, 1990],       "span": "1986–1990"},
    {"rank": 12, "player": "Gabriel Batistuta",  "player_zh": "巴蒂斯图塔", "country": "Argentina",          "country_zh": "阿根廷", "flag": "🇦🇷", "goals": 10, "tournaments": [1994, 1998, 2002],       "span": "1994–2002"},
    {"rank": 13, "player": "Teófilo Cubillas",   "player_zh": "库比拉斯",   "country": "Peru",               "country_zh": "秘鲁",   "flag": "🇵🇪", "goals": 10, "tournaments": [1970, 1978],             "span": "1970–1978"},
    {"rank": 14, "player": "Thomas Müller",      "player_zh": "穆勒",       "country": "Germany",            "country_zh": "德国",   "flag": "🇩🇪", "goals": 10, "tournaments": [2010, 2014, 2018],       "span": "2010–2018"},
    {"rank": 15, "player": "Vavá",               "player_zh": "瓦瓦",       "country": "Brazil",             "country_zh": "巴西",   "flag": "🇧🇷", "goals": 9,  "tournaments": [1958, 1962],             "span": "1958–1962"},
    {"rank": 16, "player": "Eusébio",            "player_zh": "尤西比奥",   "country": "Portugal",           "country_zh": "葡萄牙", "flag": "🇵🇹", "goals": 9,  "tournaments": [1966],                   "span": "1966"},
    {"rank": 17, "player": "Karl-Heinz Rummenigge","player_zh": "鲁梅尼格", "country": "West Germany",       "country_zh": "西德",   "flag": "🇩🇪", "goals": 9,  "tournaments": [1978, 1982, 1986],       "span": "1978–1986"},
    {"rank": 18, "player": "Roberto Baggio",     "player_zh": "巴乔",       "country": "Italy",              "country_zh": "意大利", "flag": "🇮🇹", "goals": 9,  "tournaments": [1990, 1994, 1998],       "span": "1990–1998"},
    {"rank": 19, "player": "David Villa",        "player_zh": "比利亚",     "country": "Spain",              "country_zh": "西班牙", "flag": "🇪🇸", "goals": 9,  "tournaments": [2006, 2010, 2014],       "span": "2006–2014"},
    {"rank": 20, "player": "Paolo Rossi",       "player_zh": "罗西",       "country": "Italy",              "country_zh": "意大利", "flag": "🇮🇹", "goals": 9,  "tournaments": [1978, 1982, 1986],       "span": "1978–1986"},
    {"rank": 21, "player": "Christian Vieri",    "player_zh": "维埃里",     "country": "Italy",              "country_zh": "意大利", "flag": "🇮🇹", "goals": 9,  "tournaments": [1998, 2002],             "span": "1998–2002"},
    {"rank": 22, "player": "Neymar",             "player_zh": "内马尔",     "country": "Brazil",             "country_zh": "巴西",   "flag": "🇧🇷", "goals": 8,  "tournaments": [2014, 2018, 2022],       "span": "2014–2022"},
    {"rank": 23, "player": "Andriy Shevchenko",  "player_zh": "舍甫琴科",   "country": "Ukraine",            "country_zh": "乌克兰", "flag": "🇺🇦", "goals": 8,  "tournaments": [2006],                   "span": "2006"},
    {"rank": 24, "player": "Rivaldo",            "player_zh": "里瓦尔多",   "country": "Brazil",             "country_zh": "巴西",   "flag": "🇧🇷", "goals": 8,  "tournaments": [1998, 2002],             "span": "1998–2002"},
    {"rank": 25, "player": "Óscar Míguez",       "player_zh": "米格斯",     "country": "Uruguay",            "country_zh": "乌拉圭", "flag": "🇺🇾", "goals": 8,  "tournaments": [1950, 1954],             "span": "1950–1954"},
]


# FIFA/Coca-Cola Men's World Ranking snapshot. ESPN's scoreboard API
# has no ranking field, so we ship a snapshot hard-coded here. Update
# FIFA_RANK_SNAPSHOT whenever this dict is refreshed — FIFA publishes
# updated rankings monthly. The front-end renders this as a small
# `#N` annotation next to each team name; missing values render nothing.
FIFA_RANK_SNAPSHOT = date(2026, 6, 11)
FIFA_RANK = {
    "Algeria": 28,
    "Argentina": 1,
    "Australia": 27,
    "Austria": 24,
    "Belgium": 9,
    "Bosnia-Herzegovina": 64,
    "Brazil": 6,
    "Canada": 30,
    "Cape Verde": 67,
    "Colombia": 13,
    "Congo DR": 46,
    "Croatia": 11,
    "Curaçao": 82,
    "Czechia": 40,
    "Ecuador": 23,
    "Egypt": 29,
    "England": 4,
    "France": 3,
    "Germany": 10,
    "Ghana": 73,
    "Haiti": 83,
    "Iran": 20,
    "Iraq": 57,
    "Ivory Coast": 33,
    "Japan": 18,
    "Jordan": 63,
    "Mexico": 14,
    "Morocco": 7,
    "Netherlands": 8,
    "New Zealand": 85,
    "Norway": 31,
    "Panama": 34,
    "Paraguay": 41,
    "Portugal": 5,
    "Qatar": 56,
    "Saudi Arabia": 61,
    "Scotland": 42,
    "Senegal": 15,
    "South Africa": 60,
    "South Korea": 25,
    "Spain": 2,
    "Sweden": 38,
    "Switzerland": 19,
    "Tunisia": 45,
    "Türkiye": 22,
    "United States": 17,
    "Uruguay": 16,
    "Uzbekistan": 50,
}


def _rank(english: str) -> int | None:
    """FIFA men's world ranking for an ESPN team name, or None when
    the team is a knockout placeholder or a future qualifier not yet
    in our snapshot."""
    return FIFA_RANK.get(english or "")


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


def fetch_standings(timeout: int = 20) -> list[dict]:
    """Fetch group standings (12 groups A–L, 4 teams each).
    Returns a list of group dicts in ESPN's nested shape:
        {"name": "Group A", "abbreviation": "Group A",
         "entries": [{"team": {...}, "stats": [...], "note": {...}}]}"""
    req = urllib.request.Request(ESPN_STANDINGS, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    groups = []
    for child in payload.get("children") or []:
        entries_raw = (child.get("standings") or {}).get("entries") or []
        entries = [_normalize_standing_entry(e) for e in entries_raw]
        # Stable sort: rank, then by points desc as a safety net
        entries.sort(key=lambda e: (e["rank"], -e["pts"], -e["gd"]))
        groups.append({
            "id": child.get("id") or child.get("uid") or "",
            "name": child.get("name") or "",
            "abbreviation": child.get("abbreviation") or child.get("name") or "",
            "entries": entries,
        })
    return groups


def _normalize_standing_entry(entry: dict) -> dict:
    team = entry.get("team") or {}
    by_name = {s.get("name"): s.get("value") for s in (entry.get("stats") or [])}
    note = entry.get("note") or {}
    return {
        "team": {
            "id": str(team.get("id") or ""),
            "name": team.get("displayName") or team.get("name") or "?",
            "name_zh": _name_zh(team.get("displayName") or team.get("name") or ""),
            "rank": _rank(team.get("displayName") or team.get("name") or ""),
            "short": team.get("shortDisplayName") or team.get("abbreviation") or "?",
            "abbr": team.get("abbreviation") or "",
            "flag": _flag_for_abbr(team.get("abbreviation") or ""),
            "logo": ((team.get("logos") or [{}])[0] or {}).get("href") or "",
        },
        "rank": int(by_name.get("rank", 0) or 0),
        "mp": int(by_name.get("gamesPlayed", 0) or 0),
        "w": int(by_name.get("wins", 0) or 0),
        "d": int(by_name.get("ties", 0) or 0),
        "l": int(by_name.get("losses", 0) or 0),
        "gf": int(by_name.get("pointsFor", 0) or 0),
        "ga": int(by_name.get("pointsAgainst", 0) or 0),
        "gd": int(by_name.get("pointDifferential", 0) or 0),
        "pts": int(by_name.get("points", 0) or 0),
        "advance": (by_name.get("advanced", 0) or 0) > 0,
        "advance_label": note.get("description") or "",
        "advance_color": note.get("color") or "",
    }


# ESPN summary `keyEvents` types we care about. Map of API type string ->
# normalized kind. Goals come in as `goal`, `goal---header`, `goal---own`,
# etc. — we treat any type starting with `goal` as a goal.
_KEEP_TYPES = {"yellow-card", "red-card", "substitution"}
_GOAL_PREFIX = "goal"


def _truth_from_summary(payload: dict) -> dict | None:
    """Pull authoritative status + scores out of an ESPN summary payload.

    The summary endpoint is the source of truth — the scoreboard can
    briefly disagree (e.g. stuck at HT 0-0 while keyEvents already
    shows goals from 51'-89'). Returns None if the header is missing.
    """
    header = payload.get("header") or {}
    comps = header.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    st = (comp.get("status") or {}).get("type") or {}
    status_state = (st.get("state") or "").lower()
    status_short = st.get("shortDetail") or st.get("description") or ""
    if status_state == "pre":
        status = "SCHEDULED"
    elif status_state == "in":
        status = "LIVE"
    else:
        status = "FINAL"
    competitors = comp.get("competitors") or []
    h = next((c for c in competitors if c.get("homeAway") == "home"), None)
    a = next((c for c in competitors if c.get("homeAway") == "away"), None)

    def _score(c):
        if not c:
            return None
        v = c.get("score")
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "status": status,
        "status_short": status_short,
        "home_score": _score(h),
        "away_score": _score(a),
    }


def fetch_match_events(event_id: str, home_id: str = "", away_id: str = "") -> dict:
    """Fetch goals / cards / subs for one match via the ESPN summary endpoint.

    Returns:
        {"incidents": [...], "truth": {status, status_short, home_score, away_score} | None}

    The summary endpoint is the source of truth for status + scores (the
    scoreboard can briefly lag during state transitions). On failure we
    return empty incidents + None truth and let the caller carry on.
    """
    url = f"{ESPN_SUMMARY}?event={event_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.load(r)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"  warn: events fetch failed for {event_id}: {exc}", file=sys.stderr)
        return {"incidents": [], "truth": None}

    out: list[dict] = []
    for e in payload.get("keyEvents") or []:
        raw_kind = (e.get("type") or {}).get("type") or ""
        if raw_kind in _KEEP_TYPES:
            kind = raw_kind.replace("-", "_")
        elif raw_kind.startswith(_GOAL_PREFIX):
            kind = "goal"
        else:
            continue  # kickoff / halftime / delay / end-of-half / etc.

        team_obj = e.get("team") or {}
        team_id = str(team_obj.get("id") or "")
        team_name = team_obj.get("displayName") or ""
        if home_id and team_id == str(home_id):
            team_side = "home"
        elif away_id and team_id == str(away_id):
            team_side = "away"
        else:
            team_side = ""

        participants = e.get("participants") or []
        primary = participants[0].get("athlete", {}).get("displayName", "") if participants else ""
        secondary = participants[1].get("athlete", {}).get("displayName", "") if len(participants) > 1 else ""

        incident = {
            "kind": kind,
            "minute": (e.get("clock") or {}).get("displayValue") or "",
            "team": team_name,
            "team_id": team_id,
            "team_side": team_side,
            "player": primary,
            "text": e.get("text") or "",
        }
        if kind == "goal" and secondary:
            incident["assist"] = secondary
        elif kind == "substitution" and secondary:
            incident["player_off"] = secondary
        out.append(incident)
    return {"incidents": out, "truth": _truth_from_summary(payload)}


def attach_incidents(matches: list[dict], max_workers: int = 6) -> None:
    """In-place: fetch and attach `incidents` to LIVE and FINAL matches.

    SCHEDULED matches have no events yet, so we skip them. Parallel
    fetch (4-6 workers) keeps the total runtime under ~10s for the
    full 104-match tournament.
    """
    targets = [m for m in matches if m.get("status") in ("LIVE", "FINAL")]
    if not targets:
        return
    print(f"Fetching incidents for {len(targets)} live/final matches...")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                fetch_match_events,
                m["id"],
                str(m.get("home", {}).get("id") or ""),
                str(m.get("away", {}).get("id") or ""),
            ): m
            for m in targets
        }
        for fut in as_completed(futures):
            m = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001 — best-effort
                print(f"  warn: incidents for {m['id']} failed: {exc}", file=sys.stderr)
                result = {"incidents": [], "truth": None}
            m["incidents"] = result.get("incidents", [])
            truth = result.get("truth")
            if truth:
                # Summary endpoint is authoritative — overrides any
                # stale scoreboard status / score.
                m["status"] = truth["status"]
                m["status_short"] = truth["status_short"]
                if truth.get("home_score") is not None:
                    m["home"]["score"] = truth["home_score"]
                if truth.get("away_score") is not None:
                    m["away"]["score"] = truth["away_score"]


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
    en_name = team.get("displayName") or team.get("name") or "?"
    return {
        "id": team.get("id"),
        "name": en_name,
        "name_zh": _name_zh(en_name),
        "rank": _rank(en_name),
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

    # Fetch the full World Cup window. 2026 runs Jun 11 – Jul 19,
    # hard-coded via TOURNAMENT_START / TOURNAMENT_END so the opening
    # match is always included. Pad ±1 day to absorb any tz wrap-around
    # edge cases.
    start_local = TOURNAMENT_START - timedelta(days=1)
    end_local = TOURNAMENT_END + timedelta(days=1)
    start_utc = datetime.combine(start_local, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    end_utc = datetime.combine(end_local, datetime.max.time(), tzinfo=tz).astimezone(timezone.utc)

    raw_events = fetch_full_tournament(start_utc, end_utc)

    # Group standings (best-effort — standings endpoint may lag the scoreboard)
    try:
        groups = fetch_standings()
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
        print(f"WARNING: could not fetch standings: {e}", file=sys.stderr)
        groups = []

    parsed: list[dict] = []
    for ev in raw_events:
        m = parse_event(ev, tz)
        if m:
            parsed.append(m)
    parsed.sort(key=lambda m: m["kickoff_utc"])

    # Per-match incidents (goals, cards, subs) for LIVE + FINAL games.
    attach_incidents(parsed)

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
                    "name_zh": side.get("name_zh") or _name_zh(name),
                    "rank": side.get("rank") if side.get("rank") is not None else _rank(name),
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

    # Use the hard-coded tournament dates — don't infer from the
    # fetched data, which can miss early or late matches if ESPN
    # is slow to publish them.
    tournament_start = TOURNAMENT_START.isoformat()
    tournament_end = TOURNAMENT_END.isoformat()

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
        "groups": groups,
        "days": days,
        "scorers_history": HISTORICAL_SCORERS,
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
        group_count = len(payload.get("groups", []))
        print(
            f"wrote {out} ({match_count} matches across "
            f"{len(payload['days'])} days, {team_count} teams, "
            f"{venue_count} venues, {group_count} groups, "
            f"tz={args.tz})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
