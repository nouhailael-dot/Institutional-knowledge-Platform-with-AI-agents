"""Prefix representative actor funding summaries with an explicit aggregate marker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # ghus-backend/
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from actor_quality_claude_refine import audit_actor  # noqa: E402
from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


PREFIX = "Representative or aggregate actor row; "


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changed: list[str] = []
    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        for actor in actors:
            codes = {issue.code for issue in audit_actor(actor)}
            if "representative_row_not_marked_in_funding" not in codes:
                continue
            current = (actor.funding_summary or "").strip()
            if not current or current.startswith(PREFIX):
                continue
            changed.append(actor.name)
            if args.apply:
                actor.funding_summary = PREFIX + current

        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"changed_rows={len(changed)}")
    for name in changed:
        print(f"CHANGED|{name}")


if __name__ == "__main__":
    main()
