#!/usr/bin/env python3
"""
Compute knockout-odds probabilities for each team in the group stage.

For each group, identifies remaining (unplayed) matches and runs a
Monte Carlo simulation (default 10,000 iterations) to estimate each
team's probability of finishing 1st / 2nd / 3rd / 4th in their group
and (implicitly) their chance of advancing to the Round of 32.

Win/draw/loss probabilities for each remaining match are derived
from the FIFA rank difference using an Elo-style expected-score
formula. Draw probability is shrunk as the rank gap widens (mismatched
teams are less likely to draw than evenly-matched ones).

Output: data/knockout-odds.json
  {
    "schema_version": 1,
    "generated_at": "...",
    "n_simulations": 10000,
    "match_window": ["2026-06-21", "2026-06-28"],
    "groups": [
      {
        "name": "Group A",
        "teams": [
          {
            "id": "203", "abbr": "MEX", "name": "Mexico", "rank": 14,
            "current_pts": 6, "current_gd": 3, "current_mp": 2,
            "p_1st": 87.4, "p_2nd": 9.1, "p_3rd": 2.3, "p_4th": 1.2,
            "p_advance": 96.5  // top-2 + best-3rd (per FIFA's 32-team format)
          },
          ...
        ]
      }
    ]
  }

Run: python3 scripts/compute_knockout_odds.py [--sims N]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "data"
INPUT_PATH = DATA_DIR / "matches.json"
OUTPUT_PATH = DATA_DIR / "knockout-odds.json"

DEFAULT_TZ = "America/Chicago"
SCHEMA_VERSION = 1
DEFAULT_SIMS = 10000
RNG_SEED = None  # set to int for reproducible runs

# 2026 WC format: top 2 in each group + 8 best 3rd-place teams advance.
ADVANCE_TOP2 = 2
ADVANCE_BEST3 = 8  # 8 best 3rd-place teams across all 12 groups


def elo_win_prob(rank_a: int | None, rank_b: int | None) -> float:
    """Elo-style expected score for team A vs team B given FIFA ranks.
    Lower rank = stronger. We treat the 0..300 FIFA range as roughly
    Elo-like (~400-point scale), then squish the expected score
    toward [0.02, 0.98] to avoid degenerate probabilities."""
    if rank_a is None or rank_b is None:
        return 0.5
    diff = rank_b - rank_a  # positive diff = A is stronger (lower rank)
    expected = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
    return max(0.02, min(0.98, expected))


def match_outcome_probs(rank_a: int | None, rank_b: int | None) -> tuple[float, float, float]:
    """Return (P(home wins), P(draw), P(away wins)).

    Draw probability shrinks as the rank gap widens — evenly matched
    teams draw more often than mismatched ones. We use a logistic
    shrink: max draw at rank gap = 0 (~0.30), drops to ~0.10 when
    the gap is 100+."""
    p_home = elo_win_prob(rank_a, rank_b)
    # Neutralize for away-side bias we don't model here — use mean.
    p_neutral = (p_home + (1.0 - p_home)) / 2.0  # = 0.5
    # Actually use the Elo as the team's overall strength in the match
    # (no home/away split — the simulation already knows who's home).
    p_strong = p_home
    p_weak = 1.0 - p_home
    gap = abs((rank_a or 0) - (rank_b or 0))
    # Draw: ~0.30 at gap=0, decays with gap.
    p_draw = 0.30 * (1.0 - min(1.0, gap / 100.0)) + 0.05  # floor 0.05
    p_draw = max(0.05, min(0.40, p_draw))
    # Distribute remaining mass proportional to team strength.
    remaining = 1.0 - p_draw
    if remaining <= 0:
        return 0.475, 0.05, 0.475
    # Allocate "stronger team wins" share: 80% of remaining goes to
    # the stronger team, 20% to the weaker (so the underdog still has
    # an upset chance).
    if p_strong >= p_weak:
        return remaining * 0.5 + (p_strong - p_weak) * 0.3, p_draw, remaining * 0.5 - (p_strong - p_weak) * 0.3
    return remaining * 0.5 - (p_weak - p_strong) * 0.3, p_draw, remaining * 0.5 + (p_weak - p_strong) * 0.3


def sample_outcome(probs: tuple[float, float, float], rng: random.Random) -> int:
    """Return 0 (home wins), 1 (draw), 2 (away wins) by weighted draw."""
    r = rng.random()
    if r < probs[0]:
        return 0
    if r < probs[0] + probs[1]:
        return 1
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute knockout-odds via Monte Carlo")
    parser.add_argument("--sims", type=int, default=DEFAULT_SIMS, help="number of MC iterations")
    parser.add_argument("--in", dest="in_path", default=str(INPUT_PATH), help="path to matches.json")
    parser.add_argument("--out", dest="out_path", default=str(OUTPUT_PATH), help="path to write output")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="display timezone (for date labels)")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    if not in_path.exists():
        print(f"err: {in_path} not found", file=sys.stderr)
        return 2

    with in_path.open("r", encoding="utf-8") as f:
        matches_doc = json.load(f)

    rng = random.Random(args.seed)

    # Build group_teams: {group_abbr: {team_id: {abbr, name, rank, current_pts, current_gd, ...}}}
    group_teams: dict[str, dict[str, dict]] = {}
    for g in matches_doc.get("groups", []):
        abbr = g.get("abbreviation", "?")
        group_teams[abbr] = {}
        for e in g.get("entries", []):
            t = e.get("team") or {}
            tid = str(t.get("id") or "")
            group_teams[abbr][tid] = {
                "id": tid,
                "abbr": t.get("abbr") or "?",
                "name": t.get("name") or "?",
                "name_zh": t.get("name_zh") or t.get("name") or "?",
                "flag": t.get("flag") or "🏳️",
                "rank": t.get("rank"),
                "current_pts": e.get("pts", 0) or 0,
                "current_gd": e.get("gd", 0) or 0,
                "current_gf": e.get("gf", 0) or 0,
                "current_ga": e.get("ga", 0) or 0,
                "current_mp": e.get("mp", 0) or 0,
            }

    # Build per-group remaining matches.
    # `group_abbr_for_match` requires looking at home+away team ids and
    # matching against group_teams.
    group_remaining: dict[str, list[dict]] = {g: [] for g in group_teams}
    for day in matches_doc.get("days", []):
        for m in day.get("matches", []):
            if m.get("stage_slug") != "group-stage":
                continue
            if m.get("status") not in ("SCHEDULED", "LIVE"):
                continue
            h_id = str(m.get("home", {}).get("id") or "")
            a_id = str(m.get("away", {}).get("id") or "")
            # Find group
            target_group = None
            for g_abbr, teams in group_teams.items():
                if h_id in teams and a_id in teams:
                    target_group = g_abbr
                    break
            if target_group is None:
                continue
            group_remaining[target_group].append({
                "match_id": str(m.get("id") or ""),
                "home_id": h_id,
                "away_id": a_id,
                "home_rank": m.get("home", {}).get("rank"),
                "away_rank": m.get("away", {}).get("rank"),
                "kickoff_local_date": m.get("kickoff_local_date"),
            })

    # Find match-window date range.
    all_dates = sorted({m["kickoff_local_date"] for ms in group_remaining.values() for m in ms if m.get("kickoff_local_date")})
    match_window = [all_dates[0], all_dates[-1]] if all_dates else []

    # Run Monte Carlo.
    n_sims = args.sims
    # Accumulators: per group per team per position, plus advance counts.
    counts: dict[str, dict[str, dict[str, int]]] = {
        g: {tid: {pos: 0 for pos in (1, 2, 3, 4)} for tid in teams}
        for g, teams in group_teams.items()
    }
    advance_counts: dict[str, dict[str, int]] = {
        g: {tid: 0 for tid in teams}
        for g, teams in group_teams.items()
    }

    # Pre-compute match outcome probs (don't re-evaluate every iteration).
    group_remaining_probs: dict[str, list[tuple]] = {}
    for g, ms in group_remaining.items():
        group_remaining_probs[g] = [
            (m, match_outcome_probs(m["home_rank"], m["away_rank"]))
            for m in ms
        ]

    for _ in range(n_sims):
        # For each group, simulate remaining matches and compute final standings.
        all_3rd_place: list[tuple[int, int, int, int, str, str]] = []
        # (pts, gd, gf, ga, group_abbr, team_id) — used to pick best 3rds across all groups

        per_group_standings: dict[str, list[tuple]] = {}

        for g, teams in group_teams.items():
            # Start each team with their current stats.
            live = {tid: dict(stats) for tid, stats in teams.items()}
            # Simulate remaining matches.
            for m, probs in group_remaining_probs.get(g, []):
                outcome = sample_outcome(probs, rng)
                h = live[m["home_id"]]
                a = live[m["away_id"]]
                if outcome == 0:  # home wins
                    h["current_pts"] += 3
                    h["current_gf"] += 1
                    a["current_ga"] += 1
                elif outcome == 1:  # draw
                    h["current_pts"] += 1
                    a["current_pts"] += 1
                    h["current_gf"] += 1
                    a["current_gf"] += 1
                    h["current_ga"] += 1
                    a["current_ga"] += 1
                else:  # away wins
                    a["current_pts"] += 3
                    a["current_gf"] += 1
                    h["current_ga"] += 1
                h["current_gd"] = h["current_gf"] - h["current_ga"]
                a["current_gd"] = a["current_gf"] - a["current_ga"]

            # Rank teams: higher pts, then higher GD, then higher GF.
            ranked = sorted(
                live.values(),
                key=lambda t: (t["current_pts"], t["current_gd"], t["current_gf"]),
                reverse=True,
            )
            per_group_standings[g] = ranked
            for pos, t in enumerate(ranked, 1):
                tid = t["id"]
                counts[g][tid][pos] += 1
                all_3rd_place.append((
                    t["current_pts"], t["current_gd"], t["current_gf"], t["current_ga"],
                    g, tid,
                ))

        # Pick best 3rd across all 12 groups (per FIFA tiebreaker).
        # Sort by pts, GD, GF, then goals scored (per FIFA WC rules).
        best_3rds = sorted(all_3rd_place, key=lambda x: (-x[0], -x[1], -x[2], -x[3]))
        best_3_set = {(g, tid) for _, _, _, _, g, tid in best_3rds[:ADVANCE_BEST3]}

        # Count advance = top 2 + best 3
        for g, ranked in per_group_standings.items():
            for pos, t in enumerate(ranked, 1):
                if pos <= ADVANCE_TOP2 or (g, t["id"]) in best_3_set:
                    advance_counts[g][t["id"]] += 1

    # Build output.
    groups_out = []
    for g, teams in group_teams.items():
        team_list = []
        for tid, t in teams.items():
            c = counts[g][tid]
            team_list.append({
                "id": tid,
                "abbr": t["abbr"],
                "name": t["name"],
                "name_zh": t["name_zh"],
                "flag": t["flag"],
                "rank": t["rank"],
                "current_pts": t["current_pts"],
                "current_gd": t["current_gd"],
                "current_mp": t["current_mp"],
                "p_1st": round(100.0 * c[1] / n_sims, 1),
                "p_2nd": round(100.0 * c[2] / n_sims, 1),
                "p_3rd": round(100.0 * c[3] / n_sims, 1),
                "p_4th": round(100.0 * c[4] / n_sims, 1),
                "p_advance": round(100.0 * advance_counts[g][tid] / n_sims, 1),
            })
        # Sort teams by current_pts desc for display.
        team_list.sort(key=lambda t: -t["current_pts"])
        groups_out.append({
            "name": g,
            "remaining_matches": [
                {
                    "match_id": m["match_id"],
                    "home_id": m["home_id"],
                    "away_id": m["away_id"],
                    "home_abbr": group_teams[g][m["home_id"]]["abbr"],
                    "away_abbr": group_teams[g][m["away_id"]]["abbr"],
                    "date": m["kickoff_local_date"],
                }
                for m in group_remaining.get(g, [])
            ],
            "teams": team_list,
        })

    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_simulations": n_sims,
        "match_window": match_window,
        "model": "elo + rank-gap-shrunk draw",
        "groups": groups_out,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    n_groups = len(groups_out)
    n_remaining = sum(len(g["remaining_matches"]) for g in groups_out)
    print(f"wrote {out_path} ({n_groups} groups, {n_remaining} remaining matches, {n_sims} sims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
