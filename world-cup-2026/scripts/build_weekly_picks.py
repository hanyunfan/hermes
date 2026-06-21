#!/usr/bin/env python3
"""
Build the "weekly picks" skeleton for the current round from
data/matches.json.

Picks the current or next matchday/round of matches, computes the
deterministic half (group-stage stakes, 0-10 score, must/lively/skip
verdict), and writes a per-match skeleton to data/weekly-picks.json
with the subjective fields left null/empty for manual enrichment.

Round-window logic
──────────────────
The script shows the matches in the *current* tournament round —
the next ROUND_WINDOW_DAYS of matches from today. Each WC 2026
group-stage matchday spans ~6 days (groups are staggered), so a
"weekly" digest of 6 days naturally covers one matchday. The window
is then capped at ROUND_MAX_MATCHES matches, prioritized by stakes
score then kickoff time. The window default can be overridden with
--window N.

The window includes matches that are SCHEDULED, LIVE, or FINAL — so
post-game analysis stays visible for matches earlier in the round.

Manual enrichment workflow (the whole point of this tab):
  1. Run this script to refresh the auto fields.
     python3 scripts/build_weekly_picks.py
  2. Open data/weekly-picks.json — fill in `headline_*`, `watch_for_*`,
     `key_players_*`, `news_focus_*`, `record_potential_*`,
     `why_skip_*`, `round_intro_*`, `manual_note_*` with this
     round's analysis.
  3. Commit + push → GitHub Pages redeploys.

The script is idempotent: a re-run preserves manual fields. A round
rollover (different date range OR different round label) wipes them
so stale analysis doesn't leak into the new round. Use --force to
ignore manual fields entirely.

Usage:
    python3 scripts/build_weekly_picks.py
    python3 scripts/build_weekly_picks.py --tz America/Chicago
    python3 scripts/build_weekly_picks.py --tz Europe/London
    python3 scripts/build_weekly_picks.py --force
    python3 scripts/build_weekly_picks.py --window 5
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Chicago"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
INPUT_PATH = DATA_DIR / "matches.json"
OUTPUT_PATH = DATA_DIR / "weekly-picks.json"

SCHEMA_VERSION = 1

# Hard cap on picks per round — keeps the digest readable. The
# earliest-N + highest-stakes picks win.
ROUND_MAX_MATCHES = 16

# How many days the digest spans. WC 2026 group-stage matchdays run
# ~6 days (groups are staggered), so 6 days naturally captures one
# full matchday. The window default can be overridden via --window.
ROUND_WINDOW_DAYS = 6

# Tournament-round labels. The script tries to derive a round label
# automatically (e.g. "Matchday 2", "Round of 32") from each match's
# stage_slug; this dict is the human-readable mapping.
ROUND_LABELS = {
    "group-stage":      {"zh": "小组赛",        "en": "Group Stage"},
    "round-of-32":      {"zh": "1/8 决赛",      "en": "Round of 32"},
    "round-of-16":      {"zh": "1/4 决赛前",    "en": "Round of 16"},
    "quarterfinals":    {"zh": "四分之一决赛",  "en": "Quarterfinals"},
    "semifinals":       {"zh": "半决赛",        "en": "Semifinals"},
    "3rd-place":        {"zh": "三四名决赛",    "en": "Third-Place"},
    "final":            {"zh": "决赛",          "en": "Final"},
}

# ── verdict helpers ────────────────────────────────────────────
VERDICT_MUST = "must"        # 必看
VERDICT_LIVELY = "lively"     # 可看可不看
VERDICT_SKIPPABLE = "skip"    # 可不看

# FIFA ranks that count as "marquee" for the auto score.
MARQUEE_RANKS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


def load_matches(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def today_in_tz(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


# ── round-window selection ─────────────────────────────────────
def _kickoff_local_date(m: dict, tz: ZoneInfo) -> date | None:
    ku = m.get("kickoff_utc")
    if not ku:
        return None
    try:
        return datetime.fromisoformat(ku.replace("Z", "+00:00")).astimezone(tz).date()
    except Exception:
        return None


def collect_round_matches(
    matches_doc: dict,
    tz_name: str,
    today_d: date,
    window_days: int = ROUND_WINDOW_DAYS,
    stage_filter: str | None = None,
) -> list[dict]:
    """Return matches in the current round window.

    Window = [today, today + window_days] in the display timezone.
    We include SCHEDULED, LIVE, and FINAL matches so post-game
    analysis stays visible for matches earlier in the window.
    Skip HALFTIME / POSTPONED / CANCELED.

    If `stage_filter` is set (e.g. "round-of-32"), only matches
    whose stage_slug matches are returned, and the date window is
    widened to cover the whole stage (looking back from today
    AND ahead up to +60 days) so a single round is captured
    cleanly even mid-tournament.
    """
    tz = ZoneInfo(tz_name)
    # Stage-filtered mode: span the whole stage, anchored to today.
    # -60d captures any in-progress stage; +90d covers the rest of WC.
    if stage_filter:
        start_d = today_d - timedelta(days=60)
        end_d = today_d + timedelta(days=90)
    else:
        start_d = today_d
        end_d = today_d + timedelta(days=window_days - 1)
    out = []
    for day_block in matches_doc.get("days", []):
        for m in day_block.get("matches", []):
            if stage_filter and m.get("stage_slug") != stage_filter:
                continue
            d = _kickoff_local_date(m, tz)
            if d is None:
                continue
            if start_d <= d <= end_d:
                if m.get("status") in ("HALFTIME", "POSTPONED", "CANCELED"):
                    continue
                out.append(m)
    out.sort(key=lambda m: m.get("kickoff_utc", ""))
    return out


def round_label(matches: list[dict], tz_name: str) -> dict:
    """Pick a round label for the picked matches.

    For group stage, derive "Matchday N" by looking at how many
    group-stage matches each team has already played (`mp` in
    standings): 0 → MD1, 1 → MD2, 2 → MD3. If teams are split across
    matchdays (the schedule staggers groups), use the dominant one.
    For knockout rounds, use the dominant stage_slug.
    """
    if not matches:
        return {"zh": "本轮", "en": "This Round"}
    stage_counts: dict[str, int] = defaultdict(int)
    for m in matches:
        stage_counts[m.get("stage_slug") or "unknown"] += 1
    dominant = max(stage_counts, key=stage_counts.get)

    if dominant == "group-stage":
        # Derive MD number from the median mp of teams in the picked
        # matches. Most group matches are "MD1" (mp=0) for early
        # tournament, "MD2" (mp=1) for mid, "MD3" (mp=2) for late.
        # We pull mp from the most-recent standings attached to each
        # match via the document's groups list.
        team_to_mp: dict[str, int] = {}
        for g in _doc_cache.get("groups", []):
            for e in g.get("entries", []):
                tid = str(e.get("team", {}).get("id") or "")
                if tid:
                    team_to_mp[tid] = e.get("mp", 0)
        mps = []
        for m in matches:
            for side in (m.get("home") or {}, m.get("away") or {}):
                tid = str(side.get("id") or "")
                if tid in team_to_mp:
                    mps.append(team_to_mp[tid])
        # Median mp → next matchday = median + 1
        if mps:
            mps.sort()
            median_mp = mps[len(mps) // 2]
            md_num = median_mp + 1
            md_num = max(1, min(3, md_num))
        else:
            md_num = 1
        return {
            "zh": f"小组赛第 {md_num} 轮",
            "en": f"Matchday {md_num}",
        }

    base = ROUND_LABELS.get(dominant, {"zh": dominant, "en": dominant})
    return base


def round_date_range(matches: list[dict], tz_name: str) -> tuple[date, date] | None:
    if not matches:
        return None
    tz = ZoneInfo(tz_name)
    dates = sorted({_kickoff_local_date(m, tz) for m in matches if _kickoff_local_date(m, tz) is not None})
    if not dates:
        return None
    return dates[0], dates[-1]


def build_group_index(matches_doc: dict) -> dict:
    """Map team_id → {group_name, rank, pts, mp, w, d, l, gf, ga, gd}."""
    idx: dict[str, dict] = {}
    for g in matches_doc.get("groups", []):
        gname = g.get("abbreviation") or g.get("name") or ""
        for e in g.get("entries", []):
            t = e.get("team") or {}
            tid = str(t.get("id") or "")
            if not tid:
                continue
            idx[tid] = {
                "group_name": gname,
                "group_abbr": gname,
                "rank": e.get("rank"),
                "pts": e.get("pts", 0),
                "mp": e.get("mp", 0),
                "w": e.get("w", 0),
                "d": e.get("d", 0),
                "l": e.get("l", 0),
                "gf": e.get("gf", 0),
                "ga": e.get("ga", 0),
                "gd": e.get("gd", 0),
            }
    return idx


# ── stakes computation ─────────────────────────────────────────
def _doc_cache_set(doc: dict) -> None:
    global _doc_cache
    _doc_cache = doc


_doc_cache: dict = {}


def md_for_team(team_id: str, today_iso: str) -> int:
    """Matchday number for `team_id` after counting its own matches
    scheduled on or before today (in UTC). 1, 2, or 3 in the group
    stage. Returns 0 if no group games are scheduled yet."""
    count = 0
    for day_block in _doc_cache.get("days", []):
        for m in day_block.get("matches", []):
            if m.get("stage_slug") != "group-stage":
                continue
            if str(m.get("home", {}).get("id")) != team_id and str(m.get("away", {}).get("id")) != team_id:
                continue
            ku = m.get("kickoff_utc", "")
            if ku and ku[:10] <= today_iso:
                count += 1
    return count


def compute_stakes(
    match: dict,
    standings_idx: dict,
    today_iso: str,
) -> dict:
    """Auto-derived stake narrative for one match.

    Score is on a 1–5 scale:
      5 = must-watch (highest stakes)
      4 = must-watch (real consequences)
      3 = lively (worth a look, storylines but no do-or-die)
      2 = skippable (lopsided or low-stakes)
      1 = skippable (dead rubber / opener with no marquee)

    Returns a dict with:
      - kind: stakes classification (see verdicts below)
      - score: 1–5 base interest (before marquee bonus)
      - verdict: "must" | "lively" | "skip"
      - narrative_zh / narrative_en: one-line stakes summary
    """
    home_id = str(match.get("home", {}).get("id") or "")
    away_id = str(match.get("away", {}).get("id") or "")
    stage_slug = match.get("stage_slug") or ""

    # ── knockout: 4 base (single elimination is always interesting) ──
    if stage_slug and stage_slug != "group-stage":
        return {
            "kind": "knockout",
            "score": 4,
            "verdict": VERDICT_LIVELY,
            "narrative_zh": "淘汰赛，一场定胜负。",
            "narrative_en": "Knockout — single elimination.",
        }

    # ── group stage ──
    h = standings_idx.get(home_id)
    a = standings_idx.get(away_id)
    h_md = (h["mp"] if h else 0) + 1
    a_md = (a["mp"] if a else 0) + 1
    md_num = max(h_md, a_md)
    h_pts = h["pts"] if h else 0
    a_pts = a["pts"] if a else 0
    h_alive = (h is None) or (h_pts > 0) or (h_md == 3)
    a_alive = (a is None) or (a_pts > 0) or (a_md == 3)

    # Helper: are all four teams in this group level on points?
    def group_tied() -> bool:
        if not h or not a:
            return False
        gid = h.get("group_name")
        if not gid:
            return False
        pts_set = set()
        for g in _doc_cache.get("groups", []):
            if g.get("abbreviation") != gid:
                continue
            for e in g.get("entries", []):
                pts_set.add(e.get("pts", 0))
        return len(pts_set) == 1

    if md_num == 1:
        # Opener: group is wide open, but no immediate stakes.
        # Marquee (top-10) teams get +1 from the auto_score bonus.
        return {
            "kind": "opener",
            "score": 1,
            "verdict": VERDICT_SKIPPABLE,
            "narrative_zh": "小组赛首轮，双方均无积分，一切皆有可能。",
            "narrative_en": "Group opener — both sides start from zero.",
        }

    if md_num == 3:
        if h_alive and a_alive:
            return {
                "kind": "group_decider",
                "score": 4,
                "verdict": VERDICT_MUST,
                "narrative_zh": "末轮出线生死战。",
                "narrative_en": "Final matchday — qualification on the line.",
            }
        if h_alive or a_alive:
            return {
                "kind": "lively",
                "score": 3,
                "verdict": VERDICT_LIVELY,
                "narrative_zh": "末轮，但有球队已无晋级可能。",
                "narrative_en": "Final matchday, but a team has already been eliminated.",
            }
        return {
            "kind": "dead_rubber",
            "score": 1,
            "verdict": VERDICT_SKIPPABLE,
            "narrative_zh": "末轮，双方均已无晋级可能。",
            "narrative_en": "Final matchday, dead rubber — both teams already out.",
        }

    if h_pts == 3 and a_pts == 3:
        return {
            "kind": "six_pointer",
            "score": 4,
            "verdict": VERDICT_MUST,
            "narrative_zh": "双方首轮全胜，第二轮正面交锋——赢者基本锁定出线。",
            "narrative_en": "Both won MD1 — winner likely seals qualification.",
        }
    if h_pts == 0 and a_pts == 0:
        return {
            "kind": "must_win",
            "score": 4,
            "verdict": VERDICT_MUST,
            "narrative_zh": "双方首轮均落败，本场再输基本出局。",
            "narrative_en": "Both lost MD1 — another loss likely eliminates.",
        }
    if h_pts == 1 and a_pts == 1 and group_tied():
        # Four-way tied groups: real storylines but no do-or-die yet.
        # Without marquee bonus, this is lively (3). With top-10
        # involved, it climbs to must (4) or 5.
        return {
            "kind": "four_way_tied",
            "score": 3,
            "verdict": VERDICT_LIVELY,
            "narrative_zh": "小组四队齐平，本场是拉开差距的第一次机会。",
            "narrative_en": "All four sides level — first chance to break away.",
        }
    if {h_pts, a_pts} == {3, 0}:
        # Compare the underdog's FIFA rank (from the match dict, NOT
        # the standings — standings['rank'] is the position within
        # the group, which is always 1–4 and useless for tiering).
        laggard_fifa_rank = (
            match.get("away", {}).get("rank") if h_pts == 3
            else match.get("home", {}).get("rank")
        )
        if laggard_fifa_rank is not None and laggard_fifa_rank <= 15:
            return {
                "kind": "upset_watch",
                "score": 3,
                "verdict": VERDICT_LIVELY,
                "narrative_zh": "首轮胜者对阵劲旅，弱旅再输基本告别小组赛。",
                "narrative_en": "Group leader faces a tough test — upset risk is real.",
            }
        return {
            "kind": "routine",
            "score": 2,
            "verdict": VERDICT_SKIPPABLE,
            "narrative_zh": "首轮胜者迎战弱旅，悬念不大但仍有故事。",
            "narrative_en": "Group leader vs underdog — storylines still possible.",
        }

    # Asymmetric MD2 cases (3-1, 1-0, 0-1, 1-3): one team has
    # breathing room, the other needs points. Real storylines but
    # not do-or-die. Lively.
    return {
        "kind": "asymmetric",
        "score": 3,
        "verdict": VERDICT_LIVELY,
        "narrative_zh": "小组赛第二轮常规对决。",
        "narrative_en": "Standard MD2 fixture.",
    }


def auto_score_match(match: dict, stakes: dict) -> int:
    """Combine stakes base + marquee bonus. Cap at 5.

    Marquee bonus is deliberately tight: +1 if either side is in the
    FIFA top 10. This lets marquee matchups climb from 3 to 4, or
    from 4 to 5, but a routine non-marquee game stays at its base.
    """
    base = stakes["score"]
    h_rank = match.get("home", {}).get("rank")
    a_rank = match.get("away", {}).get("rank")
    bonus = 0
    if h_rank in MARQUEE_RANKS or a_rank in MARQUEE_RANKS:
        bonus += 1
    return min(5, max(1, base + bonus))


def auto_verdict(score: int) -> str:
    if score >= 4:
        return VERDICT_MUST
    if score >= 3:
        return VERDICT_LIVELY
    return VERDICT_SKIPPABLE


# ── existing-data merge ────────────────────────────────────────
def load_existing_output(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def find_existing_match(existing: dict | None, match_id: str) -> dict | None:
    if not existing:
        return None
    for m in existing.get("matches", []):
        if str(m.get("match_id")) == str(match_id):
            return m
    return None


def preserve_manual_fields(new: dict, old: dict | None) -> None:
    if not old:
        return
    keep_keys = (
        "headline_zh", "headline_en",
        "watch_for_zh", "watch_for_en",
        "key_players_zh", "key_players_en",
        "news_focus_zh", "news_focus_en",
        "record_potential_zh", "record_potential_en",
        "why_skip_zh", "why_skip_en",
        "verdict_override", "score_override",
        "manual_author",
    )
    for k in keep_keys:
        if k in old and old[k] not in (None, "", [], {}):
            new[k] = old[k]


def is_manually_enriched(match: dict) -> bool:
    return bool(match.get("headline_zh") or match.get("headline_en"))


# ── main builder ───────────────────────────────────────────────
def build(matches_doc: dict, tz_name: str, force: bool = False, window_days: int = ROUND_WINDOW_DAYS, stage_filter_override: str | None = None) -> dict:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today_local = now_local.date()
    today_iso_utc = now_local.astimezone(timezone.utc).date().isoformat()
    _doc_cache_set(matches_doc)

    standings_idx = build_group_index(matches_doc)
    stage_filter = stage_filter_override  # bound by caller
    round_matches = collect_round_matches(
        matches_doc, tz_name, today_local,
        window_days=window_days,
        stage_filter=stage_filter,
    )
    # Cap picks per round.
    if len(round_matches) > ROUND_MAX_MATCHES:
        # Score first, then kickoff time, then take the top N.
        scored = []
        for m in round_matches:
            stakes = compute_stakes(m, standings_idx, today_iso_utc)
            scored.append((auto_score_match(m, stakes), m.get("kickoff_utc", ""), m))
        scored.sort(key=lambda x: (-x[0], x[1]))
        round_matches = [m for _, _, m in scored[:ROUND_MAX_MATCHES]]
        round_matches.sort(key=lambda m: m.get("kickoff_utc", ""))

    label = round_label(round_matches, tz_name)
    date_range = round_date_range(round_matches, tz_name)
    if date_range:
        lo, hi = date_range
        date_range_iso = [lo.isoformat(), hi.isoformat()]
    else:
        date_range_iso = [today_local.isoformat(), today_local.isoformat()]

    existing = None if force else load_existing_output(OUTPUT_PATH)
    # Round identity = (label_zh, date_range). On rollover, manual
    # fields get wiped so last round's prose doesn't leak in.
    new_round_key = (label["zh"], tuple(date_range_iso))
    existing_round_key = (
        (existing or {}).get("round_label", {}).get("zh"),
        tuple((existing or {}).get("round_date_range") or []),
    )
    round_changed = existing_round_key != new_round_key

    out_matches = []
    for m in round_matches:
        stakes = compute_stakes(m, standings_idx, today_iso_utc)
        score = auto_score_match(m, stakes)
        verdict = auto_verdict(score)
        home = m.get("home", {}) or {}
        away = m.get("away", {}) or {}

        h_entry = standings_idx.get(str(home.get("id") or "")) or {}
        a_entry = standings_idx.get(str(away.get("id") or "")) or {}

        new_entry = {
            "match_id": str(m.get("id") or ""),
            "kickoff_utc": m.get("kickoff_utc"),
            "kickoff_local": m.get("kickoff_local"),
            "kickoff_local_date": m.get("kickoff_local_date"),
            "kickoff_time": m.get("kickoff_time"),
            "kickoff_weekday": m.get("kickoff_weekday"),
            "stage": m.get("stage"),
            "stage_slug": m.get("stage_slug"),
            "venue": (m.get("venue") or {}).get("name"),
            "venue_city": (m.get("venue") or {}).get("city"),
            "espn_url": m.get("espn_url"),
            "fox_url": m.get("fox_url"),

            "home": {
                "id": str(home.get("id") or ""),
                "name": home.get("name"),
                "name_zh": home.get("name_zh"),
                "flag": home.get("flag"),
                "abbr": home.get("abbr"),
                "rank": home.get("rank"),
            },
            "away": {
                "id": str(away.get("id") or ""),
                "name": away.get("name"),
                "name_zh": away.get("name_zh"),
                "flag": away.get("flag"),
                "abbr": away.get("abbr"),
                "rank": away.get("rank"),
            },

            "group_name": h_entry.get("group_name") or a_entry.get("group_name"),
            "home_group_rank": h_entry.get("rank"),
            "home_pts": h_entry.get("pts", 0),
            "home_mp": h_entry.get("mp", 0),
            "away_group_rank": a_entry.get("rank"),
            "away_pts": a_entry.get("pts", 0),
            "away_mp": a_entry.get("mp", 0),

            "stakes_kind": stakes["kind"],
            "stakes_score_auto": score,
            "stakes_verdict_auto": verdict,
            "stakes_narrative_zh": stakes["narrative_zh"],
            "stakes_narrative_en": stakes["narrative_en"],

            "verdict": verdict,
            "score": score,
            "headline_zh": None,
            "headline_en": None,
            "watch_for_zh": [],
            "watch_for_en": [],
            "key_players_zh": [],
            "key_players_en": [],
            "news_focus_zh": None,
            "news_focus_en": None,
            "record_potential_zh": [],
            "record_potential_en": [],
            "why_skip_zh": None,
            "why_skip_en": None,
            "verdict_override": None,
            "score_override": None,
        }

        if not round_changed:
            old = find_existing_match(existing, new_entry["match_id"])
            preserve_manual_fields(new_entry, old)
        if new_entry.get("verdict_override"):
            new_entry["verdict"] = new_entry["verdict_override"]
        if new_entry.get("score_override") is not None:
            new_entry["score"] = new_entry["score_override"]
        out_matches.append(new_entry)

    # Sort: must > lively > skip; within a bucket, kickoff time.
    bucket_order = {VERDICT_MUST: 0, VERDICT_LIVELY: 1, VERDICT_SKIPPABLE: 2}
    out_matches.sort(
        key=lambda m: (
            bucket_order.get(m.get("verdict"), 99),
            m.get("kickoff_utc") or "",
        )
    )

    manual_count = sum(1 for m in out_matches if is_manually_enriched(m))
    last_manual = (existing or {}).get("last_manual_update") if not round_changed else None

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": tz_name,
        "now_local": now_local.isoformat(timespec="seconds"),
        "round_label": label,
        "round_date_range": date_range_iso,
        "match_count": len(out_matches),
        "manual_count": manual_count,
        "last_manual_update": last_manual,
        "round_intro_zh": (existing or {}).get("round_intro_zh") if not round_changed else None,
        "round_intro_en": (existing or {}).get("round_intro_en") if not round_changed else None,
        "manual_note_zh": (existing or {}).get("manual_note_zh") if not round_changed else None,
        "manual_note_en": (existing or {}).get("manual_note_en") if not round_changed else None,
        "matches": out_matches,
    }
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build weekly-picks skeleton from matches.json")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="display timezone (default: America/Chicago)")
    parser.add_argument("--in", dest="in_path", default=str(INPUT_PATH), help="path to matches.json")
    parser.add_argument("--out", dest="out_path", default=str(OUTPUT_PATH), help="path to weekly-picks.json")
    parser.add_argument("--force", action="store_true", help="ignore existing manual enrichment")
    parser.add_argument("--window", type=int, default=None, help="override round-window auto-detect (days)")
    parser.add_argument("--stage", dest="stage", default=None,
                        help="filter to a specific stage_slug (e.g. 'round-of-32', 'group-stage'). "
                             "When set, the date window is widened to span the whole stage.")
    parser.add_argument("--dry-run", action="store_true", help="print JSON to stdout, don't write")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    if not in_path.exists():
        print(f"err: {in_path} not found", file=sys.stderr)
        return 2

    matches_doc = load_matches(in_path)
    doc = build(
        matches_doc, args.tz,
        force=args.force,
        window_days=args.window or ROUND_WINDOW_DAYS,
        stage_filter_override=args.stage,
    )

    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    label_en = doc["round_label"]["en"]
    rng = doc["round_date_range"]
    print(
        f"wrote {out_path} ({doc['match_count']} matches, "
        f"{doc['manual_count']} manually enriched, "
        f"round={label_en}, dates={rng[0]}..{rng[1]}, stage_filter={args.stage or 'auto'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())