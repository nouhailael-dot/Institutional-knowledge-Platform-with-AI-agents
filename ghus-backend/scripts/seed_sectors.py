"""
seed_sectors.py — seed the sector table with UM6P Global Hub US priority sectors.

The sector table is empty, so event_sector tagging has nothing to match against.
This seeds the nine priority sectors (the event spreadsheet's tabs). The `code`
values match SECTOR_SHEETS in the events translator, so tagging resolves.

Idempotent: skips any code that already exists, so it is safe to re-run.

    python scripts/seed_sectors.py            # dry run
    python scripts/seed_sectors.py --apply
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from src.db.models import Sector
from src.db.session import SessionLocal

# (code, name) — code matches SECTOR_SHEETS values in the events translator.
# Codes AGRI, AI, CHEM, ENERGY, HEALTH, MINING, WATER, SUSTAIN already appear in
# hub.primary_sectors — this seed matches that existing vocabulary exactly so hubs
# and events share one sector set. DIASPORA is the one genuinely new sector.
SECTORS = [
    ("AGRI",     "Agriculture"),
    ("WATER",    "Water"),
    ("AI",       "Artificial Intelligence"),
    ("ENERGY",   "Energy Transition"),
    ("MINING",   "Mining"),
    ("CHEM",     "Specialty Chemicals"),
    ("HEALTH",   "Healthcare"),
    ("SUSTAIN",  "Sustainability"),
    ("DIASPORA", "African Diaspora"),
    ("CROSS",    "Cross-Thematic"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    s = SessionLocal()
    try:
        existing = {c for (c,) in s.execute(select(Sector.code)).all()}
        to_add = [(code, name) for code, name in SECTORS if code not in existing]

        print(f"[seed] {len(existing)} sector(s) already present")
        if not to_add:
            print("[seed] nothing to add — all sectors exist.")
            return
        print(f"[seed] will add {len(to_add)}:")
        for code, name in to_add:
            print(f"        {code:<10} {name}")

        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return

        for code, name in to_add:
            s.add(Sector(sector_id=uuid.uuid4(), code=code, name=name,
                         created_at=datetime.now()))
        s.commit()
        print(f"\n[done] inserted {len(to_add)} sector(s).")
    finally:
        s.close()


if __name__ == "__main__":
    main()