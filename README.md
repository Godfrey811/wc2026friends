# wc2026friends

World Cup 2026 prediction pool (friends edition). 16 players each draft three
teams — one from each odds-tiered pot — and score points across the tournament
from a deliberately chaotic set of rules.

## Rules & pots

- **[RULES.md](RULES.md)** — the full scoring rules
- **[POTS.md](POTS.md)** — the three draft pots (16 teams each)
- **rules.pdf** — shareable one-doc version of both

All three are generated from a single source:

```bash
python rules.py          # regenerates RULES.md, POTS.md, rules.pdf (PDF needs fpdf2)
```

## Tracker

`tracker.py` reads the draft + match-event CSVs and computes the standings.

```bash
python tracker.py --init             # scaffold empty templates into ./data
#   ...fill in data/draft.csv owners after the draft, then log match data...
python tracker.py                    # score ./data -> writes ./out, prints standings
python tracker.py --data data_sample # run the worked example
```

Outputs (in `out/`, git-ignored):
- `standings.csv` — players ranked by total points
- `team_breakdown.csv` — every team's points split by category

### Data files (in `data/`)

| File | Columns |
|---|---|
| `draft.csv` | `pot,team,owner` (pots + teams prefilled; add owners after the draft) |
| `matches.csv` | `match_id,stage,team_a,team_b,team_a_sot,team_b_sot` |
| `goals.csv` | `match_id,team,minute,type,scorer,scorer_age,disallowed` (type = open/freekick/penalty/shootout) |
| `cards.csv` | `match_id,team,minute,color,dice` (color = yellow/red; dice = the red-card d6 roll) |
| `subs.csv` | `match_id,team,minute` |
| `own_goals.csv` | `match_id,team,minute` (team = the side that erred) |
| `progression.csv` | `team,stage,flip` (stage = group/R32/R16/QF/SF/RU/winner/third; flip = 1 if a 90'+ goal flips their elimination round) |

`data_sample/` is a small worked example (4 teams, 2 matches) used to validate the engine.

### Known gaps (see tracker.py header)

Own-goal effects on goals-for/clean-sheet, the extra-time / own-both-teams 0-0
clean-sheet nuances, and ranked-category tie-splitting / "most recent" tiebreaks
are not yet modelled. Flag if these matter for settlement.
