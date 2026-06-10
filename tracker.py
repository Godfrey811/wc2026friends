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
    fixtures.csv     date,kickoff,stage,group,home,away,venue   (display only;
                       not used in scoring. date as YYYY-MM-DD so it sorts.)

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
    "fixtures.csv": ["date", "kickoff", "stage", "group", "home", "away", "venue"],
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
    fixtures = load(data_dir, "fixtures.csv")

    goals_by_match: dict[str, list] = defaultdict(list)
    for g in goals:
        goals_by_match[g["match_id"]].append(g)
    cards_by_match: dict[str, list] = defaultdict(list)
    for c in cards:
        cards_by_match[c["match_id"]].append(c)

    # category buckets, keyed by team
    pts = defaultdict(lambda: defaultdict(float))     # team -> category -> points
    detail = defaultdict(lambda: defaultdict(float))  # team -> in_game sub-component -> RAW points
    #   (raw = before the 90'+ flip and opponent free-kick doubling are applied)

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
            d_open = d_pen = d_shoot = d_var = 0.0
            fk_scored = 0
            for g in tg:
                typ = (g.get("type") or "open").strip()
                if truthy(g.get("disallowed", "")):
                    p += -1.0  # VAR
                    d_var += -1.0
                    continue
                gp = GOAL_POINTS.get(typ, 0.0)
                p += gp
                if typ == "penalty":
                    d_pen += gp
                elif typ == "shootout":
                    d_shoot += gp
                else:
                    d_open += gp
                    if typ == "freekick":
                        fk_scored += 1
                if typ != "shootout":
                    scored += 1
                mn = parse_minute(g.get("minute", ""))
                # 90'+ = from 90:00 onwards - the 90th minute and all its injury/
                # stoppage time ("90" or "90+X"), NOT extra time (91-120).
                # parse_minute("90+5") -> 90, "105" -> 105.
                if typ != "shootout" and mn == 90:
                    ninety += 1

            def hit_2367(rows):
                for g in rows:
                    if truthy(g.get("disallowed", "")) or (g.get("type") == "shootout"):
                        continue
                    if parse_minute(g.get("minute", "")) in (23, 67):
                        return True
                return False

            b2367 = 4.0 if (hit_2367(tg) or hit_2367(og)) else 0.0   # capped at +4 per game
            b0sot = 4.0 if sot.get(team) == 0 else 0.0
            cs = -1.0 if scored == 0 else 0.0                        # opposition clean sheet
            reddice = 0.0
            for c in cards_by_match.get(mid, []):
                if c["team"] == team and (c.get("color") == "red") and (c.get("dice") or "").strip():
                    d = int(c["dice"])
                    reddice += (d / 2) if d % 2 == 1 else -(d / 2)
            p += b2367 + b0sot + cs + reddice
            if ninety % 2 == 1:
                p = -p  # 90'+ flip (pairs cancel)
            opp_fk = sum(1 for g in og if g.get("type") == "freekick" and not truthy(g.get("disallowed", "")))
            p *= (2 ** opp_fk)
            pts[team]["in_game"] += p

            detail[team]["goal_open"] += d_open
            detail[team]["goal_pen"] += d_pen
            detail[team]["goal_shootout"] += d_shoot
            detail[team]["var"] += d_var
            detail[team]["bonus_2367"] += b2367
            detail[team]["bonus_0sot"] += b0sot
            detail[team]["clean_sheet"] += cs
            detail[team]["red_dice"] += reddice
            detail[team]["freekick_goals"] += fk_scored

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
        "detail": detail,
        "goals_for": dict(goals_for),
        "team_totals": team_totals,
        "owner_totals": dict(owner_totals),
        "fixtures": fixtures,
    }


# --- output ------------------------------------------------------------------

CATEGORY_ORDER = [
    "in_game", "prime", "progression", "fewest_goals", "fewest_cards",
    "quickest_goal", "quickest_yellow", "fastest_sub", "fastest_own_goal",
    "youngest_scorer", "oldest_scorer", "longest_name", "shortest_name",
]

CAT_LABELS = {
    "in_game": "In-game points", "prime": "Prime-goals penalty",
    "progression": "Progression", "fewest_goals": "Fewest goals",
    "fewest_cards": "Fewest cards", "quickest_goal": "Quickest goal",
    "quickest_yellow": "Quickest yellow card", "fastest_sub": "Fastest substitution",
    "fastest_own_goal": "Fastest own goal", "youngest_scorer": "Youngest scorer",
    "oldest_scorer": "Oldest scorer", "longest_name": "Longest name",
    "shortest_name": "Shortest name",
}

CAT_SHORT = {
    "in_game": "In-game", "prime": "Prime", "progression": "Prog", "fewest_goals": "Few.G",
    "fewest_cards": "Few.C", "quickest_goal": "Q.goal", "quickest_yellow": "Q.yel",
    "fastest_sub": "F.sub", "fastest_own_goal": "F.OG", "youngest_scorer": "Young",
    "oldest_scorer": "Old", "longest_name": "Long", "shortest_name": "Short",
}

CAT_DESC = {
    "in_game": "In-game points: goals (open +0.5, pen -1.5, shootout -0.5, free-kick 0), VAR -1, "
               "a goal/concede in the 23rd or 67th min +4, 0 shots on target +4, clean sheet against you -1, "
               "red-card dice - then the 90'+ flip and opponent free-kick doubling are applied.",
    "prime": "-3 while the team is on a PRIME number of (non-shootout) goals.",
    "progression": "Stage points: R32 +1, R16 +2, QF +3, SF +5, runner-up +8, winner +10 "
                   "(flipped to negative if a 90'+ goal loses their elimination game).",
    "fewest_goals": "+7 shared between the team(s) that have scored the FEWEST goals.",
    "fewest_cards": "+7 shared between the team(s) with the FEWEST cards.",
    "quickest_goal": "Ranked 10/8/5/3/2/1 for the quickest goal of the tournament (earliest minute).",
    "quickest_yellow": "Ranked 10/8/5/3/2/1 for the quickest yellow card.",
    "fastest_sub": "Ranked 10/8/5/3/2/1 for the fastest substitution.",
    "fastest_own_goal": "Ranked 10/8/5/3/2/1 for the fastest own goal.",
    "youngest_scorer": "Ranked 10/8/5/3/2/1 for the youngest goalscorer.",
    "oldest_scorer": "Ranked -10/-8/-5/-3/-2/-1 for the OLDEST goalscorer (a penalty).",
    "longest_name": "Ranked 10/8/5/3/2/1 for the longest goalscorer name.",
    "shortest_name": "Ranked -10/-8/-5/-3/-2/-1 for the SHORTEST goalscorer name (a penalty).",
}

# in_game sub-components (raw, before 90'+ flip / opp free-kick doubling)
DETAIL_ORDER = ["goal_open", "goal_pen", "goal_shootout", "var",
                "bonus_2367", "bonus_0sot", "clean_sheet", "red_dice", "freekick_goals"]
DETAIL_LABELS = {
    "goal_open": "Open goals (+)", "goal_pen": "Pens (-)", "goal_shootout": "Shootout pens (-)",
    "var": "VAR ruled out (-)", "bonus_2367": "23'/67' bonus (+)", "bonus_0sot": "0 shots-on-target (+)",
    "clean_sheet": "Clean sheet vs (-)", "red_dice": "Red-card dice", "freekick_goals": "Free-kick goals",
}


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

    standings = sorted(result["owner_totals"].items(), key=lambda kv: (-kv[1], kv[0]))
    with open(os.path.join(out_dir, "standings.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["position", "owner", "total"])
        for i, (o, total) in enumerate(standings, 1):
            w.writerow([i, o or "(undrafted)", round(total, 2)])


def print_standings(result: dict) -> None:
    standings = sorted(result["owner_totals"].items(), key=lambda kv: (-kv[1], kv[0]))
    print("\n  WC2026 Friends — standings")
    print("  " + "-" * 30)
    for i, (o, total) in enumerate(standings, 1):
        print(f"  {i:>2}. {o or '(undrafted)':<18} {total:>7.2f}")
    print()


def write_html(result: dict, out_dir: str) -> None:
    """Render a self-contained index.html leaderboard for GitHub Pages."""
    from datetime import datetime, timezone
    os.makedirs(out_dir, exist_ok=True)
    owner, tt, teams = result["owner"], result["team_totals"], result["teams"]
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    standings = sorted(result["owner_totals"].items(), key=lambda kv: (-kv[1], kv[0]))
    lb = "\n".join(
        f"<tr><td>{i}</td><td>{o or '(undrafted)'}</td><td>{round(total, 2):g}</td></tr>"
        for i, (o, total) in enumerate(standings, 1)) or '<tr><td colspan="3">-</td></tr>'

    def ordinal(n):
        suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf}"
    team_rank = {t: 1 + sum(1 for o in teams if tt[o] > tt[t]) for t in teams}

    # All teams, alphabetical, with current points rank out of 48
    team_rows = "\n".join(
        f"<tr><td>{t}</td><td>{owner.get(t, '') or '-'}</td><td>{round(tt[t], 2):g}</td>"
        f"<td>{ordinal(team_rank[t])}</td></tr>"
        for t in sorted(teams))

    # By player: their three teams (by pot) + each team's rank out of 48
    pot_of = {t: i for i, pl in enumerate([POT1, POT2, POT3], 1) for t in pl}
    owner_pots = defaultdict(dict)
    for t in teams:
        if owner.get(t, ""):
            owner_pots[owner[t]][pot_of.get(t, 0)] = t

    seed_rank = {t: i for i, t in enumerate(POT1 + POT2 + POT3, 1)}  # 1 = strongest by odds

    def teamcell(t):
        return f"{t} <span class='r'>(#{seed_rank.get(t, 0)})</span>" if t else "-"
    def avg_seed(o):                       # mean of the player's three team seeds (lower = stronger)
        rs = [seed_rank[t] for t in owner_pots[o].values() if t]
        return sum(rs) / len(rs) if rs else 0.0
    player_rows = "\n".join(
        f"<tr><td><b>{o}</b></td><td>{round(result['owner_totals'].get(o, 0), 2):g}</td>"
        f"<td>{avg_seed(o):.2f}</td>"
        f"<td>{teamcell(owner_pots[o].get(1))}</td><td>{teamcell(owner_pots[o].get(2))}</td>"
        f"<td>{teamcell(owner_pots[o].get(3))}</td></tr>"
        for o in sorted((o for o in result['owner_totals'] if o),
                        key=lambda o: (avg_seed(o), o)))   # strongest average seed first

    pts, detail, gf = result["pts"], result["detail"], result["goals_for"]

    def teamlabel(t):
        o = owner.get(t, "")
        return f"{t}{(' (' + o + ')') if o else ''}"

    # Category extremes: per category, the team gaining the most and losing the most.
    # Tie-aware: when many teams share the extreme (e.g. everyone level early on), say so.
    def extreme_cell(vals, positive):
        if not vals:
            return "-"
        best = max(v for _, v in vals) if positive else min(v for _, v in vals)
        if (positive and best <= 0) or (not positive and best >= 0):
            return "-"
        tied = [t for t, v in vals if v == best]
        s = f"{'+' if best > 0 else ''}{round(best, 2):g}"
        if len(tied) == 1:
            return f"{teamlabel(tied[0])} <b>{s}</b>"
        return f"<b>{len(tied)} teams tied</b> ({s} each)"

    cat_rows = ""
    for cat in CATEGORY_ORDER:
        if cat == "prime":      # prime has its own section below
            continue
        vals = [(t, pts[t].get(cat, 0.0)) for t in teams if pts[t].get(cat, 0.0)]
        cat_rows += (f"<tr><td>{CAT_LABELS.get(cat, cat)}</td>"
                     f"<td>{extreme_cell(vals, True)}</td>"
                     f"<td>{extreme_cell(vals, False)}</td></tr>\n")

    # Prime watch: teams currently on a prime number of (non-shootout) goals.
    on_prime = [t for t in teams if pts[t].get("prime", 0.0)]
    n_on, n_total = len(on_prime), len(teams)
    n_off = n_total - n_on
    prime_rows = "\n".join(
        f"<tr><td>{t}</td><td>{owner.get(t, '') or '-'}</td><td>{gf.get(t, 0)}</td></tr>"
        for t in sorted(on_prime, key=lambda t: gf.get(t, 0), reverse=True)) \
        or '<tr><td colspan="3">none on a prime right now</td></tr>'
    owner_prime: dict[str, int] = {}
    for t in on_prime:
        o = owner.get(t, "")
        if o:
            owner_prime[o] = owner_prime.get(o, 0) + 1
    prime_person = "\n".join(
        f"<tr><td>{o}</td><td>{c}</td><td>{-3 * c:g}</td></tr>"
        for o, c in sorted(owner_prime.items(), key=lambda kv: -kv[1])) \
        or '<tr><td colspan="3">nobody affected yet</td></tr>'

    # Goal-points breakdown (in_game sub-components) for teams that have any.
    gd_teams = [t for t in teams if any(detail[t].get(k) for k in DETAIL_ORDER)]
    gd_rows = "\n".join(
        "<tr><td>" + teamlabel(t) + "</td>" +
        "".join(f"<td>{round(detail[t].get(k, 0), 2):g}</td>" for k in DETAIL_ORDER) + "</tr>"
        for t in sorted(gd_teams, key=lambda t: pts[t].get("in_game", 0.0), reverse=True)) \
        or f'<tr><td colspan="{len(DETAIL_ORDER) + 1}">no goals yet</td></tr>'
    gd_head = "<th>Team</th>" + "".join(f"<th>{DETAIL_LABELS[k]}</th>" for k in DETAIL_ORDER)

    # Fixtures: who plays whom on which day (display only; owners annotated).
    fixtures = result.get("fixtures", [])
    def fx_key(r):
        return ((r.get("date") or "").strip(), (r.get("kickoff") or "").strip())
    def matchcell(t):
        o = owner.get((t or "").strip(), "")
        return f"{t} <span class='o'>({o})</span>" if o else f"{t}"
    fx_rows = ""
    for r in sorted((r for r in fixtures
                     if (r.get("home") or "").strip() and (r.get("away") or "").strip()),
                    key=fx_key):
        sg = ((r.get("stage") or "").strip() + " " + (r.get("group") or "").strip()).strip() or "-"
        fx_rows += (f"<tr><td>{(r.get('date') or '').strip() or '-'}</td>"
                    f"<td>{(r.get('kickoff') or '').strip() or '-'}</td>"
                    f"<td>{sg}</td>"
                    f"<td>{matchcell(r['home'].strip())} <span class='r'>v</span> "
                    f"{matchcell(r['away'].strip())}</td>"
                    f"<td>{(r.get('venue') or '').strip() or '-'}</td></tr>\n")
    fx_rows = fx_rows or ('<tr><td colspan="5">no fixtures loaded yet - '
                          'add rows to data/fixtures.csv</td></tr>')

    # Full team x category grid (full labels + descriptions as hover tooltips).
    grid_head = ('<th title="The team">Team</th><th title="Who drafted it">Owner</th>'
                 + "".join(f'<th title="{CAT_LABELS[c]} - {CAT_DESC[c]}">{CAT_LABELS[c]}</th>'
                           for c in CATEGORY_ORDER)
                 + '<th title="Sum of every category">Total</th>')
    grid_rows = "\n".join(
        f"<tr><td>{t}</td><td>{owner.get(t, '') or '-'}</td>" +
        "".join(f"<td>{round(pts[t].get(c, 0), 2):g}</td>" for c in CATEGORY_ORDER) +
        f"<td><b>{round(tt[t], 2):g}</b></td></tr>"
        for t in sorted(teams, key=lambda t: tt[t], reverse=True))

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC 2026 Friends Pool</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:880px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} h2{{margin-top:2rem;font-size:1.2rem}} .sub{{color:#666;margin-top:0}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
 th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e3e6ea}}
 th{{background:#fafbfc}} a{{color:#2563eb}} .o{{color:#16a34a;font-size:.85rem}}
 .lb td:last-child,.lb th:last-child,.tt td:last-child,.tt th:last-child{{text-align:right}}
 .scroll{{overflow-x:auto}} .grid{{font-size:.78rem}}
 .grid td,.grid th{{padding:.25rem .35rem}} .grid td{{white-space:nowrap;text-align:center}}
 .grid th{{white-space:normal;vertical-align:bottom;line-height:1.15}}
 .grid td:first-child,.grid th:first-child{{text-align:left}}
 .num td:not(:first-child),.num th:not(:first-child){{text-align:right}}
 .r{{color:#888;font-size:.85rem}} .pl td:nth-child(2){{text-align:right}}
 .wide{{width:98vw;max-width:1700px;position:relative;left:50%;transform:translateX(-50%)}}
 table.sortable th{{cursor:pointer;user-select:none;text-decoration:underline dotted #bbb}}
 table.sortable th:hover{{background:#eef2ff;color:#2563eb}}
 table.sortable th::after{{content:" \\2195";color:#bbb;font-size:.8em}}
</style></head><body>
<h1>🏆 WC 2026 Friends Pool</h1>
<p class="sub">Draft pool - 16 players, 3 teams each (one per pot). Auto-updated {updated}.
<a href="rules.pdf">📜 full rules (PDF)</a></p>

<h2>Leaderboard</h2>
<table class="lb sortable"><tr><th>#</th><th>Player</th><th>Points</th></tr>
{lb}
</table>

<h2>By player</h2>
<p class="sub">Each player (sorted by average seed, strongest squad first) and their three teams (Pot 1 / 2 / 3). The #number is the team's
<b>seed out of 48</b> by Polymarket winner odds, within the draft pot tiers (#1 = strongest, #48 = longest shot).</p>
<table class="pl sortable"><tr><th>Player</th><th>Total</th><th>Avg seed</th><th>Pot 1</th><th>Pot 2</th><th>Pot 3</th></tr>
{player_rows}
</table>

<h2>📅 Fixtures</h2>
<p class="sub">All 104 matches - who plays whom, and when (your players' teams in green; knockout slots show the bracket code until teams are known). Kickoffs are <b>local venue time</b>. Click a header to sort - by date, kickoff, stage or venue.</p>
<div class="scroll"><table class="fx sortable"><tr><th>Date</th><th>Kickoff</th><th>Stage</th><th>Match</th><th>Venue</th></tr>
{fx_rows}
</table></div>

<h2>All teams (A-Z)</h2>
<table class="tt sortable"><tr><th>Team</th><th>Owner</th><th>Points</th><th>Rank</th></tr>
{team_rows}
</table>

<h2>Category extremes</h2>
<p class="sub">For every scoring category: the team gaining the most, and the team losing the most (owner in brackets).</p>
<table class="num"><tr><th>Category</th><th>🟢 Most points</th><th>🔴 Most lost</th></tr>
{cat_rows}
</table>

<h2>Goal-points breakdown</h2>
<p class="sub">Where each team's in-game points come from (raw, before the 90'+ flip &amp; opponent free-kick doubling).
So you can see who's banked the most from goals and who's bled the most from pens / VAR. The 90'+ flip and
free-kick doubling only ever touch these in-game points - never the ranked prizes (fastest / youngest /
fewest etc.) or the prime penalty.</p>
<div class="scroll wide"><table class="num grid sortable"><tr>{gd_head}</tr>
{gd_rows}
</table></div>

<h2>🔢 Prime watch</h2>
<p class="sub"><b>{n_on}</b> of {n_total} teams are on a <b>prime</b> number of goals right now
(<b>{n_off}</b> are not). Each prime team is a <b>-3</b> hit to its owner.</p>
<table class="tt num"><tr><th>Player</th><th>Teams on a prime</th><th>Points lost</th></tr>
{prime_person}
</table>
<p class="sub">Which teams:</p>
<table class="tt"><tr><th>Team</th><th>Owner</th><th>Goals</th></tr>
{prime_rows}
</table>

<h2>Full breakdown - every team, every category</h2>
<div class="scroll wide"><table class="num grid sortable"><tr>{grid_head}</tr>
{grid_rows}
</table></div>
<p class="sub"><b>Hover</b> any column header for its full scoring rule, and <b>click</b> a header to sort by it.</p>

<p class="sub"><a href="standings.csv">standings.csv</a> · <a href="team_breakdown.csv">team_breakdown.csv</a> · <a href="rules.pdf">rules.pdf</a></p>
</body></html>"""
    sort_js = """<script>
document.querySelectorAll('table.sortable').forEach(function(tbl){
  var head = tbl.rows[0];
  Array.prototype.forEach.call(head.cells, function(th, i){
    th.addEventListener('click', function(){
      var asc = th.getAttribute('data-asc') !== 'true';
      Array.prototype.forEach.call(head.cells, function(c){ c.removeAttribute('data-asc'); });
      th.setAttribute('data-asc', asc);
      var body = head.parentNode;
      var rows = Array.prototype.slice.call(tbl.rows, 1);
      rows.sort(function(a, b){
        var x = a.cells[i].innerText.trim(), y = b.cells[i].innerText.trim();
        var nx = parseFloat(x.replace(/[^0-9.\\-]/g, '')), ny = parseFloat(y.replace(/[^0-9.\\-]/g, ''));
        var num = !isNaN(nx) && !isNaN(ny) && /[0-9]/.test(x) && /[0-9]/.test(y);
        var c = num ? nx - ny : x.localeCompare(y);
        return asc ? c : -c;
      });
      rows.forEach(function(r){ body.appendChild(r); });
    });
  });
});
</script>"""
    html = html.replace("</body></html>", sort_js + "\n</body></html>")
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)


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
    write_html(result, args.out)
    # copy the rules PDF alongside the site so it's downloadable from Pages
    import shutil
    if os.path.exists("rules.pdf"):
        shutil.copy("rules.pdf", os.path.join(args.out, "rules.pdf"))
    print_standings(result)
    print(f"  Wrote {args.out}/index.html, standings.csv, team_breakdown.csv")


if __name__ == "__main__":
    main()
