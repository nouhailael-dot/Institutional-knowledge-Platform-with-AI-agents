"""
Run the UNGA & Climate Week 2026 event translator.

Dry-run by default: parses, logs an audit CSV, and rolls back. Use --apply to
commit. Mirrors the run pattern of the other ETL entry-point scripts.

    python scripts/run_unga_climate_week.py            # dry run
    python scripts/run_unga_climate_week.py --apply    # commit
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import SessionLocal
from src.etl.translators.UNGA_climate_week import UngaClimateWeekTranslator

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
logger = logging.getLogger("run_unga_climate_week")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="commit changes; without this the run is a dry run")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("Starting UNGA / Climate Week translator [%s]", mode)

    with SessionLocal() as session:
        try:
            stats = UngaClimateWeekTranslator(PROJECT_ROOT, session, apply=args.apply).run()
        except Exception:
            session.rollback()
            logger.exception("UNGA / Climate Week translator crashed")
            return 2

    print("\n" + "=" * 56)
    print(f"[{mode}] inserted={stats.events_inserted}  matched={stats.events_matched}  "
          f"header_rows={stats.rows_skipped_header}  empty={stats.rows_skipped_empty}  "
          f"failed={stats.rows_failed}")
    print("Audit log: data/interim/unga_climate_week_audit.csv")
    if not args.apply:
        print("Dry run — nothing committed. Re-run with --apply.")
    return 2 if stats.rows_failed else 0


if __name__ == "__main__":
    sys.exit(main())