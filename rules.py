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
         ["Prime number of total goals (excludes shootout goals)", "-3"],
     ]),
    ("note",
     "A free-kick goal still counts toward your team's total-goals tally (so it "
     "can still trigger the prime -3 and the fewest-goals award) — it just "
     "earns you nothing directly."),

    ("h2", "The 90'+ rule"),
    ("bullets", [
        "A goal scored at 90:00 or later multiplies ALL of that team's points for that game by -1.",
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

    ("h2", "The draft — pots"),
    ("p",
     "The 48 finalists are split into three pots of 16 by their \"to reach the "
     "quarter-finals\" odds: Pot 1 = the 16 strongest, Pot 2 = the middle 16, "
     "Pot 3 = the 16 longest shots. The pots keep everyone's squad balanced. "
     "(Pot contents are listed separately and finalised once the 48-team field "
     "is confirmed.)"),

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
                x = pdf.get_x()
                pdf.multi_cell(5, 5.5, chr(149))  # latin-1 bullet
                pdf.set_xy(x + 5, pdf.get_y() - 5.5)
                pdf.multi_cell(epw - 5, 5.5, _latin1(item))
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


if __name__ == "__main__":
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    md_path = os.path.join(here, "RULES.md")
    pdf_path = os.path.join(here, "rules.pdf")

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(CONTENT))
    print(f"wrote {md_path}")

    try:
        render_pdf(CONTENT, pdf_path)
        print(f"wrote {pdf_path}")
    except ImportError:
        print("fpdf2 not installed — skipped PDF (run: pip install fpdf2)")
