"""Refresh search_doc/search_doc_2 actor text from cleaned actor rows."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

PROJECT_ROOT = Path(r"C:\Users\Ismail\Projects\GHUS-Platform")
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import Actor, Hub, HubActor  # noqa: E402
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


def load_hubs(session, actor_ids):
    hubs: dict[Any, list[str]] = defaultdict(list)
    if not actor_ids:
        return hubs
    for actor_id, hub_name in session.execute(
        select(HubActor.actor_id, Hub.name)
        .join(Hub, Hub.hub_id == HubActor.hub_id)
        .where(HubActor.actor_id.in_(actor_ids))
    ):
        hubs[actor_id].append(hub_name)
    return hubs


def location_line(actor: Actor) -> str:
    parts = [clean(actor.location_city), clean(actor.state), clean(actor.country)]
    return ", ".join(part for part in parts if part)


def build_doc_text(actor: Actor, hubs: list[str]) -> str:
    lines = [f"Name: {actor.name}"]
    if clean(actor.actor_type):
        lines.append(f"Type: {clean(actor.actor_type)}")
    if clean(actor.website):
        lines.append(f"Website: {clean(actor.website)}")
    location = location_line(actor)
    if location:
        lines.append(f"Location: {location}")
    if clean(actor.description):
        lines.append(f"Description: {clean(actor.description)}")
    if clean(actor.primary_technical_focus):
        lines.append(f"Primary technical focus: {clean(actor.primary_technical_focus)}")
    if clean(actor.technical_approach):
        lines.append(f"Technical approach: {clean(actor.technical_approach)}")
    if clean(actor.current_activities):
        lines.append(f"Current activities: {clean(actor.current_activities)}")
    if clean(actor.technology_ip_notes):
        lines.append(f"Technology/IP notes: {clean(actor.technology_ip_notes)}")
    if clean(actor.key_constraints):
        lines.append(f"Key constraints: {clean(actor.key_constraints)}")
    if clean(actor.funding_summary):
        lines.append(f"Funding summary: {clean(actor.funding_summary)}")
    if clean(actor.primary_lifecycle_role):
        lines.append(f"Lifecycle role: {clean(actor.primary_lifecycle_role)}")
    if hubs:
        lines.append(f"Part of hubs: {', '.join(hubs)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--only-template-hits", action="store_true")
    args = parser.parse_args()

    changed: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        actor_by_id = {actor.actor_id: actor for actor in actors}
        hubs = load_hubs(session, list(actor_by_id))

        for table in ("search_doc", "search_doc_2"):
            rows = session.execute(
                text(f"""
                    SELECT entity_id, doc_text
                    FROM {table}
                    WHERE entity_type = 'actor'
                """)
            ).mappings().all()
            for row in rows:
                actor = actor_by_id.get(row["entity_id"])
                if not actor:
                    skipped.append((table, str(row["entity_id"])))
                    continue
                old_doc = row["doc_text"] or ""
                if args.only_template_hits and not has_template(old_doc):
                    continue
                new_doc = build_doc_text(actor, hubs[actor.actor_id])
                if clean(old_doc) == clean(new_doc):
                    continue
                changed.append((table, actor.name))
                if args.apply:
                    if table == "search_doc_2":
                        session.execute(
                            text("""
                                UPDATE search_doc_2
                                SET name = :name,
                                    doc_text = :doc_text,
                                    website = :website,
                                    updated_at = :updated_at,
                                    verification_status = :verification_status,
                                    confidence = :confidence,
                                    indexed_at = now()
                                WHERE entity_id = :entity_id
                                  AND entity_type = 'actor'
                            """),
                            {
                                "entity_id": actor.actor_id,
                                "name": actor.name,
                                "doc_text": new_doc,
                                "website": actor.website,
                                "updated_at": actor.updated_at,
                                "verification_status": actor.verification_status,
                                "confidence": str(actor.confidence) if actor.confidence is not None else None,
                            },
                        )
                    else:
                        session.execute(
                            text("""
                                UPDATE search_doc
                                SET name = :name,
                                    doc_text = :doc_text
                                WHERE entity_id = :entity_id
                                  AND entity_type = 'actor'
                            """),
                            {
                                "entity_id": actor.actor_id,
                                "name": actor.name,
                                "doc_text": new_doc,
                            },
                        )

        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"changed_rows={len(changed)}")
    print("changed_by_table=" + str(dict(Counter(table for table, _ in changed))))
    print(f"skipped_missing_actor={len(skipped)}")
    for table, name in changed[:120]:
        print(f"CHANGED|{table}|{name}")
    for table, entity_id in skipped[:30]:
        print(f"SKIPPED_MISSING_ACTOR|{table}|{entity_id}")


if __name__ == "__main__":
    main()
