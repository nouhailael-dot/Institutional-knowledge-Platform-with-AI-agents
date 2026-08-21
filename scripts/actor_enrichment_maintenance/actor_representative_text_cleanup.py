"""Clean representative/category actor rows without using AI credits."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

PROJECT_ROOT = Path(r"C:\Users\Ismail\Projects\GHUS-Platform")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from actor_quality_claude_refine import audit_actor, is_representative  # noqa: E402
from src.db.models import Actor, ActorSector, Hub, HubActor, Sector  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def load_context(session, actor_ids):
    hubs: dict[Any, list[str]] = defaultdict(list)
    sectors: dict[Any, list[str]] = defaultdict(list)
    if not actor_ids:
        return hubs, sectors

    for actor_id, hub_name in session.execute(
        select(HubActor.actor_id, Hub.name)
        .join(Hub, Hub.hub_id == HubActor.hub_id)
        .where(HubActor.actor_id.in_(actor_ids))
    ):
        hubs[actor_id].append(hub_name)

    for actor_id, sector_name in session.execute(
        select(ActorSector.actor_id, Sector.name)
        .join(Sector, Sector.sector_id == ActorSector.sector_id)
        .where(ActorSector.actor_id.in_(actor_ids))
    ):
        sectors[actor_id].append(sector_name)

    return hubs, sectors


def domain_label(actor: Actor, sectors: list[str]) -> str:
    text_value = " ".join([actor.name or "", actor.description or "", " ".join(sectors)]).lower()
    if "health" in text_value or "medical" in text_value or "hospital" in text_value:
        return "health and biomedical"
    if "ai" in text_value or "artificial intelligence" in text_value or "robot" in text_value:
        return "AI and digital technology"
    if "ag" in text_value or "crop" in text_value or "farm" in text_value or "dairy" in text_value:
        return "agriculture and food systems"
    if "water" in text_value or "hydrology" in text_value:
        return "water and environmental systems"
    if "mining" in text_value or "mineral" in text_value or "critical" in text_value:
        return "mining and critical minerals"
    if "energy" in text_value or "hydrogen" in text_value or "carbon" in text_value or "climate" in text_value:
        return "energy and climate technology"
    if "venture" in text_value or "capital" in text_value or "fund" in text_value:
        return "investment and commercialization"
    if "policy" in text_value or "commission" in text_value or "authority" in text_value:
        return "policy and governance"
    if sectors:
        return sectors[0].lower()
    return "ecosystem"


def hub_label(hubs: list[str]) -> str:
    if not hubs:
        return "linked GHUS ecosystem"
    if len(hubs) == 1:
        return hubs[0]
    return ", ".join(hubs[:2])


def representative_values(actor: Actor, hubs: list[str], sectors: list[str]) -> dict[str, str]:
    domain = domain_label(actor, sectors)
    hub = hub_label(hubs)
    return {
        "primary_technical_focus": (
            f"Representative {domain} category for actors connected to {hub}; not a single verified organization."
        ),
        "technical_approach": (
            "Covers varied research, commercialization, policy, finance, or deployment approaches across the underlying organizations."
        ),
        "current_activities": (
            f"Used as a GHUS mapping label for {domain} actors; individual organizations require source-level validation before outreach."
        ),
        "technology_ip_notes": (
            "No single IP owner; publications, patents, proprietary assets, and know-how sit with the underlying organizations."
        ),
        "key_constraints": (
            "Not directly actionable as one partner; decompose into named organizations, sites, decision-makers, and verified evidence."
        ),
        "primary_lifecycle_role": "Multiple Roles",
        "funding_summary": (
            "Representative or aggregate actor row; funding varies by the underlying organizations and is not verified at this category level."
        ),
    }


def should_clean(actor: Actor) -> bool:
    if not is_representative(actor):
        return False

    name = clean(actor.name).lower()
    protected_exact = (
        "national institutes of health" in name
        or "novartis institutes" in name
        or "texas a&m engineering extension service (teex)" in name
        or name == "broad institute"
        or name == "mit lincoln laboratory"
        or name == "argonne national laboratory"
        or name.endswith(" board")
        or " producers board" in name
    )
    if protected_exact:
        return False

    obvious_category = any(
        phrase in name
        for phrase in (
            "programs",
            "initiatives",
            "cluster",
            "ecosystem",
            "regional presence",
            "research labs",
            "technology firms",
            "venture capital firms",
            "startups",
            "operators",
            "projects",
            "facilities",
            "authorities",
            "bodies",
            "issuers",
            "partners",
            "centers",
            "platforms",
            "producers",
        )
    )
    if clean(actor.website) and not obvious_category:
        return False

    issue_codes = {issue.code for issue in audit_actor(actor)}
    return bool(
        "representative_row_not_marked_in_funding" in issue_codes
        or any(code.startswith("weak_template_") for code in issue_codes)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changed: list[str] = []
    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        hubs, sectors = load_context(session, [actor.actor_id for actor in actors])

        for actor in actors:
            if not should_clean(actor):
                continue
            values = representative_values(actor, hubs[actor.actor_id], sectors[actor.actor_id])
            before = {field: clean(getattr(actor, field)) for field in values}
            if before == values:
                continue
            changed.append(actor.name)
            if args.apply:
                for field, value in values.items():
                    setattr(actor, field, value)

        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"changed_rows={len(changed)}")
    for name in changed[:120]:
        print(f"CHANGED|{name}")


if __name__ == "__main__":
    main()
