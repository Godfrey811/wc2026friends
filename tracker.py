"""WC2026 Friends pool — scoring tracker.

Reads the draft + match-event CSVs from a data directory and computes each
team's points and the player standings, following RULES.md.

Usage:
    python tracker.py --init            # scaffold empty templates into ./data
    python tracker.py                   # score ./data, write ./out, print table
    python tracker.py --data data_sample

DATA MODEL (all in the --data dir):
    draft.csv        pot,team,owner
    matches.csv      match_id,stage,team_a,team_b,team_a_sot,team_b_sot
    goals.csv        match_id,team,minute,type,scorer,scorer_age,disallowed
                       type = open | freekick | penalty | shootout
                       disallowed = 1 for a VAR-chalked-off goal (else blank/0)
    cards.csv        match_id,team,minute,color,dice
                       color = yellow | red ; dice = the d6 roll for a red card
    subs.csv         match_id,team,minute
    own_goals.csv    match_id,team,minute        (team = the side that erred)
    progression.csv  team,stage,flip
                       stage = group|R32|R16|QF|SF|RU|winner|third
                       (SF = 4th place; third = 3rd-place playoff winner)
                       flip = 1 if a 90'+ goal in their elimination game flips it

ACCEPTED SIMPLIFICATIONS (confirmed intentional — not bugs):
  * Own goals feed only the fastest-own-goal ranking; they do NOT affect the
    benefiting team's goals-for / clean-sheet / prime tally.
  * Clean sheets are a flat -1 per goalless match: extra-time exclusion and the
    own-both-teams 0-0 = 0 nuance are deliberately not modelled.
  * Ranked categories enforce one prize per owner; ties resolve by input order
    (no tie-splitting or "most recent occurrence" tiebreak).
  * Opponent free-kick doubling stacks (x2 per free kick) and is applied after
    the 90'+ flip.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict

# Pot definitions are the single source of truth in rules.py.
from rules import POT1, POT2, POT3

STAGE_POINTS = {
    "group": 0, "R32": 1, "R16": 2, "QF": 3,
    "SF": 5, "RU": 8, "winner": 10, "third": 0,
}

POS_DIST = [10, 8, 5, 3, 2, 1]
NEG_DIST = [-10, -8, -5, -3, -2, -1]

GOAL_POINTS = {"open": 0.5, "freekick": 0.0, "penalty": -1.5, "shootout": -0.5}


# --- small helpers -----------------------------------------------------------

def parse_minute(raw: str) -> int | None:
    """'67' -> 67, '90+3' -> 90, '' -> None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    base = raw.split("+", 1)[0].strip()
    try:
        return int(base)
    except ValueError:
        return None


def truthy(raw: str) -> bool:
    return (raw or "").strip().lower() in {"1", "y", "yes", "true"}


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def load(data_dir: str, name: str) -> list[dict]:
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh)]


# --- scaffolding -------------------------------------------------------------

TEMPLATE_HEADERS = {
    "matches.csv": ["match_id", "stage", "team_a", "team_b", "team_a_sot", "team_b_sot"],
    "goals.csv": ["match_id", "team", "minute", "type", "scorer", "scorer_age", "disallowed"],
    "cards.csv": ["match_id", "team", "minute", "color", "dice"],
    "subs.csv": ["match_id", "team", "minute"],
    "own_goals.csv": ["match_id", "team", "minute"],
    "progression.csv": ["team", "stage", "flip"],
}


def init_templates(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    # draft.csv pre-filled with pots + teams, owner left blank for the draft.
    draft_path = os.path.join(data_dir, "draft.csv")
    with open(draft_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pot", "team", "owner"])
        for pot_no, pot in ((1, POT1), (2, POT2), (3, POT3)):
            for team in pot:
                w.writerow([pot_no, team, ""])
    # progression.csv pre-filled with all teams at 'group'.
    prog_path = os.path.join(data_dir, "progression.csv")
    with open(prog_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "stage", "flip"])
        for team in POT1 + POT2 + POT3:
            w.writerow([team, "group", ""])
    for name, headers in TEMPLATE_HEADERS.items():
        if name == "progression.csv":
            continue
        with open(os.path.join(data_dir, name), "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(headers)
    print(f"Scaffolded templates in {data_dir}/ — fill draft.csv owners, then add match data.")


# --- the engine --------------------------------------------------------------

def score(data_dir: str) -> dict:
    draft = load(data_dir, "draft.csv")
    owner = {r["team"]: (r.get("owner") or "").strip() for r in draft}
    teams = [r["team"] for r in draft]

    matches = load(data_dir, "matches.csv")
    goals = load(data_dir, "goals.csv")
    cards = load(data_dir, "cards.csv")
    subs = load(data_dir, "subs.csv")
    own_goals = load(data_dir, "own_goals.csv")
    progression = load(data_dir, "progression.csv")

    goals_by_match: dict[str, list] = defaultdict(list)
    for g in goals:
        goals_by_match[g["match_id"]].append(g)
    cards_by_match: dict[str, list] = defaultdict(list)
    for c in cards:
        cards_by_match[c["match_id"]].append(c)

    # category buckets, keyed by team
    pts = defaultdict(lambda: defaultdict(float))  # team -> category -> points

    # ---- per-match in-game scoring ----
    for m in matches:
        mid = m["match_id"]
        sot = {}
        for side in ("a", "b"):
            raw = (m.get(f"team_{side}_sot") or "").strip()
            sot[m[f"team_{side}"]] = int(raw) if raw.isdigit() else None
        mg = goals_by_match.get(mid, [])
        for team, opp in ((m["team_a"], m["team_b"]), (m["team_b"], m["team_a"])):
            tg = [g for g in mg if g["team"] == team]
            og = [g for g in mg if g["team"] == opp]
            p = 0.0
            scored = 0
            ninety = 0
            for g in tg:
                typ = (g.get("type") or "open").strip()
                if truthy(g.get("disallowed", "")):
                    p += -1.0  # VAR
                    continue
                p += GOAL_POINTS.get(typ, 0.0)
                if typ != "shootout":
                    scored += 1
                mn = parse_minute(g.get("minute", ""))
                if typ != "shootout" and mn is not None and mn >= 90:
                    ninety += 1

            def hit_2367(rows):
                for g in rows:
                    if truthy(g.get("disallowed", "")) or (g.get("type") == "shootout"):
                        continue
                    if parse_minute(g.get("minute", "")) in (23, 67):
                        return True
                return False

            if hit_2367(tg) or hit_2367(og):
                p += 4.0  # capped at +4 per game
            if sot.get(team) == 0:
                p += 4.0
            if scored == 0:
                p += -1.0  # opposition clean sheet
            for c in cards_by_match.get(mid, []):
                if c["team"] == team and (c.get("color") == "red") and (c.get("dice") or "").strip():
                    d = int(c["dice"])
                    p += (d / 2) if d % 2 == 1 else -(d / 2)
            if ninety % 2 == 1:
                p = -p  # 90'+ flip (pairs cancel)
            opp_fk = sum(1 for g in og if g.get("type") == "freekick" and not truthy(g.get("disallowed", "")))
            p *= (2 ** opp_fk)
            pts[team]["in_game"] += p

    # ---- prime number of goals (excl. shootouts & disallowed) ----
    goals_for = defaultdict(int)
    for g in goals:
        if truthy(g.get("disallowed", "")) or g.get("type") == "shootout":
            continue
        goals_for[g["team"]] += 1
    for team in teams:
        if is_prime(goals_for[team]):
            pts[team]["prime"] += -3.0

    # ---- progression ----
    for r in progression:
        team = r["team"]
        val = STAGE_POINTS.get((r.get("stage") or "group").strip(), 0)
        if r.get("stage") == "third":
            val = STAGE_POINTS["SF"] - 5  # SF reward then -5 = 0
        if truthy(r.get("flip", "")):
            val = -val
        pts[team]["progression"] += val

    # ---- ranked categories ----
    def extreme(rows, key, agg, minute_key=None):
        """min/max of `key` per team over rows (skipping disallowed goals)."""
        out: dict[str, float] = {}
        for r in rows:
            if r.get("type") == "shootout" or truthy(r.get("disallowed", "")):
                continue
            team = r["team"]
            if minute_key:
                v = parse_minute(r.get(minute_key, ""))
            else:
                raw = (r.get(key) or "").strip()
                if not raw:
                    continue
                v = float(raw) if "." in raw or key == "scorer_age" else len(raw)
            if v is None:
                continue
            if team not in out:
                out[team] = v
            else:
                out[team] = (min if agg == "min" else max)(out[team], v)
        return out

    yellows = [c for c in cards if c.get("color") == "yellow"]
    scored_goals = [g for g in goals if not truthy(g.get("disallowed", "")) and g.get("type") != "shootout"]

    metrics = {
        "quickest_goal": (extreme(scored_goals, "minute", "min", minute_key="minute"), POS_DIST, "min"),
        "quickest_yellow": (extreme(yellows, "minute", "min", minute_key="minute"), POS_DIST, "min"),
        "fastest_sub": (extreme(subs, "minute", "min", minute_key="minute"), POS_DIST, "min"),
        "fastest_own_goal": (extreme(own_goals, "minute", "min", minute_key="minute"), POS_DIST, "min"),
        "youngest_scorer": (extreme(scored_goals, "scorer_age", "min"), POS_DIST, "min"),
        "oldest_scorer": (extreme(scored_goals, "scorer_age", "max"), NEG_DIST, "max"),
        "longest_name": (extreme(scored_goals, "scorer", "max"), POS_DIST, "max"),
        "shortest_name": (extreme(scored_goals, "scorer", "min"), NEG_DIST, "min"),
    }

    for cat, (values, dist, better) in metrics.items():
        ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=(better == "max"))
        used_owners = set()
        idx = 0
        for team, _v in ranked:
            o = owner.get(team, "")
            if o in used_owners:  # one prize per owner per category
                continue
            if idx >= len(dist):
                break
            pts[team][cat] += dist[idx]
            used_owners.add(o)
            idx += 1

    # ---- flat fewest-goals / fewest-cards (+7, tie-split across teams) ----
    cards_total = defaultdict(int)
    for c in cards:
        cards_total[c["team"]] += 1

    def award_fewest(tally: dict, cat: str):
        if not teams:
            return
        full = {t: tally.get(t, 0) for t in teams}
        best = min(full.values())
        winners = [t for t, v in full.items() if v == best]
        share = 7.0 / len(winners)
        for t in winners:
            pts[t][cat] += share

    award_fewest(goals_for, "fewest_goals")
    award_fewest(cards_total, "fewest_cards")

    # ---- totals ----
    team_totals = {t: sum(pts[t].values()) for t in teams}
    owner_totals = defaultdict(float)
    for t in teams:
        owner_totals[owner.get(t, "")] += team_totals[t]

    return {
        "owner": owner,
        "teams": teams,
        "pts": pts,
        "team_totals": team_totals,
        "owner_totals": dict(owner_totals),
    }


# --- output ------------------------------------------------------------------

CATEGORY_ORDER = [
    "in_game", "prime", "progression", "fewest_goals", "fewest_cards",
    "quickest_goal", "quickest_yellow", "fastest_sub", "fastest_own_goal",
    "youngest_scorer", "oldest_scorer", "longest_name", "shortest_name",
]


def write_outputs(result: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    pts, teams, owner = result["pts"], result["teams"], result["owner"]

    with open(os.path.join(out_dir, "team_breakdown.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "owner"] + CATEGORY_ORDER + ["total"])
        for t in sorted(teams, key=lambda t: result["team_totals"][t], reverse=True):
            row = [t, owner.get(t, "")] + [round(pts[t].get(c, 0.0), 2) for c in CATEGORY_ORDER]
            row.append(round(result["team_totals"][t], 2))
            w.writerow(row)

    standings = sorted(result["owner_totals"].items(), key=lambda kv: kv[1], reverse=True)
    with open(os.path.join(out_dir, "standings.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["position", "owner", "total"])
        for i, (o, total) in enumerate(standings, 1):
            w.writerow([i, o or "(undrafted)", round(total, 2)])


def print_standings(result: dict) -> None:
    standings = sorted(result["owner_totals"].items(), key=lambda kv: kv[1], reverse=True)
    print("\n  WC2026 Friends — standings")
    print("  " + "-" * 30)
    for i, (o, total) in enumerate(standings, 1):
        print(f"  {i:>2}. {o or '(undrafted)':<18} {total:>7.2f}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="WC2026 Friends scoring tracker")
    ap.add_argument("--data", default="data", help="data directory (default: data)")
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    ap.add_argument("--init", action="store_true", help="scaffold empty templates and exit")
    args = ap.parse_args()

    if args.init:
        init_templates(args.data)
        return

    if not os.path.exists(os.path.join(args.data, "draft.csv")):
        print(f"No draft.csv in {args.data}/. Run `python tracker.py --init` first.")
        return

    result = score(args.data)
    write_outputs(result, args.out)
    print_standings(result)
    print(f"  Wrote {args.out}/standings.csv and {args.out}/team_breakdown.csv")


if __name__ == "__main__":
    main()
