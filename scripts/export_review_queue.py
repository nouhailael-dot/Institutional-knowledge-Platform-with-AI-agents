"""
export_review_queue.py — pull pending review pairs into a labeling workbook.

Turns the review_queue rows the sweep created into an .xlsx a human can work
through: the two names side by side, the model's score, and a dropdown decision.
Same shape as the duplicate-labeling workbook, so the workflow is familiar.

Decisions available:
  same       -> one entity; will be merged
  different  -> distinct entities
  hierarchy  -> related but not equal; one is a sub-unit of the other
  skip       -> undecided, stays pending

Sorted hardest-first (highest score) so the most consequential pairs get the
freshest attention.

    python scripts/export_review_queue.py
    python scripts/export_review_queue.py --limit 100 --out review_batch1.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.session import SessionLocal

SQL = """
SELECT rq.review_id::text, rq.score,
       a.actor_id::text AS actor_id_a, a.name AS name_a,
       COALESCE(a.location_city,'') AS loc_a, COALESCE(a.description,'') AS desc_a,
       b.actor_id::text AS actor_id_b, b.name AS name_b,
       COALESCE(b.location_city,'') AS loc_b, COALESCE(b.description,'') AS desc_b
FROM review_queue rq
JOIN actor a ON a.actor_id = rq.actor_id_a
JOIN actor b ON b.actor_id = rq.actor_id_b
WHERE rq.status = 'pending'
  AND a.merged_into_actor_id IS NULL
  AND b.merged_into_actor_id IS NULL
ORDER BY rq.score DESC
"""

NAVY, WHITE, YEL, LGRAY, GRAY = "1F4E78", "FFFFFF", "FFF7D6", "F7F9FC", "6B7280"


def f(sz=10, b=False, color="1A1A1A", it=False):
    return Font(name="Arial", size=sz, bold=b, color=color, italic=it)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/ml/results/review_queue.xlsx")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    s = SessionLocal()
    try:
        df = pd.read_sql(text(SQL), s.connection())
    finally:
        s.close()
    if args.limit:
        df = df.head(args.limit)
    if df.empty:
        print("no pending review pairs."); return
    print(f"[queue] {len(df)} pending pair(s), scores "
          f"{df.score.min():.2f}-{df.score.max():.2f}")

    wb = Workbook()
    ws = wb.active; ws.title = "How to review"; ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2; ws.column_dimensions["B"].width = 100
    lines = [
        ("Entity resolution — review queue", 16, True, NAVY),
        (f"{len(df)} pairs the model could not decide on its own", 10, False, GRAY),
        ("", 10, False, "1A1A1A"),
        ("For each row, pick a decision from the dropdown:", 11, True, NAVY),
        ("  same       — the two rows are one real organization (they will be merged)", 10, False, "1A1A1A"),
        ("  different  — distinct organizations", 10, False, "1A1A1A"),
        ("  hierarchy  — related but not equal: one is a department/division of the other", 10, False, "1A1A1A"),
        ("  skip       — leave undecided for now", 10, False, "1A1A1A"),
        ("", 10, False, "1A1A1A"),
        ("Watch out for these:", 11, True, NAVY),
        ("  'X State University' and 'University of X' are DIFFERENT schools", 10, False, "1A1A1A"),
        ("     (Michigan State University is not the University of Michigan)", 10, False, "1A1A1A"),
        ("  A department is 'hierarchy', not 'same', when paired with its parent university", 10, False, "1A1A1A"),
        ("  Acronym vs full name IS the same entity (NREL = National Renewable Energy Laboratory)", 10, False, "1A1A1A"),
        ("", 10, False, "1A1A1A"),
        ("Rows are sorted by model score, highest first. When unsure, choose 'different'.", 10, True, NAVY),
    ]
    r = 2
    for t, sz, b, c in lines:
        cell = ws.cell(r, 2, t); cell.font = f(sz, b, c)
        cell.alignment = Alignment(wrap_text=True, vertical="top"); r += 1

    ws = wb.create_sheet("Pairs to review"); ws.sheet_view.showGridLines = False
    headers = [("score", 8), ("name_a", 38), ("name_b", 38), ("decision", 14),
               ("notes (optional)", 26), ("location_a", 16), ("location_b", 16),
               ("review_id", 34), ("actor_id_a", 34), ("actor_id_b", 34)]
    thin = Side(style="thin", color="D5DAE0"); bd = Border(thin, thin, thin, thin)
    for i, (h, w) in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(1, i, h); c.font = f(10, True, WHITE)
        c.fill = PatternFill("solid", fgColor=NAVY); c.border = bd
        c.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    ws.row_dimensions[1].height = 24; ws.freeze_panes = "E2"

    for i, row in enumerate(df.itertuples(index=False), start=2):
        vals = [round(float(row.score), 3), row.name_a, row.name_b, "", "",
                row.loc_a, row.loc_b, row.review_id, row.actor_id_a, row.actor_id_b]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v); c.font = f(10); c.border = bd
            c.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
            if i % 2 == 0 and j not in (4, 5):
                c.fill = PatternFill("solid", fgColor=LGRAY)
        ws.cell(i, 4).fill = PatternFill("solid", fgColor=YEL)
        ws.cell(i, 5).fill = PatternFill("solid", fgColor=YEL)
        ws.cell(i, 4).alignment = Alignment(vertical="top", horizontal="center")
        ws.row_dimensions[i].height = 28

    last = len(df) + 1
    dv = DataValidation(type="list", formula1='"same,different,hierarchy,skip"',
                        allow_blank=True, promptTitle="Decision",
                        prompt="same / different / hierarchy / skip")
    ws.add_data_validation(dv); dv.add(f"D2:D{last}")
    ws.cell(1, 12, "decided:").font = f(9, True, GRAY)
    ws.cell(1, 13, f'=COUNTIF(D2:D{last},"?*")').font = f(9, True, NAVY)
    ws.cell(1, 14, f"of {len(df)}").font = f(9, False, GRAY)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"[saved] {out}")
    print("Fill the yellow 'decision' column, then run apply_review_decisions.py")


if __name__ == "__main__":
    main()