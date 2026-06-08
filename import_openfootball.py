#!/usr/bin/env python3
"""
Pre-fill the friends-pool data CSVs from openfootball (keyless, no signup).

It pulls played WC2026 matches and ADDITIVELY merges them into data/:
  - matches.csv     adds new matches (match_id = file order); keeps your SOT edits
  - goals.csv       adds new goals (type=penalty if flagged, else open); keeps your
                    manual scorer_age / type / disallowed on existing rows
  - own_goals.csv   adds own goals (the erring side)
It NEVER overwrites an existing row, and NEVER touches cards.csv / subs.csv
(openfootball has no card/sub data) - those stay fully manual.

Still-manual after import: scorer_age, free-kick vs open, shootout penalties,
VAR-disallowed flags, the red-card dice roll, and shots-on-target.

    python import_openfootball.py            # merge into ./data
    python import_openfootball.py --data X   # merge into ./X
"""
import argparse
import csv
import json
import os
import urllib.request

URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _stage(m):
    r = (m.get("round") or "").lower()
    if m.get("group"):
        return "group"
    for key, val in [("32", "R32"), ("16", "R16"), ("quarter", "QF"),
                     ("semi", "SF"), ("third", "third"), ("final", "RU")]:
        if key in r:
            return val
    return r or "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    args = ap.parse_args()
    os.makedirs(args.data, exist_ok=True)

    matches = json.load(urllib.request.urlopen(URL, timeout=30))["matches"]

    m_rows = _load(os.path.join(args.data, "matches.csv"))
    g_rows = _load(os.path.join(args.data, "goals.csv"))
    og_rows = _load(os.path.join(args.data, "own_goals.csv"))
    m_have = {r["match_id"] for r in m_rows}
    g_have = {(r["match_id"], r["team"], r["minute"], r.get("scorer", "")) for r in g_rows}
    og_have = {(r["match_id"], r["team"], r["minute"]) for r in og_rows}

    added_m = added_g = added_og = 0
    for i, m in enumerate(matches, 1):
        sc = m.get("score") or {}
        if "ft" not in sc:
            continue                       # not played yet
        mid = str(i)
        if mid not in m_have:
            m_rows.append({"match_id": mid, "stage": _stage(m), "team_a": m["team1"],
                           "team_b": m["team2"], "team_a_sot": "", "team_b_sot": ""})
            m_have.add(mid)
            added_m += 1
        for key, scorer_team, other in (("goals1", m["team1"], m["team2"]),
                                        ("goals2", m["team2"], m["team1"])):
            for g in m.get(key) or []:
                if not isinstance(g, dict):
                    continue
                mn = str(g.get("minute", ""))
                nm = g.get("name", "")
                if g.get("owngoal"):
                    k = (mid, other, mn)   # erring side = the other team
                    if k not in og_have:
                        og_rows.append({"match_id": mid, "team": other, "minute": mn})
                        og_have.add(k); added_og += 1
                    continue
                k = (mid, scorer_team, mn, nm)
                if k not in g_have:
                    g_rows.append({"match_id": mid, "team": scorer_team, "minute": mn,
                                   "type": "penalty" if g.get("penalty") else "open",
                                   "scorer": nm, "scorer_age": "", "disallowed": ""})
                    g_have.add(k); added_g += 1

    _write(os.path.join(args.data, "matches.csv"),
           ["match_id", "stage", "team_a", "team_b", "team_a_sot", "team_b_sot"], m_rows)
    _write(os.path.join(args.data, "goals.csv"),
           ["match_id", "team", "minute", "type", "scorer", "scorer_age", "disallowed"], g_rows)
    _write(os.path.join(args.data, "own_goals.csv"),
           ["match_id", "team", "minute"], og_rows)

    print(f"Imported: +{added_m} matches, +{added_g} goals, +{added_og} own goals.")
    print("Now fill the manual bits: scorer_age, free-kick/shootout types, VAR flags,")
    print("cards.csv (incl. dice), subs.csv, and shots-on-target in matches.csv.")


if __name__ == "__main__":
    main()
