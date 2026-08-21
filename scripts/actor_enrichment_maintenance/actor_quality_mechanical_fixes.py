"""Apply deterministic actor quality fixes that should not spend AI credits."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import select, text

PROJECT_ROOT = Path(r"C:\Users\Ismail\Projects\GHUS-Platform")
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


URL_RE = re.compile(r"https?://[^\s)]+")

WEBSITE_OVERRIDES = {
    "Duke University": "https://www.duke.edu/",
}

SPEARSTONE_FUNDING = (
    "Startup funding profile: current structured context identifies a 2025 NSF SBIR Phase I "
    "award for clean-gypsum separation from phosphate-processing waste; additional scale-up "
    "would likely rely on non-dilutive grants, pilot customers, strategic remediation or "
    "critical-minerals partners, and private startup capital. Confirm later awards before "
    "treating them as funded."
)


def first_url(value: str) -> str | None:
    match = URL_RE.search(value or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;:")


def should_blank_aggregate_website(actor: Actor) -> bool:
    name = (actor.name or "").lower()
    return "tennessee" in name and "kentucky" in name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changes: list[str] = []
    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())

        for actor in actors:
            website = (actor.website or "").strip()
            new_website = None
            if actor.name in WEBSITE_OVERRIDES:
                new_website = WEBSITE_OVERRIDES[actor.name]
            elif website and not website.startswith(("http://", "https://")):
                if should_blank_aggregate_website(actor):
                    new_website = ""
                else:
                    new_website = first_url(website)

            if new_website is not None and new_website != website:
                changes.append(f"WEBSITE|{actor.name}|{website}|{new_website or '<blank>'}")
                if args.apply:
                    actor.website = new_website or None

            if actor.name == "Spearstone Solutions, LLC" and first_url(actor.funding_summary or ""):
                old = actor.funding_summary or ""
                changes.append(f"FUNDING|{actor.name}|{old}|{SPEARSTONE_FUNDING}")
                if args.apply:
                    actor.funding_summary = SPEARSTONE_FUNDING

        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"changes={len(changes)}")
    for change in changes:
        print(change)


if __name__ == "__main__":
    main()
