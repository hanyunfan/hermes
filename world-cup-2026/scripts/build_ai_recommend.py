#!/usr/bin/env python3
"""
Build the AI-recommend skeleton for "today" from data/matches.json.

This script does ONLY the deterministic / numeric side of the AI
recommendation tab — it computes group-stage stakes (which team needs
what result to advance / stay alive / qualify for the round of 32),
ranks matches by stakes + marquee appeal, and emits a per-match
skeleton to data/ai-recommend.json with the subjective fields left
null/empty for manual enrichment.

Manual enrichment workflow (the whole point of this tab):
  1. Run this script to refresh the auto fields.
     python3 scripts/build_ai_recommend.py
  2. Open data/ai-recommend.json — fill in `headline_*`, `watch_for_*`,
     `key_players_*`, `news_focus_*`, `record_potential_*`, `why_skip_*`,
     `intro_*`, `manual_note_*` with today's analysis.
  3. Commit + push → GitHub Pages redeploys.

The script is idempotent: if a manual analysis already exists (any
`headline_zh` or `headline_en` populated on a match), it keeps the
existing text and only refreshes the auto fields and timestamps. To
force a full rewrite (rare — usually only when the date changes),
pass --force.

Usage:
    python3 scripts/build_ai_recommend.py
    python3 scripts/build_ai_recommend.py --tz America/Chicago
    python3 scripts/build_ai_recommend.py --tz Europe/London
    python3 scripts/build_ai_recommend.py --force
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Chicago"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
INPUT_PATH = DATA_DIR / "matches.json"
OUTPUT_PATH = DATA_DIR / "ai-recommend.json"

SCHEMA_VERSION = 1

# ── verdict helpers ────────────────────────────────────────────
# We classify each match into one of three buckets based on auto-
# derived signals. The subjective text still wins in the UI — this
# just gives Frank (and the script) a starting point.

VERDICT_MUST = "must"        # 必看
VERDICT_LIVELY = "lively"     # 还行 / 可看可不看
VERDICT_SKIPPABLE = "skip"    # 可不看

# FIFA ranks that count as "marquee" for the auto score.
MARQUEE_RANKS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


def load_matches(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def today_in_tz(tz_name: str) -> date:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).date()


def collect_today_matches(matches_doc: dict, tz_name: str, day: date) -> list[dict]:
    """Pull all matches whose local kickoff date == `day` in `tz_name`."""
    tz = ZoneInfo(tz_name)
    out = []
    for day_block in matches_doc.get("days", []):
        for m in day_block.get("matches", []):
            ku = m.get("kickoff_utc")
            if not ku:
                continue
            try:
                d = datetime.fromisoformat(ku.replace("Z", "+00:00")).astimezone(tz).date()
            except Exception:
                continue
            if d == day:
                out.append(m)
    out.sort(key=lambda m: m.get("kickoff_utc", ""))
    return out


def build_group_index(matches_doc: dict) -> dict:
    """Map team_id → {group_name, group_abbr, pts, mp, w, d, l, gf, ga, gd, rank}.

    Built from the standings payload, which already reflects every
    match played through the most recent fetch.
    """
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


def md_for_team(team_id: str, matches_doc: dict, today_iso: str) -> int | None:
    """Matchday number for `team_id` after counting its own matches
    scheduled on or before today (in UTC). 1, 2, or 3 in the group
    stage. Returns None if no group games are scheduled yet (knockout)."""
    count = 0
    for day_block in matches_doc.get("days", []):
        for m in day_block.get("matches", []):
            if m.get("stage_slug") != "group-stage":
                continue
            if str(m.get("home", {}).get("id")) != team_id and str(m.get("away", {}).get("id")) != team_id:
                continue
            ku = m.get("kickoff_utc", "")
            if ku and ku[:10] <= today_iso:
                count += 1
    return count or None


def compute_stakes(
    match: dict,
    standings_idx: dict,
    today_iso: str,
    matches_doc: dict,
) -> dict:
    """Return the auto-derived stake narrative for one match.

    Returns a dict with:
      - kind: "group_decider" | "must_win" | "dead_rubber" |
              "knockout" | "opener" | "regular"
      - score: 0–10 base interest (before subjective override)
      - verdict: "must" | "lively" | "skip"
      - narrative_zh / narrative_en: one-line stakes summary
    """
    home_id = str(match.get("home", {}).get("id") or "")
    away_id = str(match.get("away", {}).get("id") or "")
    stage_slug = match.get("stage_slug") or ""

    # ── knockout: trivial — always lively (no math needed) ──
    if stage_slug and stage_slug != "group-stage":
        return {
            "kind": "knockout",
            "score": 8,
            "verdict": VERDICT_LIVELY,
            "narrative_zh": "淘汰赛，一场定胜负。",
            "narrative_en": "Knockout — single elimination.",
        }

    # ── group stage ──
    h = standings_idx.get(home_id)
    a = standings_idx.get(away_id)

    # MD1 = first matchday. If both teams have played 0 games, this is
    # an opener (every team alive, no dead rubbers yet). Use a single
    # source of truth: count *this* match as MD(cnt+1).
    h_md = (h["mp"] if h else 0) + 1
    a_md = (a["mp"] if a else 0) + 1
    md_num = max(h_md, a_md)

    h_pts = h["pts"] if h else 0
    a_pts = a["pts"] if a else 0
    h_rank = h["rank"] if h and h.get("rank") else None
    a_rank = a["rank"] if a and a.get("rank") else None

    # After MD2, top 2 are usually clear; MD3 is when elimination math
    # gets interesting. Pre-MD2 (opener) everything is wide open.
    if md_num == 1:
        # Opener — wide open. Marquee teams get a bump.
        marquee = (
            (match.get("home", {}).get("rank") in MARQUEE_RANKS)
            or (match.get("away", {}).get("rank") in MARQUEE_RANKS)
        )
        score = 7 if marquee else 5
        return {
            "kind": "opener",
            "score": score,
            "verdict": VERDICT_MUST if marquee else VERDICT_LIVELY,
            "narrative_zh": "小组赛首轮，双方均无积分，一切皆有可能。",
            "narrative_en": "Group opener — both sides start from zero.",
        }

    if md_num == 3:
        # Final matchday — always decisive math.
        # If either team has 0 pts they're already out (unless the
        # group is so lopsided that others can't catch up).
        h_alive = h is None or h_pts > 0 or h_md == 3
        a_alive = a is None or a_pts > 0 or a_md == 3
        if not h_alive or not a_alive:
            score = 6
            verdict = VERDICT_LIVELY
            kind = "dead_rubber"
            zh = "末轮，但有球队已无晋级可能。"
            en = "Final matchday, but a team has already been eliminated."
        else:
            score = 9
            verdict = VERDICT_MUST
            kind = "group_decider"
            zh = "末轮出线生死战。"
            en = "Final matchday — qualification on the line."
        return {"kind": kind, "score": score, "verdict": verdict, "narrative_zh": zh, "narrative_en": en}

    # md_num == 2 — middle matchday. Heuristic:
    #   • Both teams at 3 pts → "six-pointer" decider
    #   • One at 3, one at 0 → favorite vs underdog, fairly high stakes
    #   • Both at 0 → both desperate, must-win for both
    #   • One at 3+, one at 0 with weak opponent → quieter
    # Helper: are all four teams in this group level on points?
    # When yes, MD2 is the first chance to break away — quietly
    # tense even if neither team is "top".
    def group_tied() -> bool:
        if not h or not a:
            return False
        gid = None
        for g in matches_doc.get("groups", []):
            for e in g.get("entries", []):
                if str(e.get("team", {}).get("id")) == home_id:
                    gid = g.get("abbreviation")
                    break
            if gid:
                break
        if not gid:
            return False
        pts_set = set()
        for g in matches_doc.get("groups", []):
            if g.get("abbreviation") != gid:
                continue
            for e in g.get("entries", []):
                pts_set.add(e.get("pts", 0))
        return len(pts_set) == 1

    if h_pts == 3 and a_pts == 3:
        return {
            "kind": "must_win",
            "score": 9,
            "verdict": VERDICT_MUST,
            "narrative_zh": "双方首轮全胜，第二轮正面交锋——赢者基本锁定出线。",
            "narrative_en": "Both won MD1 — winner likely seals qualification.",
        }
    if (h_pts == 0 and a_pts == 0):
        return {
            "kind": "must_win",
            "score": 8,
            "verdict": VERDICT_MUST,
            "narrative_zh": "双方首轮均落败，本场再输基本出局。",
            "narrative_en": "Both lost MD1 — another loss likely eliminates.",
        }
    if h_pts == 1 and a_pts == 1 and group_tied():
        return {
            "kind": "must_win",
            "score": 8,
            "verdict": VERDICT_MUST,
            "narrative_zh": "小组四队齐平，本场是拉开差距的第一次机会。",
            "narrative_en": "All four sides level — first chance to break away.",
        }
    if {h_pts, a_pts} == {3, 0}:
        laggard_rank = a_rank if h_pts == 3 else h_rank
        # Bump score if the trailing team is highly ranked (i.e. this
        # is an upset risk match, not a routine walkover).
        if laggard_rank is not None and laggard_rank <= 15:
            return {
                "kind": "must_win",
                "score": 8,
                "verdict": VERDICT_MUST,
                "narrative_zh": "首轮胜者对阵劲旅，弱旅再输基本告别小组赛。",
                "narrative_en": "Group leader faces a tough test — upset risk is real.",
            }
        return {
            "kind": "regular",
            "score": 6,
            "verdict": VERDICT_LIVELY,
            "narrative_zh": "首轮胜者迎战弱旅，悬念不大但仍有故事。",
            "narrative_en": "Group leader vs underdog — storylines still possible.",
        }

    # One team on 1 pt (draw), other on 0 or 3 — middling stakes.
    return {
        "kind": "regular",
        "score": 6,
        "verdict": VERDICT_LIVELY,
        "narrative_zh": "小组赛第二轮常规对决。",
        "narrative_en": "Standard MD2 fixture.",
    }


# Tiny helpers that keep `compute_stakes` readable. We carry the
# loaded document around via a global cache so md_for_team can use
# it without threading it through every call site.
_doc_cache: dict = {}


def recompute_stakes(match, standings_idx, today_iso, doc):
    """Recompute stakes with the document in scope (avoids globals)."""
    global _doc_cache
    _doc_cache = doc
    return compute_stakes(match, standings_idx, today_iso, doc)


# ── verdict auto-ranking ───────────────────────────────────────
def auto_score_match(match: dict, stakes: dict) -> int:
    """Combine stakes score + marquee team bonus into a 0–10 score."""
    base = stakes["score"]
    h_rank = match.get("home", {}).get("rank")
    a_rank = match.get("away", {}).get("rank")
    bonus = 0
    if h_rank in MARQUEE_RANKS or a_rank in MARQUEE_RANKS:
        bonus += 1
    # Both teams top-20 → huge marquee bump.
    if (h_rank or 99) <= 20 and (a_rank or 99) <= 20:
        bonus += 1
    return min(10, base + bonus)


def auto_verdict(score: int) -> str:
    if score >= 8:
        return VERDICT_MUST
    if score >= 6:
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
    """Carry over subjective fields from an older revision so a
    re-run of this script doesn't wipe today's manual analysis."""
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
    """A match counts as 'enriched' if either headline is populated."""
    return bool(match.get("headline_zh") or match.get("headline_en"))


# ── main builder ───────────────────────────────────────────────
def build(matches_doc: dict, tz_name: str, force: bool = False) -> dict:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today_local = now_local.date()
    today_iso = today_local.isoformat()
    # today_iso is local-date-in-tz, but it's also a UTC prefix that
    # sorts correctly because all dates we compare are YYYY-MM-DD.
    today_iso_utc = now_local.astimezone(timezone.utc).date().isoformat()

    standings_idx = build_group_index(matches_doc)
    today_matches = collect_today_matches(matches_doc, tz_name, today_local)

    existing = None if force else load_existing_output(OUTPUT_PATH)

    out_matches = []
    for m in today_matches:
        stakes = recompute_stakes(m, standings_idx, today_iso_utc, matches_doc)
        score = auto_score_match(m, stakes)
        verdict = auto_verdict(score)
        home = m.get("home", {}) or {}
        away = m.get("away", {}) or {}

        h_entry = standings_idx.get(str(home.get("id") or "")) or {}
        a_entry = standings_idx.get(str(away.get("id") or "")) or {}

        # `record_potential` is left for manual enrichment; we pre-fill
        # the auto-detected items that a script can safely know: a
        # player's all-time rank (Mbappé climbing to top of all-time,
        # etc.) is too speculative for a deterministic script, so this
        # list starts empty.

        new_entry = {
            "match_id": str(m.get("id") or ""),
            "kickoff_utc": m.get("kickoff_utc"),
            "kickoff_local": m.get("kickoff_local"),
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

            # Manual fields — populated by the analyst (Claude, on
            # request from Frank). Default to null so the UI can show
            # a clear "awaiting analysis" placeholder.
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

        old = find_existing_match(existing, new_entry["match_id"])
        preserve_manual_fields(new_entry, old)
        # Honor overrides from a prior manual pass too.
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
    last_manual = existing.get("last_manual_update") if existing else None
    if existing and existing.get("date_local") != today_iso:
        # Date rolled over — wipe the manual signals so the stale
        # analysis from yesterday doesn't leak into today's tab.
        for m in out_matches:
            for k in (
                "headline_zh", "headline_en",
                "watch_for_zh", "watch_for_en",
                "key_players_zh", "key_players_en",
                "news_focus_zh", "news_focus_en",
                "record_potential_zh", "record_potential_en",
                "why_skip_zh", "why_skip_en",
                "verdict_override", "score_override",
                "manual_author",
            ):
                m[k] = None if not isinstance(m.get(k), list) else []
        last_manual = None
        manual_count = 0

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": tz_name,
        "now_local": now_local.isoformat(timespec="seconds"),
        "date_local": today_iso,
        "match_count": len(out_matches),
        "manual_count": manual_count,
        "last_manual_update": last_manual,
        "intro_zh": (existing or {}).get("intro_zh"),
        "intro_en": (existing or {}).get("intro_en"),
        "manual_note_zh": (existing or {}).get("manual_note_zh"),
        "manual_note_en": (existing or {}).get("manual_note_en"),
        "matches": out_matches,
    }
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AI-recommend skeleton from matches.json")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="display timezone (default: America/Chicago)")
    parser.add_argument("--in", dest="in_path", default=str(INPUT_PATH), help="path to matches.json")
    parser.add_argument("--out", dest="out_path", default=str(OUTPUT_PATH), help="path to ai-recommend.json")
    parser.add_argument("--force", action="store_true", help="ignore existing manual enrichment")
    parser.add_argument("--dry-run", action="store_true", help="print JSON to stdout, don't write")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    if not in_path.exists():
        print(f"err: {in_path} not found", file=sys.stderr)
        return 2

    matches_doc = load_matches(in_path)
    doc = build(matches_doc, args.tz, force=args.force)

    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    manual = doc["manual_count"]
    print(f"wrote {out_path} ({doc['match_count']} matches, {manual} manually enriched, date={doc['date_local']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())