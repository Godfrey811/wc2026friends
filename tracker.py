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
                       disallowed = 1 ONLY for a goal that was GIVEN then chalked
                         off by VAR (a real-time offside flag is not a goal at all,
                         so don't record it); else blank/0
    cards.csv        match_id,team,minute,color,dice
                       color = yellow | red ; dice = the d6 roll for a red card
    subs.csv         match_id,team,minute
    own_goals.csv    match_id,team,minute        (team = the side that erred)
    progression.csv  team,stage,flip,out
                       stage = group|R32|R16|QF|SF|RU|winner|third
                       (SF = 4th place; third = 3rd-place playoff winner)
                       flip = 1 if a 90'+ goal in their elimination game flips it
                       out  = the DATE the team is confirmed out, YYYY-MM-DD
                              (drives the early-exit bonus; earlier date ranks
                              ahead, so a side eliminated earlier in the group
                              beats one not settled until later. Leave blank while
                              still in; a plain 1 also works but then teams only
                              separate by stage, not by when they actually went out)
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
    "SF": 5, "RU": 8, "winner": 10, "third": -5,  # 3rd-place playoff winner: -5 overall
}

# How early a team was knocked out (lower = out sooner), for the early-exit bonus.
# A 3rd/4th-place side exits around the semis; a champion never exits.
STAGE_RANK = {
    "group": 0, "R32": 1, "R16": 2, "QF": 3, "SF": 4, "third": 4, "RU": 5, "winner": 6,
}
STAGE_LABEL = {
    "group": "Group stage", "R32": "Round of 32", "R16": "Round of 16",
    "QF": "Quarter-final", "SF": "Semi-final", "third": "3rd-place game",
    "RU": "Final (runner-up)", "winner": "Champion (never out)",
}
# Points by finishing position in the early-exit race (1st all-out = position 1).
EARLY_EXIT_POINTS = [5, 4, 3, 3, 2, 2, 1, 1] + [0] * 8

# Live-leaderboard position markers (purely cosmetic). 1st gets 👑 (wins the shirt,
# everyone chips in <=£150); last gets 💩 (buys seven others dessert).
# The end-of-tournament £20 dice gift lands on two RANDOM positions via the d16 -
# it is NOT fixed to 4 & 7 (that was only an example roll). Once you roll it, set
# these two and the board flags them: payer 😈 (has to pay - bad), receiver 😇
# (gets the gift - good). Leave None until rolled.
DICE_PAYER = 4          # finishing position that has to pay (£20 dice gift)
DICE_RECEIVER = 7       # finishing position that gets the gift

POS_DIST = [10, 8, 5, 3, 2, 1]
NEG_DIST = [-10, -8, -5, -3, -2, -1]

GOAL_POINTS = {"open": 0.5, "freekick": 0.0, "penalty": -1.5, "shootout": -0.5}

# Short team codes (FIFA-style) for the detail labels.
TEAM_ABBR = {
    "Spain": "ESP", "France": "FRA", "England": "ENG", "Portugal": "POR", "Argentina": "ARG",
    "Brazil": "BRA", "Germany": "GER", "Netherlands": "NED", "Norway": "NOR", "Belgium": "BEL",
    "Colombia": "COL", "Morocco": "MAR", "Mexico": "MEX", "USA": "USA", "Switzerland": "SUI",
    "Turkey": "TUR", "Japan": "JPN", "Uruguay": "URU", "Croatia": "CRO", "Ecuador": "ECU",
    "Senegal": "SEN", "Austria": "AUT", "Ivory Coast": "CIV", "Canada": "CAN", "Sweden": "SWE",
    "Paraguay": "PAR", "Scotland": "SCO", "South Korea": "KOR", "Egypt": "EGY", "Algeria": "ALG",
    "Czechia": "CZE", "Bosnia & Herzegovina": "BIH", "Australia": "AUS", "Ghana": "GHA",
    "South Africa": "RSA", "Panama": "PAN", "DR Congo": "COD", "Saudi Arabia": "KSA",
    "Tunisia": "TUN", "Uzbekistan": "UZB", "New Zealand": "NZL", "Cape Verde": "CPV",
    "Jordan": "JOR", "Iraq": "IRQ", "Haiti": "HAI", "Qatar": "QAT", "Curaçao": "CUW", "Iran": "IRN",
}


def abbr(team):
    return TEAM_ABBR.get(team, (team or "")[:3].upper())


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


def name_letters(s):
    """Count LETTERS in a name (spaces/hyphens/punctuation excluded, accents count).
    'Julián Quiñones' -> 14, 'Hwang In-beom' -> 11."""
    return sum(c.isalpha() for c in (s or ""))


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def _age_days(s):
    """'25y 60d' -> days, for ranking youngest/oldest. Tolerates plain numbers."""
    import re
    s = str(s or "").strip()
    m = re.match(r"(\d+)\s*y\s*(\d+)\s*d", s)
    if m:
        return int(m.group(1)) * 365 + int(m.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def load(data_dir: str, name: str) -> list[dict]:
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh)]


# --- scaffolding -------------------------------------------------------------

TEMPLATE_HEADERS = {
    "matches.csv": ["match_id", "stage", "team_a", "team_b", "team_a_sot", "team_b_sot"],
    "goals.csv": ["match_id", "team", "minute", "type", "scorer", "scorer_age", "disallowed", "dob"],
    "cards.csv": ["match_id", "team", "minute", "color", "dice", "player"],
    "subs.csv": ["match_id", "team", "minute"],
    "own_goals.csv": ["match_id", "team", "minute"],
    "progression.csv": ["team", "stage", "flip", "out"],
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
        w.writerow(["team", "stage", "flip", "out"])
        for team in POT1 + POT2 + POT3:
            w.writerow([team, "group", "", ""])
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
            val = -5  # 3rd-place playoff WINNER: -5 overall (NOT the SF +5)
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
                v = _age_days(raw) if key == "scorer_age" else name_letters(raw)
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
    # Card count is WEIGHTED: a yellow = 1, a red = 2.
    cards_total = defaultdict(int)
    for c in cards:
        cards_total[c["team"]] += 2 if (c.get("color") or "").strip().lower() == "red" else 1

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

    # ---- early-exit bonus (owner-level: scored when your LAST team is out) ----
    # Players are ranked by WHEN their final team is confirmed out: each eliminated
    # team carries its knock-out DATE in progression.csv `out` (YYYY-MM-DD), so a team
    # confirmed out earlier in the group stage ranks ahead of one not settled until a
    # later game - it's the date, not just the stage. A player only places once ALL
    # three of their teams have an `out` date; until then they score 0, so nobody banks
    # anything before teams actually go out. Players whose last team is out at the same
    # time tie and split the summed points for the positions they fill. The bonus is
    # attached to the team that set the owner's exit, so it flows into totals.
    team_stage = {r["team"]: ((r.get("stage") or "group").strip() or "group")
                  for r in progression}
    team_out = {r["team"]: (r.get("out") or "").strip() for r in progression}
    owner_teams: dict[str, list] = defaultdict(list)
    for t in teams:
        if owner.get(t, ""):
            owner_teams[owner[t]].append(t)

    def stage_rank(t):
        return STAGE_RANK.get(team_stage.get(t, "group"), 0)

    # A team is out once it has an `out` date; a player places once all theirs do.
    placed = {o for o, ts in owner_teams.items()
              if ts and all(team_out.get(t, "") for t in ts)}
    # The team that sets a player's exit = their LAST out (latest date, then stage).
    exit_team = {o: max(ts, key=lambda t: (team_out.get(t, ""), stage_rank(t), t))
                 for o, ts in owner_teams.items()}

    def exit_metric(o):       # (knock-out date, stage rank) of the last team out
        et = exit_team[o]
        return (team_out.get(et, ""), stage_rank(et))

    def sort_key(o):          # placed players first, then earliest exit (date, stage)
        return (o not in placed, exit_metric(o))

    early_exit = []  # (owner, exit_team, stage, out_date, points) for placed players
    order = sorted(owner_teams, key=sort_key)
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and sort_key(order[j]) == sort_key(order[i]):
            j += 1
        block = order[i:j]
        total = sum(EARLY_EXIT_POINTS[i + k] for k in range(len(block))
                    if i + k < len(EARLY_EXIT_POINTS))
        share = total / len(block)
        for o in block:
            if o not in placed:        # still in - forfeit these positions for now
                continue
            et = exit_team[o]
            pts[et]["early_exit"] += share
            early_exit.append((o, et, team_stage.get(et, "group"), team_out.get(et, ""), share))
        i = j
    early_exit.sort(key=lambda x: (-x[4], x[3], x[0]))

    # ---- played-match scores (for the fixtures table: mark/colour completed games) ----
    match_scores = {}
    for m in matches:
        a, b = m["team_a"], m["team_b"]
        gm = goals_by_match.get(m["match_id"], [])
        def _scored(team):
            return sum(1 for g in gm if g["team"] == team
                       and not truthy(g.get("disallowed", "")) and g.get("type") != "shootout")
        match_scores[frozenset((a, b))] = {a: _scored(a), b: _scored(b)}

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
        "early_exit": early_exit,
        "match_scores": match_scores,
        "cards_total": dict(cards_total),
        "raw": {"goals": goals, "cards": cards, "subs": subs, "own_goals": own_goals},
        "match_label": {m["match_id"]: f'{m["team_a"]} v {m["team_b"]}' for m in matches},
    }


# --- output ------------------------------------------------------------------

GOAL_LOG_COLS = ["Match", "Team", "Owner", "Scorer", "Born", "Age", "Min", "Type", "Letters", "Disallowed"]
CARD_LOG_COLS = ["Match", "Team", "Owner", "Player", "Min", "Card", "Dice"]


def match_logs(result):
    """Enriched per-event logs: (goal rows, card rows) as lists matching GOAL/CARD_LOG_COLS."""
    owner, ml, raw = result["owner"], result["match_label"], result["raw"]

    def mkey(e):
        return (e.get("match_id", ""), parse_minute(e.get("minute", "")) or 999)

    goals = []
    for g in sorted(raw["goals"], key=mkey):
        t = g["team"]
        goals.append([ml.get(g["match_id"], g["match_id"]), t, owner.get(t, ""),
                      g.get("scorer", ""), g.get("dob", ""), g.get("scorer_age", ""),
                      g.get("minute", ""), g.get("type", ""), name_letters(g.get("scorer", "")),
                      "yes" if truthy(g.get("disallowed", "")) else ""])
    cards = []
    for c in sorted(raw["cards"], key=mkey):
        t = c["team"]
        cards.append([ml.get(c["match_id"], c["match_id"]), t, owner.get(t, ""),
                      c.get("player", ""), c.get("minute", ""), c.get("color", ""),
                      c.get("dice", "")])
    return goals, cards


CATEGORY_ORDER = [
    "in_game", "prime", "progression", "early_exit", "fewest_goals", "fewest_cards",
    "quickest_goal", "quickest_yellow", "fastest_sub", "fastest_own_goal",
    "youngest_scorer", "oldest_scorer", "longest_name", "shortest_name",
]

CAT_LABELS = {
    "in_game": "In-game points", "prime": "Prime-goals penalty",
    "progression": "Progression", "early_exit": "Early-exit bonus",
    "fewest_goals": "Fewest goals",
    "fewest_cards": "Fewest cards", "quickest_goal": "Quickest goal",
    "quickest_yellow": "Quickest yellow card", "fastest_sub": "Fastest substitution",
    "fastest_own_goal": "Fastest own goal", "youngest_scorer": "Youngest scorer",
    "oldest_scorer": "Oldest scorer", "longest_name": "Longest name",
    "shortest_name": "Shortest name",
}

CAT_SHORT = {
    "in_game": "In-game", "prime": "Prime", "progression": "Prog", "early_exit": "Exit",
    "fewest_goals": "Few.G",
    "fewest_cards": "Few.C", "quickest_goal": "Q.goal", "quickest_yellow": "Q.yel",
    "fastest_sub": "F.sub", "fastest_own_goal": "F.OG", "youngest_scorer": "Young",
    "oldest_scorer": "Old", "longest_name": "Long", "shortest_name": "Short",
}

CAT_DESC = {
    "in_game": "In-game points: goals (open +0.5, pen -1.5, shootout -0.5, free-kick 0), VAR -1, "
               "a goal/concede in the 23rd or 67th min +4, 0 shots on target +4, clean sheet against you -1, "
               "red-card dice - then the 90:00+ multiply (x -1) and opponent free-kick doubling (x2) are applied (both together = x -2).",
    "prime": "-3 while the team is on a PRIME number of (non-shootout) goals.",
    "progression": "Points for the round a team is knocked out in: R32 +1, R16 +2, QF +3, SF +5, "
                   "runner-up +8, winner +10; the 3rd-place playoff winner is -5 overall "
                   "(multiplied by -1 if a 90:00+ goal loses their elimination game).",
    "early_exit": "Owner-level: players ranked by when their LAST team is knocked out - "
                  "earliest all-out scores most (1st 5, 2nd 4, 3rd/4th 3, 5th/6th 2, 7th/8th 1, "
                  "rest 0). Players out at the same stage tie and split the summed points for the "
                  "positions they fill. Ranked by the DATE your last team is confirmed out, so an "
                  "earlier group exit beats one settled later. You only place once all three of your "
                  "teams are out; until then it's 0. Shown on the team that set your exit.",
    "fewest_goals": "+7 shared between the team(s) that have scored the FEWEST goals.",
    "fewest_cards": "+7 shared between the team(s) with the FEWEST cards, where a yellow = 1 and a red = 2.",
    "quickest_goal": "Ranked 10/8/5/3/2/1 for the quickest goal of the tournament (earliest minute).",
    "quickest_yellow": "Ranked 10/8/5/3/2/1 for the quickest yellow card.",
    "fastest_sub": "Ranked 10/8/5/3/2/1 for the fastest substitution.",
    "fastest_own_goal": "Ranked 10/8/5/3/2/1 for the fastest own goal.",
    "youngest_scorer": "Ranked 10/8/5/3/2/1 for the youngest goalscorer.",
    "oldest_scorer": "Ranked -10/-8/-5/-3/-2/-1 for the OLDEST goalscorer (a deduction; only your best team qualifies).",
    "longest_name": "Ranked 10/8/5/3/2/1 for the longest goalscorer name.",
    "shortest_name": "Ranked -10/-8/-5/-3/-2/-1 for the SHORTEST goalscorer name (a deduction; only your best team qualifies).",
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

    # Reference sheets: every goal / every card with the details (viewable on GitHub).
    goal_rows, card_rows = match_logs(result)
    with open(os.path.join(out_dir, "goals_log.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(GOAL_LOG_COLS); w.writerows(goal_rows)
    with open(os.path.join(out_dir, "cards_log.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(CARD_LOG_COLS); w.writerows(card_rows)


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
    n_players = len(standings)

    def lb_mark(pos):
        m = ""
        if pos == 1:
            m += "👑"
        if n_players > 1 and pos == n_players:
            m += "💩"
        if DICE_PAYER and pos == DICE_PAYER:
            m += "😈"
        if DICE_RECEIVER and pos == DICE_RECEIVER:
            m += "😇"
        return f" {m}" if m else ""

    lb = "\n".join(
        f"<tr><td>{i}</td><td>{(o or '(undrafted)')}{lb_mark(i)}</td><td>{round(total, 2):g}</td></tr>"
        for i, (o, total) in enumerate(standings, 1)) or '<tr><td colspan="3">-</td></tr>'
    def _ord(n):
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
    dice_note = (f" Dice rolled: whoever finishes {_ord(DICE_PAYER)} (😈) buys whoever finishes "
                 f"{_ord(DICE_RECEIVER)} (😇) the £20 gift."
                 if (DICE_PAYER and DICE_RECEIVER) else " The £20 dice gift hasn't been rolled yet.")

    def ordinal(n):
        suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf}"
    team_rank = {t: 1 + sum(1 for o in teams if tt[o] > tt[t]) for t in teams}

    # All teams, ordered by points (highest first), with current points rank out of 48
    team_rows = "\n".join(
        f"<tr><td>{t}</td><td>{owner.get(t, '') or '-'}</td><td>{round(tt[t], 2):g}</td>"
        f"<td>{ordinal(team_rank[t])}</td></tr>"
        for t in sorted(teams, key=lambda t: (-tt[t], t)))

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
        if cat in ("prime", "early_exit"):   # these are owner-level; own sections below
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

    # Early-exit bonus: players ranked by when their last team is knocked out.
    ee = result.get("early_exit", [])
    ee_rows = "\n".join(
        f"<tr><td>{o}</td><td>{et}</td>"
        f"<td>{(od + ' · ') if od else ''}{STAGE_LABEL.get(stg, stg)}</td>"
        f"<td>{('+' if p else '') + format(round(p, 2), 'g')}</td></tr>"
        for (o, et, stg, od, p) in ee) \
        or '<tr><td colspan="4">settles as teams are knocked out</td></tr>'

    # Fixtures: who plays whom on which day (display only; owners annotated).
    fixtures = result.get("fixtures", [])
    def fx_key(r):
        return ((r.get("date") or "").strip(), (r.get("kickoff") or "").strip())
    def matchcell(t):
        o = owner.get((t or "").strip(), "")
        return f"{t} <span class='o'>({o})</span>" if o else f"{t}"
    mscores = result.get("match_scores", {})
    fx_rows = ""
    for r in sorted((r for r in fixtures
                     if (r.get("home") or "").strip() and (r.get("away") or "").strip()),
                    key=fx_key):
        home, away = r["home"].strip(), r["away"].strip()
        sg = ((r.get("stage") or "").strip() + " " + (r.get("group") or "").strip()).strip() or "-"
        sc = mscores.get(frozenset((home, away)))
        if sc is not None:                       # played -> show score, colour the row
            mid = f"{matchcell(home)} <b>{sc.get(home, 0)}-{sc.get(away, 0)}</b> {matchcell(away)}"
            tr = '<tr class="done">'
        else:
            mid = f"{matchcell(home)} <span class='r'>v</span> {matchcell(away)}"
            tr = "<tr>"
        fx_rows += (f"{tr}<td>{(r.get('date') or '').strip() or '-'}</td>"
                    f"<td>{(r.get('kickoff') or '').strip() or '-'}</td>"
                    f"<td>{sg}</td><td>{mid}</td>"
                    f"<td>{(r.get('venue') or '').strip() or '-'}</td></tr>\n")
    fx_rows = fx_rows or ('<tr><td colspan="5">no fixtures loaded yet - '
                          'add rows to data/fixtures.csv</td></tr>')

    # Full team x category grid. In-game is SPLIT into its components (so you can see
    # goal/FK/red-card/23'-67'/90:00+ points separately) instead of one lumped column.
    # Each column: (short header, full title, tooltip, value-fn). Columns sum to Total.
    _ingame_pts = ("goal_open", "goal_pen", "goal_shootout", "var",
                   "bonus_2367", "bonus_0sot", "clean_sheet", "red_dice")
    _gd_short = {"goal_open": "Goals", "goal_pen": "Pens", "goal_shootout": "S.O. pens",
                 "var": "VAR", "bonus_2367": "23'/67'", "bonus_0sot": "0-SOT",
                 "clean_sheet": "Clean sheet", "red_dice": "Red dice"}

    def _effect(t):   # 90:00+ x-1 and opponent free-kick doubling: final in-game minus raw parts
        raw = sum(detail[t].get(k, 0) for k in _ingame_pts)
        return round(pts[t].get("in_game", 0.0) - raw, 2)

    grid_cols = []   # (short, full, desc, num_fn, key) where num_fn(team) -> number
    for k in _ingame_pts:
        grid_cols.append((_gd_short[k], DETAIL_LABELS[k],
                          "In-game component (raw, before the 90:00+ / free-kick multipliers).",
                          lambda t, k=k: detail[t].get(k, 0), k))
    grid_cols.append(("90'+/FK x", "90:00+ & free-kick multiplier",
                      "Effect of the 90:00+ x-1 flip and opponent free-kick doubling on this game's in-game total.",
                      _effect, "effect"))
    for c in CATEGORY_ORDER:
        if c == "in_game":
            continue
        grid_cols.append((CAT_SHORT.get(c, c), CAT_LABELS[c], CAT_DESC.get(c, ""),
                          lambda t, c=c: pts[t].get(c, 0), c))

    def _cell(x):
        return f"{round(x, 2):g}"

    grid_head = ('<th title="The team">Team</th><th title="Who drafted it">Owner</th>'
                 + "".join(f'<th title="{full} - {desc}">{short}</th>'
                           for (short, full, desc, _fn, _k) in grid_cols)
                 + '<th title="Sum of every column">Total</th>')
    grid_rows = "\n".join(
        f"<tr><td>{t}</td><td>{owner.get(t, '') or '-'}</td>"
        + "".join(f"<td>{_cell(fn(t))}</td>" for (_s, _f, _d, fn, _k) in grid_cols)
        + f"<td><b>{round(tt[t], 2):g}</b></td></tr>"
        for t in sorted(teams, key=lambda t: tt[t], reverse=True))

    # Same breakdown, aggregated BY PLAYER (sum each owner's three teams per column).
    owner_teams_grid = defaultdict(list)
    for t in teams:
        if owner.get(t, ""):
            owner_teams_grid[owner[t]].append(t)
    pgrid_head = ('<th title="The player">Player</th>'
                  + "".join(f'<th title="{full} - {desc}">{short}</th>'
                            for (short, full, desc, _fn, _k) in grid_cols)
                  + '<th title="Player total (all three teams)">Total</th>')
    pgrid_rows = "\n".join(
        f"<tr><td>{o}</td>"
        + "".join(f"<td>{_cell(sum(fn(t) for t in owner_teams_grid[o]))}</td>"
                  for (_s, _f, _d, fn, _k) in grid_cols)
        + f"<td><b>{round(result['owner_totals'].get(o, 0), 2):g}</b></td></tr>"
        for o in sorted(owner_teams_grid, key=lambda o: -result['owner_totals'].get(o, 0)))

    # ---- per-category DETAIL extractors (which team/scorer/minute earned the points) ----
    _raw = result.get("raw", {})
    rgoals, rcards, rsubs, rog = (_raw.get("goals", []), _raw.get("cards", []),
                                  _raw.get("subs", []), _raw.get("own_goals", []))
    gfor, ctot = result["goals_for"], result.get("cards_total", {})

    def _tg(t):   # a team's countable goals (open/pen/freekick, not disallowed/shootout)
        return [g for g in rgoals if g["team"] == t
                and not truthy(g.get("disallowed", "")) and g.get("type") != "shootout"]

    def _minrow(rows, key):
        rows = [(parse_minute(r.get(key, "")), r) for r in rows]
        rows = [(m, r) for m, r in rows if m is not None]
        return min(rows, key=lambda mr: mr[0])[1] if rows else None

    def d_qgoal(t):
        r = _minrow(_tg(t), "minute"); return f"{r['minute']}' - {r['scorer']} ({abbr(t)})" if r else ""
    def d_qyel(t):
        r = _minrow([c for c in rcards if c["team"] == t and c.get("color") == "yellow"], "minute")
        return f"{r['minute']}' - {r.get('player') or '?'} ({abbr(t)})" if r else ""
    def d_fsub(t):
        r = _minrow([s for s in rsubs if s["team"] == t], "minute"); return f"{r['minute']}' ({abbr(t)})" if r else ""
    def d_fog(t):
        r = _minrow([o for o in rog if o["team"] == t], "minute"); return f"{r['minute']}' ({abbr(t)})" if r else ""
    def _age_pick(t, oldest):
        gs = [g for g in _tg(t) if (g.get("scorer_age") or "").strip()]
        if not gs:
            return ""
        g = (max if oldest else min)(gs, key=lambda g: _age_days(g["scorer_age"]) or (-1 if oldest else 1e9))
        return f"{g['scorer_age']} - {g['scorer']} ({abbr(t)})"
    def d_young(t): return _age_pick(t, False)
    def d_old(t):   return _age_pick(t, True)
    def _name_pick(t, longest):
        gs = _tg(t)
        if not gs:
            return ""
        g = (max if longest else min)(gs, key=lambda g: name_letters(g["scorer"]))
        return f"{name_letters(g['scorer'])} letters - {g['scorer']} ({abbr(t)})"
    def d_long(t):  return _name_pick(t, True)
    def d_short(t): return _name_pick(t, False)

    CAT_DETAIL = {"quickest_goal": d_qgoal, "quickest_yellow": d_qyel, "fastest_sub": d_fsub,
                  "fastest_own_goal": d_fog, "youngest_scorer": d_young, "oldest_scorer": d_old,
                  "longest_name": d_long, "shortest_name": d_short,
                  "prime": lambda t: f"{gfor.get(t, 0)} goals ({abbr(t)})",
                  "fewest_goals": lambda t: f"{gfor.get(t, 0)} goals ({abbr(t)})",
                  "fewest_cards": lambda t: f"{ctot.get(t, 0):g} cards ({abbr(t)})"}

    # By-category tab: one mini by-player leaderboard per category (with the why).
    def _cat_card(title, desc, key, num_fn):
        dfn = CAT_DETAIL.get(key)
        rows = []
        for o in owner_teams_grid:
            v = sum(num_fn(t) for t in owner_teams_grid[o])
            if round(v, 2) == 0:
                continue
            det = ""
            if dfn:
                tms = [t for t in owner_teams_grid[o] if round(pts[t].get(key, 0), 2) != 0]
                det = "; ".join(dfn(t) for t in tms if dfn(t))
            rows.append((o, v, det))
        rows.sort(key=lambda r: (-abs(r[1]), r[0]))
        if any(r[2] for r in rows):
            head = '<tr><th>Player</th><th>Detail</th><th>Pts</th></tr>'
            body = "".join(f"<tr><td>{o}</td><td class='det'>{det}</td><td>{_cell(v)}</td></tr>"
                           for o, v, det in rows) or '<tr><td colspan="3">nobody yet</td></tr>'
        else:
            head = '<tr><th>Player</th><th>Pts</th></tr>'
            body = "".join(f"<tr><td>{o}</td><td>{_cell(v)}</td></tr>"
                           for o, v, _ in rows) or '<tr><td colspan="2">nobody yet</td></tr>'
        return f'<div class="catcard"><h3 title="{desc}">{title}</h3><table class="tt num">{head}{body}</table></div>'

    cat_cards = _cat_card("Overall total", "Every player's total across all scoring", "_total",
                          lambda t: tt[t])
    for (_short, full, desc, fn, key) in grid_cols:
        cat_cards += _cat_card(full, desc, key, fn)

    glog, clog = match_logs(result)
    goal_log_head = "".join(f"<th>{c}</th>" for c in GOAL_LOG_COLS)
    goal_log_rows = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in glog) \
        or f'<tr><td colspan="{len(GOAL_LOG_COLS)}">no goals yet</td></tr>'
    card_log_head = "".join(f"<th>{c}</th>" for c in CARD_LOG_COLS)
    card_log_rows = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in clog) \
        or f'<tr><td colspan="{len(CARD_LOG_COLS)}">no cards yet</td></tr>'

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
 .scroll{{overflow-x:auto}} .grid{{font-size:.9rem}}
 .grid td,.grid th{{padding:.3rem .4rem}} .grid td{{white-space:nowrap;text-align:center}}
 .grid th{{white-space:normal;vertical-align:bottom;line-height:1.12;max-width:5.5em}}
 .grid td:first-child,.grid th:first-child{{text-align:left}}
 .num td:not(:first-child),.num th:not(:first-child){{text-align:right}}
 .r{{color:#888;font-size:.85rem}} .pl td:nth-child(2){{text-align:right}}
 .wide{{width:98vw;max-width:1700px;position:relative;left:50%;transform:translateX(-50%)}}
 table.sortable th{{cursor:pointer;user-select:none;text-decoration:underline dotted #bbb}}
 table.sortable th:hover{{background:#eef2ff;color:#2563eb}}
 table.sortable th::after{{content:" \\2195";color:#bbb;font-size:.8em}}
 nav.tabs{{position:sticky;top:0;background:#fff;border-bottom:1px solid #e3e6ea;margin:1rem 0 .5rem;
   padding:.45rem 0;display:flex;flex-wrap:wrap;gap:.3rem;z-index:5}}
 nav.tabs a{{padding:.35rem .75rem;border-radius:6px;text-decoration:none;color:#2563eb;font-weight:600;font-size:.95rem}}
 nav.tabs a:hover{{background:#eef2ff}} nav.tabs a.active{{background:#2563eb;color:#fff}}
 section.tab[hidden]{{display:none}} .legend{{color:#555;font-size:.9rem;margin:.2rem 0 1.5rem}}
 .catgrid{{display:flex;flex-wrap:wrap;gap:.8rem 1.4rem;align-items:flex-start}}
 .catcard{{flex:1 1 230px;min-width:210px;max-width:340px}} .catcard h3{{margin:.4rem 0 .1rem;font-size:1rem}}
 .catcard table{{margin:.2rem 0 .6rem;font-size:.92rem}}
 .catcard td.det{{text-align:left;white-space:normal;font-size:.82rem;color:#444}}
 table.fx tr.done td{{background:#e6f6ec}} table.fx tr.done td:first-child{{box-shadow:inset 3px 0 #16a34a}}
</style></head><body>
<h1>🏆 WC 2026 Friends Pool</h1>
<p class="sub">Draft pool - 16 players, 3 teams each (one per pot). Auto-updated {updated}.
<a href="rules.pdf">📜 full rules (PDF)</a> · <a href="mini-rules.pdf">📋 scoring cheat-sheet (PDF)</a></p>

<nav class="tabs">
<a href="#tab-leaderboard">🏆 Leaderboard</a>
<a href="#tab-players">👥 Player teams</a>
<a href="#tab-fixtures">📅 Fixtures</a>
<a href="#tab-stats">📊 Stats</a>
<a href="#tab-breakdown">🧮 Full breakdown</a>
<a href="#tab-categories">🗂️ By category</a>
<a href="#tab-log">📋 Match log</a>
</nav>

<section class="tab" id="tab-leaderboard">
<h2>Leaderboard</h2>
<table class="lb sortable"><tr><th>#</th><th>Player</th><th>Points</th></tr>
{lb}
</table>
<p class="legend">👑 1st - wins a sports shirt of their choice (everyone chips in, up to £150) ·
💩 last - buys seven other players dessert · 😈 pays the £20 dice gift · 😇 receives it.{dice_note}</p>
</section>

<section class="tab" id="tab-players">
<h2>Player teams</h2>
<p class="sub">Each player (sorted by average seed, strongest squad first) and their three teams (Pot 1 / 2 / 3). The #number is the team's
<b>seed out of 48</b> by Polymarket winner odds, within the draft pot tiers (#1 = strongest, #48 = longest shot).</p>
<table class="pl sortable"><tr><th>Player</th><th>Total</th><th>Avg seed</th><th>Pot 1</th><th>Pot 2</th><th>Pot 3</th></tr>
{player_rows}
</table>
</section>

<section class="tab" id="tab-fixtures">
<h2>📅 Fixtures</h2>
<p class="sub">All 104 matches - who plays whom, and when (your players' teams in green; knockout slots show the bracket code until teams are known). Kickoffs are <b>UK time (BST)</b> - late US games roll into the early hours of the next UK day, and the date shown is the UK date. <b>Played games are shaded green with the score.</b> Click a header to sort - by date, kickoff, stage or venue.</p>
<div class="scroll"><table class="fx sortable"><tr><th>Date</th><th>Kickoff</th><th>Stage</th><th>Match</th><th>Venue</th></tr>
{fx_rows}
</table></div>
</section>

<section class="tab" id="tab-stats">
<h2>All teams (by points)</h2>
<table class="tt sortable"><tr><th>Team</th><th>Owner</th><th>Points</th><th>Rank</th></tr>
{team_rows}
</table>

<h2>Category extremes</h2>
<p class="sub">For every scoring category: the team gaining the most, and the team losing the most (owner in brackets).</p>
<table class="num"><tr><th>Category</th><th>🟢 Most points</th><th>🔴 Most lost</th></tr>
{cat_rows}
</table>

<h2>🚪 Early-exit bonus</h2>
<p class="sub">Score for your teams crashing out early: you're ranked by when your <b>last</b> team is knocked out.
1st all-out = 5, 2nd = 4, 3rd/4th = 3, 5th/6th = 2, 7th/8th = 1. Players out at the same stage tie and
split the summed points for the positions they fill. Ranked by the <b>date</b> your last team is confirmed
out, so an earlier group exit beats one settled later. You only place once <b>all three</b> of your teams
are eliminated - nobody scores here until teams actually start going out.</p>
<table class="tt num sortable"><tr><th>Player</th><th>Last team out</th><th>Knocked out (date · stage)</th><th>Bonus</th></tr>
{ee_rows}
</table>

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

</section>

<section class="tab" id="tab-breakdown">
<h2>Full breakdown - by team</h2>
<p class="sub">In-game points are split into their parts - <b>Goals · Pens · S.O. pens · VAR · 23'/67' · 0-SOT · Clean sheet · Red dice</b>,
plus a <b>90'+/FK x</b> column for the 90:00+ flip and free-kick doubling - then the ranked prizes and bonuses. Every column adds up to <b>Total</b>.</p>
<div class="scroll wide"><table class="num grid sortable"><tr>{grid_head}</tr>
{grid_rows}
</table></div>

<h2>Full breakdown - by player</h2>
<p class="sub">The same columns, but each player's <b>three teams added together</b>. Sorted by total.</p>
<div class="scroll wide"><table class="num grid sortable"><tr>{pgrid_head}</tr>
{pgrid_rows}
</table></div>
<p class="sub"><b>Hover</b> any column header for its full scoring rule, and <b>click</b> a header to sort by it.</p>
</section>

<section class="tab" id="tab-categories">
<h2>Every category - by player</h2>
<p class="sub">Each scoring category as its own by-player leaderboard - who's qualifying, and for how much.
Ranked prizes (quickest goal/yellow, youngest/oldest, etc.) show the players currently in the top 6.</p>
<div class="catgrid">
{cat_cards}
</div>
</section>

<section class="tab" id="tab-log">
<h2>📋 Match log - every goal</h2>
<p class="sub">Every goal so far with scorer, birth date, age, minute, type and name length. <a href="goals_log.csv">goals_log.csv</a></p>
<div class="scroll"><table class="tt sortable"><tr>{goal_log_head}</tr>
{goal_log_rows}
</table></div>
<h2>📋 Match log - every card</h2>
<p class="sub">Every yellow/red so far with player, minute and (for reds) the dice roll. <a href="cards_log.csv">cards_log.csv</a></p>
<div class="scroll"><table class="tt sortable"><tr>{card_log_head}</tr>
{card_log_rows}
</table></div>
</section>

<p class="sub"><a href="standings.csv">standings.csv</a> · <a href="team_breakdown.csv">team_breakdown.csv</a> · <a href="rules.pdf">rules.pdf</a> · <a href="mini-rules.pdf">mini-rules.pdf</a></p>
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
    tab_js = """<script>
(function(){
  var tabs = Array.prototype.slice.call(document.querySelectorAll('nav.tabs a'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('section.tab'));
  if(!tabs.length || !panels.length) return;
  function show(id){
    if(!document.getElementById(id)) id = panels[0].id;
    panels.forEach(function(p){ p.hidden = (p.id !== id); });
    tabs.forEach(function(t){ t.classList.toggle('active', t.getAttribute('href') === '#'+id); });
    if(history.replaceState) history.replaceState(null, '', '#'+id);
  }
  tabs.forEach(function(t){
    t.addEventListener('click', function(e){
      e.preventDefault(); show(t.getAttribute('href').slice(1)); window.scrollTo(0,0);
    });
  });
  show(location.hash ? location.hash.slice(1) : panels[0].id);
})();
</script>"""
    html = html.replace("</body></html>", sort_js + tab_js + "\n</body></html>")
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
    for doc in ("rules.pdf", "mini-rules.pdf"):
        if os.path.exists(doc):
            shutil.copy(doc, os.path.join(args.out, doc))
    print_standings(result)
    print(f"  Wrote {args.out}/index.html, standings.csv, team_breakdown.csv")


if __name__ == "__main__":
    main()
