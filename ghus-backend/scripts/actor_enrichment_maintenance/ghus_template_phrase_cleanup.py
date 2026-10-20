"""Find and remove old GHUS template/provenance phrases from DB text fields.

This targets text like:
- "Existing GHUS context ..."
- "hub-linked actor referenced ..."
- "No high-confidence structured API match ..."
- "Context used: linked hub context ..."

The cleanup is deterministic and conservative. It rewrites only actor text fields
where the content is clearly generated provenance, preserving hub/theme context
without the weak wording. It does not invent websites, locations, awards, or
organization facts.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.sql.sqltypes import String, Text

PROJECT_ROOT = Path(r"C:\Users\Ismail\Projects\GHUS-Platform")
WORKSPACE = Path(r"C:\Users\Ismail\Documents\GHUS")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(WORKSPACE))

from actor_quality_claude_refine import is_representative  # noqa: E402
from src.db.models import Actor, ActorSector, Hub, HubActor, Sector  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


PATTERNS = (
    "existing ghus",
    "ghus context",
    "hub-linked actor referenced",
    "context used:",
    "linked hub context:",
    "no high-confidence structured api match",
    "enriched from hub context only",
    "existing ghus record",
)


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def has_template(value: Any) -> bool:
    low = clean(value).lower()
    return any(pattern in low for pattern in PATTERNS)


def matched_patterns(value: Any) -> list[str]:
    low = clean(value).lower()
    return [pattern for pattern in PATTERNS if pattern in low]


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


def hub_label(hubs: list[str]) -> str:
    if not hubs:
        return "the linked ecosystem"
    if len(hubs) == 1:
        return hubs[0]
    return ", ".join(hubs[:3])


def domain_label(actor: Actor, sectors: list[str]) -> str:
    text_value = " ".join(
        [
            actor.name or "",
            actor.actor_type or "",
            actor.description or "",
            actor.primary_technical_focus or "",
            " ".join(sectors),
        ]
    ).lower()
    if "health" in text_value or "medical" in text_value or "hospital" in text_value:
        return "health and biomedical innovation"
    if "ai" in text_value or "artificial intelligence" in text_value or "robot" in text_value:
        return "AI and digital technology"
    if "ag" in text_value or "crop" in text_value or "farm" in text_value or "dairy" in text_value:
        return "agriculture and food systems"
    if "water" in text_value or "hydrology" in text_value or "desalination" in text_value:
        return "water and environmental systems"
    if "mining" in text_value or "mineral" in text_value or "lithium" in text_value:
        return "mining and critical minerals"
    if "energy" in text_value or "hydrogen" in text_value or "carbon" in text_value or "climate" in text_value:
        return "energy and climate technology"
    if "chem" in text_value or "catalysis" in text_value or "polymer" in text_value:
        return "chemistry, catalysis, and materials"
    if sectors:
        return sectors[0].lower()
    return "ecosystem activity"


def extract_themes(description: Any) -> list[str]:
    value = clean(description)
    marker = "emphasizes"
    idx = value.lower().find(marker)
    if idx == -1:
        return []
    tail = value[idx + len(marker):].strip(" .;:")
    tail = re.sub(r"\bContext used:.*$", "", tail, flags=re.IGNORECASE).strip(" .;:")
    raw_parts = re.split(r"\s*;\s*|\s+\|\s+", tail)
    themes = []
    for part in raw_parts:
        part = clean(part).strip(" .;:-")
        if not part:
            continue
        if part.lower().startswith("the linked hub context"):
            continue
        themes.append(part)
    return themes[:4]


def new_description(actor: Actor, hubs: list[str], sectors: list[str]) -> str:
    domain = domain_label(actor, sectors)
    hub = hub_label(hubs)
    themes = extract_themes(actor.description)
    if is_representative(actor):
        base = (
            f"Aggregate category for {domain} actors associated with {hub}. "
            "This row represents a group, program cluster, or ecosystem role rather than one legal entity."
        )
    else:
        base = (
            f"{actor.name} is included in the {hub} ecosystem mapping because of its relevance to {domain}. "
            "Organization-level evidence should be verified from primary sources before outreach or scoring."
        )
    if themes:
        base += " Relevant themes include " + "; ".join(themes) + "."
    return base


def new_current_activities(actor: Actor, hubs: list[str], sectors: list[str]) -> str:
    domain = domain_label(actor, sectors)
    hub = hub_label(hubs)
    if is_representative(actor):
        return (
            f"Aggregate mapping row for {domain} actors associated with {hub}; "
            "use it for ecosystem analysis, then decompose into named organizations for outreach."
        )
    return (
        f"Tracked in {hub} for {domain}; validate current organization-level activity, contacts, "
        "and evidence from primary sources before outreach."
    )


def new_value(actor: Actor, column: str, hubs: list[str], sectors: list[str]) -> str | None:
    current = getattr(actor, column)
    if not has_template(current):
        return None
    if column == "description":
        return new_description(actor, hubs, sectors)
    if column == "current_activities":
        return new_current_activities(actor, hubs, sectors)
    if column == "technology_ip_notes":
        return clean(current).replace("existing GHUS record", "current structured data")
    return None


def actor_hits(actors: list[Actor]) -> list[dict[str, str]]:
    cols = [c.name for c in Actor.__table__.columns if isinstance(c.type, (String, Text))]
    hits = []
    for actor in actors:
        for col in cols:
            value = getattr(actor, col)
            if not has_template(value):
                continue
            hits.append(
                {
                    "table": "actor",
                    "row_id": str(actor.actor_id),
                    "name": actor.name or "",
                    "column": col,
                    "patterns": "|".join(matched_patterns(value)),
                    "value": clean(value),
                }
            )
    return hits


def write_report(path: Path, hits: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["table", "row_id", "name", "column", "patterns", "value"])
        writer.writeheader()
        writer.writerows(hits)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default=str(WORKSPACE / "ghus_template_phrase_hits.csv"))
    args = parser.parse_args()

    changed: list[tuple[str, str]] = []
    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        hubs, sectors = load_context(session, [actor.actor_id for actor in actors])

        before_hits = actor_hits(actors)
        write_report(Path(args.report), before_hits)

        for actor in actors:
            for col in ("description", "current_activities", "technology_ip_notes"):
                replacement = new_value(actor, col, hubs[actor.actor_id], sectors[actor.actor_id])
                if replacement is None:
                    continue
                if clean(getattr(actor, col)) == clean(replacement):
                    continue
                changed.append((actor.name, col))
                if args.apply:
                    setattr(actor, col, replacement)

        if args.apply:
            session.commit()
        else:
            session.rollback()

        refreshed = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        after_hits = actor_hits(refreshed)

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"before_hits={len(before_hits)}")
    print("before_by_column=" + str(dict(Counter(hit["column"] for hit in before_hits))))
    print(f"changed_cells={len(changed)}")
    print("changed_by_column=" + str(dict(Counter(col for _, col in changed))))
    print(f"after_hits={len(after_hits)}")
    print("after_by_column=" + str(dict(Counter(hit["column"] for hit in after_hits))))
    print(f"report={Path(args.report)}")
    for name, col in changed[:120]:
        print(f"CHANGED|{name}|{col}")


if __name__ == "__main__":
    main()
