"""Single source of truth for the WC2026 Friends pool rules.

Run this to regenerate both RULES.md (GitHub-viewable) and rules.pdf (shareable):

    python rules.py

PDF generation needs fpdf2 (`pip install fpdf2`); the Markdown output has no deps.
"""

from __future__ import annotations

# --- Content: one structured source, rendered to Markdown and PDF below. -----
# Block forms:
#   ("h1", text) / ("h2", text)        section headings
#   ("p", text)                        paragraph
#   ("bullets", [str, ...])            bullet list
#   ("table", [headers], [[row], ...]) table
#   ("note", text)                     small caveat / footnote

# --- Draft pots: membership by "to reach QF" odds; order within each pot (the #1-48
# --- seed) by Polymarket winner odds, June 2026. Pot 1 strongest. -----------
# Field checked against the confirmed 48-team WC2026 lineup (June 2026):
# UEFA 16, CONMEBOL 6, AFC 9, CAF 10, CONCACAF 6, OFC 1.

POT1 = [
    "Spain", "France", "England", "Portugal", "Argentina", "Brazil",
    "Germany", "Netherlands", "Norway", "Belgium", "Colombia", "Morocco",
    "Mexico", "USA", "Switzerland", "Turkey",
]
POT2 = [
    "Japan", "Uruguay", "Croatia", "Ecuador", "Senegal", "Austria",
    "Ivory Coast", "Canada", "Sweden", "Paraguay", "Scotland", "South Korea",
    "Egypt", "Algeria", "Czechia", "Bosnia & Herzegovina",
]
POT3 = [
    "Australia", "Ghana", "South Africa", "Panama", "DR Congo", "Saudi Arabia",
    "Tunisia", "Uzbekistan", "New Zealand", "Cape Verde", "Jordan", "Iraq",
    "Haiti", "Qatar", "Curaçao", "Iran",
]

_POT_HEADERS = ["Pot 1 — strongest", "Pot 2 — middle", "Pot 3 — long shots"]
_POT_ROWS = [[POT1[i], POT2[i], POT3[i]] for i in range(16)]


CONTENT = [
    ("h1", "WC2026 Friends Pool — Rules"),
    ("p",
     "Everyone drafts teams from three odds-tiered pots. Your teams earn (and "
     "lose) points across the whole tournament from the categories below. Most "
     "points at the end wins. The pool leans into chaos — plenty of ways to "
     "score are deliberately perverse, so read carefully."),

    ("h2", "Goals & shots"),
    ("table",
     ["Event", "Points"],
     [
         ["Open-play goal", "+0.5 each"],
         ["Free-kick goal", "doubles the OPPONENT team's points for that game (scores nothing for you)"],
         ["Penalty scored — not a shootout", "-1.5 each"],
         ["Penalty scored — in a shootout", "-0.5 each"],
         ["Goal ruled out by VAR", "-1 each"],
         ["0 shots on target in a game", "+4"],
         ["Goal scored OR conceded in the 23rd or 67th minute", "+4 (max +4 per game, even if you own both teams)"],
         ["Each game your team fails to score (clean sheet against you)", "-1 (own both teams & it's 0-0 = 0; extra time excluded)"],
         ["Prime number of total goals in the tournament (excludes shootout goals)", "-3"],
     ]),
    ("note",
     "A free-kick goal still counts toward your team's total-goals tally (so it "
     "can still trigger the prime -3 and the fewest-goals award) — it just "
     "earns you nothing directly."),

    ("h2", "The 90'+ rule"),
    ("bullets", [
        "A goal from 90:00 onwards - the 90th minute and ALL of its injury/stoppage time (recorded as 90 or 90+X) - multiplies that team's IN-GAME points for that game by -1 - i.e. the goals, the 23'/67' bonus, the 0-shots-on-target bonus, the clean-sheet, and the red-card dice from that game.",
        "90:00 ONWARDS, INJURY TIME ONLY - this is NOT extra time. A goal in extra time (91-120, e.g. 105 or 120) does NOT count for this rule.",
        "It hits ONLY that game's in-game total. It does NOT touch the tournament-long ranked prizes (quickest goal, quickest yellow, fastest sub, fastest own goal, youngest/oldest scorer, longest/shortest name, fewest goals, fewest cards) or the prime-goals penalty - those are never flipped.",
        "Two 90'+ goals in the same game cancel out (×-1 ×-1 = back to positive).",
        "In-game points flip in ANY game (win or lose).",
        "Progression points only flip in your ELIMINATION game. Winning teams bank no progression at that moment, so a champion's Winner points are always safe — but a runner-up who scores a 90'+ goal in the final they lose flips their +8 to -8.",
    ]),

    ("h2", "Red card — roll the dice"),
    ("bullets", [
        "When one of your teams gets a red card, roll a single d6.",
        "Odd roll  -> you GAIN (roll / 2) points:  1 = +0.5,  3 = +1.5,  5 = +2.5",
        "Even roll -> you LOSE (roll / 2) points:   2 = -1,    4 = -2,    6 = -3",
        "No rounding — half-points stand.",
    ]),

    ("h2", "Ranked categories"),
    ("p",
     "Each category ranks the top 6 teams across the whole tournament. Positive "
     "categories pay 10 / 8 / 5 / 3 / 2 / 1; penalty categories pay the negative "
     "of that."),
    ("table",
     ["Direction", "Points (top 6)", "Categories"],
     [
         ["Reward", "10 / 8 / 5 / 3 / 2 / 1",
          "Quickest Goal · Youngest Goalscorer · Fastest Substitute · Fastest Own Goal · Quickest Yellow Card · Longest-Named Goalscorer"],
         ["Penalty", "-10 / -8 / -5 / -3 / -2 / -1",
          "Oldest Goalscorer · Shortest-Named Goalscorer"],
     ]),
    ("bullets", [
        "An owner can only win a given category once — if you own both the best and second-best team in it, the second prize rolls down to the next DISTINCT owner.",
        "Ties split the points between the tied owners (owning several tied teams = a bigger share).",
        "Tiebreak: the most recent occurrence ranks higher.",
        "Data source priority: official FIFA, else BBC, else ITV.",
    ]),

    ("h2", "Flat awards"),
    ("bullets", [
        "Fewest Goals (whole tournament): +7 to the single team with fewest (tie-split between owners).",
        "Fewest Cards (whole tournament): +7 to the single team with fewest (tie-split between owners).",
    ]),

    ("h2", "Tournament progression"),
    ("p",
     "Points for the furthest stage a team reaches, realised in the game they're "
     "eliminated."),
    ("table",
     ["R32", "R16", "QF", "SF", "Runner-up", "Winner"],
     [["+1", "+2", "+3", "+5", "+8", "+10"]]),
    ("bullets", [
        "3rd-place playoff WINNER: -5 (cancels their SF +5, so 3rd place nets 0).",
        "4th place (loses the 3rd-place playoff): keeps the SF +5.",
    ]),

    ("h2", "Early-exit bonus"),
    ("p",
     "A reward for drafting teams that all crash out early. Players are ranked by "
     "when their LAST surviving team is knocked out - the sooner all three of your "
     "teams are gone, the more you score."),
    ("table",
     ["1st all-out", "2nd", "3rd or 4th", "5th or 6th", "7th or 8th", "9th-16th"],
     [["5", "4", "3", "2", "1", "0"]]),
    ("bullets", [
        "Your exit is set by your FURTHEST team - you're only 'out' once all three are eliminated.",
        "It's about WHEN you're confirmed out, not just the stage. A team mathematically eliminated earlier in its group (say after game 5) ranks ahead of one that isn't confirmed out until a later game - you don't wait for the group to finish.",
        "Players confirmed out at the SAME time tie, and split the summed points for the positions they fill. Example: if three players' last teams are all confirmed out together, they take positions 1-3 and split 5 + 4 + 3 = 12, i.e. 4 points each.",
        "A team that wins the tournament never goes out, so its owner finishes last here (0).",
    ]),

    ("h2", "The draft — pots"),
    ("p",
     "16 players. Each player drafts THREE teams — one from each pot — so every "
     "squad gets a strong team, a mid team and a long shot (16 players x 3 = the "
     "full 48). The pots are seeded by each team's \"to reach the quarter-finals\" "
     "odds: Pot 1 is the 16 strongest, Pot 3 the 16 longest shots."),
    ("table", _POT_HEADERS, _POT_ROWS),

    ("h2", "Prizes & forfeits"),
    ("bullets", [
        "1st place: a shirt of any sports team of their choice, paid for by everyone else (capped at £150).",
        "Last place: must buy SEVEN other players (their choice) dessert - in person, and within 3 months of the final.",
        "The dice gift: once the final standings are locked, roll a 16-sided die twice. The player who finished in the FIRST position rolled buys the player who finished in the SECOND a £20 gift - e.g. a roll of 4 then 7 means whoever finished 4th has to buy whoever finished 7th. Re-roll if the same position comes up twice.",
    ]),

    ("note",
     "Rules locked from the conversation of June 2026. If anything here doesn't "
     "match what you expected, flag it before the draft."),
]


# --- Markdown renderer -------------------------------------------------------

def render_markdown(content) -> str:
    out: list[str] = []
    for block in content:
        kind = block[0]
        if kind == "h1":
            out.append(f"# {block[1]}\n")
        elif kind == "h2":
            out.append(f"## {block[1]}\n")
        elif kind == "p":
            out.append(f"{block[1]}\n")
        elif kind == "bullets":
            out.append("\n".join(f"- {item}" for item in block[1]) + "\n")
        elif kind == "note":
            out.append(f"> _{block[1]}_\n")
        elif kind == "table":
            headers, rows = block[1], block[2]
            out.append("| " + " | ".join(headers) + " |")
            out.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in rows:
                out.append("| " + " | ".join(row) + " |")
            out.append("")
    return "\n".join(out).strip() + "\n"


# --- PDF renderer ------------------------------------------------------------

_PDF_SUBS = {
    "—": " - ",  # em dash
    "–": "-",    # en dash
    "•": "-",    # bullet
    "’": "'", "‘": "'",       # curly single quotes
    "“": '"', "”": '"',       # curly double quotes
    "…": "...",                     # ellipsis
}


def _latin1(text: str) -> str:
    """The built-in PDF fonts are latin-1 only; map the few fancy glyphs down."""
    for bad, good in _PDF_SUBS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(content, path: str) -> None:
    from fpdf import FPDF
    from fpdf.fonts import FontFace
    from fpdf.enums import XPos, YPos

    NAVY = (15, 30, 75)
    GREY = (90, 90, 90)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 16, 18)
    epw = pdf.epw  # effective page width

    for block in content:
        kind = block[0]
        if kind == "h1":
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(*NAVY)
            pdf.multi_cell(epw, 9, _latin1(block[1]))
            pdf.ln(2)
        elif kind == "h2":
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(*NAVY)
            pdf.multi_cell(epw, 7, _latin1(block[1]))
            pdf.ln(1)
        elif kind == "p":
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(epw, 5.5, _latin1(block[1]))
            pdf.ln(1.5)
        elif kind == "bullets":
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(0, 0, 0)
            for item in block[1]:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(6, 5.5, chr(149), new_x=XPos.RIGHT, new_y=YPos.TOP)  # bullet
                pdf.multi_cell(epw - 6, 5.5, _latin1(item),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)               # text, then next line
            pdf.ln(1.5)
        elif kind == "note":
            pdf.ln(1)
            pdf.set_font("Helvetica", "I", 9.5)
            pdf.set_text_color(*GREY)
            pdf.multi_cell(epw, 5, _latin1(block[1]))
            pdf.ln(1.5)
        elif kind == "table":
            headers, rows = block[1], block[2]
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(0, 0, 0)
            with pdf.table(
                headings_style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY),
                line_height=6,
                text_align="LEFT",
            ) as table:
                head = table.row()
                for h in headers:
                    head.cell(_latin1(h))
                for r in rows:
                    row = table.row()
                    for cell in r:
                        row.cell(_latin1(cell))
            pdf.ln(2)

    pdf.output(path)


# --- Mini one-page, colour-coded scoring table -------------------------------

# (group title, header colour, row tint, [(rule, points/effect), ...])
MINI_RULES = [
    ("In-game points (per match)", (37, 99, 235), (219, 234, 254), [
        ("Open-play goal", "+0.5 each"),
        ("Penalty scored - not a shootout", "-1.5 each"),
        ("Penalty scored - in a shootout", "-0.5 each"),
        ("Goal ruled out by VAR", "-1 each"),
        ("0 shots on target in a game", "+4"),
        ("Goal scored OR conceded in the 23rd or 67th minute", "+4 (max +4 per game)"),
        ("Fail to score in a game (clean sheet against you)", "-1 (own both & 0-0 = 0; extra time excluded)"),
        ("Prime number of total goals in the tournament (excl. shootout goals)", "-3"),
    ]),
    ("Modifiers - these change other points, not flat", (124, 58, 237), (237, 233, 254), [
        ("Free-kick goal", "doubles the OPPONENT team's points that game (nothing for you)"),
        ("Goal from 90:00 onwards (injury time, not extra time)", "flips that team's in-game points x -1 (two cancel out)"),
        ("Red card - roll a d6", "odd = +(roll/2): 1=+0.5, 3=+1.5, 5=+2.5;  even = -(roll/2): 2=-1, 4=-2, 6=-3"),
    ]),
    ("Ranked rewards - top 6 teams score 10 / 8 / 5 / 3 / 2 / 1", (22, 163, 74), (220, 252, 231), [
        ("Quickest goal", "+"), ("Quickest yellow card", "+"), ("Fastest substitution", "+"),
        ("Fastest own goal", "+"), ("Youngest goalscorer", "+"), ("Longest-named goalscorer", "+"),
    ]),
    ("Ranked penalties - top 6 teams score -10 / -8 / -5 / -3 / -2 / -1", (220, 38, 38), (254, 226, 226), [
        ("Oldest goalscorer", "-"), ("Shortest-named goalscorer", "-"),
    ]),
    ("Flat awards", (13, 148, 136), (204, 251, 241), [
        ("Fewest goals (whole tournament)", "+7 (tie-split between owners)"),
        ("Fewest cards (whole tournament)", "+7 (tie-split between owners)"),
    ]),
    ("Tournament progression - banked when the team is eliminated", (217, 119, 6), (254, 243, 199), [
        ("Reach Round of 32", "+1"), ("Reach Round of 16", "+2"), ("Reach Quarter-final", "+3"),
        ("Reach Semi-final", "+5"), ("Runner-up", "+8"), ("Winner", "+10"),
        ("3rd-place playoff winner", "-5 (cancels the SF +5, so 3rd nets 0)"),
    ]),
    ("Early-exit bonus - ranked by when your LAST team is knocked out", (234, 88, 12), (255, 237, 213), [
        ("1st player all-out", "+5"), ("2nd", "+4"), ("3rd or 4th", "+3"),
        ("5th or 6th", "+2"), ("7th or 8th", "+1"), ("9th - 16th", "0"),
    ]),
]


def render_mini_pdf(path: str) -> None:
    """One landscape-free A4 page: every points rule in a single colour-coded table."""
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    NAVY = (15, 30, 75)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_margins(14, 12, 14)
    epw = pdf.epw

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(epw, 8, _latin1("WC2026 Friends Pool - Scoring at a glance"))
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(epw, 5, _latin1("Every points rule on one page, colour-coded by type. "
                                   "Full wording and edge cases are in rules.pdf."))
    pdf.ln(2.5)

    head = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(0, 0, 0)
    with pdf.table(first_row_as_headings=False, col_widths=(62, 38),
                   line_height=5.4, text_align=("LEFT", "LEFT"), width=epw) as table:
        r = table.row()
        r.cell(_latin1("Rule"), style=head)
        r.cell(_latin1("Points / effect"), style=head)
        for name, hrgb, tint, rows in MINI_RULES:
            gr = table.row()
            gr.cell(_latin1(name), colspan=2,
                    style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=hrgb))
            face = FontFace(color=(0, 0, 0), fill_color=tint)
            for rule, pts in rows:
                row = table.row()
                row.cell(_latin1(rule), style=face)
                row.cell(_latin1(pts), style=face)

    pdf.output(path)


if __name__ == "__main__":
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    md_path = os.path.join(here, "RULES.md")
    pdf_path = os.path.join(here, "rules.pdf")

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(CONTENT))
    print(f"wrote {md_path}")

    # Standalone teams-only reference.
    pots_content = [
        ("h1", "WC2026 Friends — Draft Pots"),
        ("p", "16 players, three teams each (one per pot). Pots by \"reach QF\" odds; order within each pot by Polymarket winner odds."),
        ("table", _POT_HEADERS, _POT_ROWS),
    ]
    pots_path = os.path.join(here, "POTS.md")
    with open(pots_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(pots_content))
    print(f"wrote {pots_path}")

    try:
        render_pdf(CONTENT, pdf_path)
        print(f"wrote {pdf_path}")
        mini_path = os.path.join(here, "mini-rules.pdf")
        render_mini_pdf(mini_path)
        print(f"wrote {mini_path}")
    except ImportError:
        print("fpdf2 not installed — skipped PDF (run: pip install fpdf2)")
