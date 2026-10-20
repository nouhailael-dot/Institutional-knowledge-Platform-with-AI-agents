"""
Run Task 2: extract named researchers from hub talent narratives.

Default mode is a dry-run: it calls Claude, prints/writes an audit CSV, and
rolls back all database changes. Use --apply only after reviewing a sample.

Usage:
    python scripts/run_researcher_enrichement.py --limit 5
    python scripts/run_researcher_enrichement.py --limit 5 --apply
    python scripts/run_researcher_enrichement.py --apply
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.enrichment.decisions import persist_canonical_record

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.client import SONNET, UsageTracker  # noqa: E402
from src.db.models import (  # noqa: E402
    Actor,
    ActorPerson,
    Hub,
    HubActor,
    Person,
    Source,
)
from src.db.session import SessionLocal  # noqa: E402
from src.enrichment.extractors.researchers import extract_researchers  # noqa: E402

logger = logging.getLogger("run_researcher_enrichement")

AI_CONFIDENCE = 0.7
DEFAULT_ROLE = "researcher"
AUDIT_DIR = PROJECT_ROOT / "data" / "interim"


@dataclass
class RunStats:
    hubs_seen: int = 0
    people_extracted: int = 0
    people_created: int = 0
    people_existing: int = 0
    links_created: int = 0
    links_existing: int = 0
    no_actor_match: int = 0
    failures: int = 0

    def summary(self) -> str:
        return (
            f"  Hubs processed:        {self.hubs_seen}\n"
            f"  People extracted:      {self.people_extracted}\n"
            f"  People created:        {self.people_created}\n"
            f"  Existing people reused:{self.people_existing}\n"
            f"  Actor links created:   {self.links_created}\n"
            f"  Existing links reused: {self.links_existing}\n"
            f"  No actor match:        {self.no_actor_match}\n"
            f"  Failures:              {self.failures}"
        )


def normalize_name(value: str) -> str:
    """Normalize names for conservative exact deduplication."""
    value = re.sub(r"\s+", " ", value or "").strip().lower()
    value = re.sub(r"^(dr|prof|professor)\.?\s+", "", value)
    return value


def normalize_org(value: Optional[str]) -> str:
    value = re.sub(r"\s+", " ", value or "").strip().lower()
    value = re.sub(r"[^\w\s&.-]", "", value)
    return value


def as_role(title: Optional[str]) -> str:
    role = (title or DEFAULT_ROLE).strip() or DEFAULT_ROLE
    return role[:120]


class ResearcherEnricher:
    def __init__(
        self,
        session: Session,
        *,
        limit: Optional[int] = None,
        apply: bool = False,
        model: str = SONNET,
    ):
        self.session = session
        self.limit = limit
        self.apply = apply
        self.model = model
        self.tracker = UsageTracker(model=model)
        self.stats = RunStats()
        self.people_by_name = self._load_people_by_normalized_name()
        self.actor_by_name = self._load_actors_by_normalized_name()

        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audit_path = AUDIT_DIR / f"researcher_enrichment_{stamp}.csv"
        self.audit_fh = self.audit_path.open("w", newline="", encoding="utf-8")
        self.audit_writer = csv.writer(self.audit_fh)
        self.audit_writer.writerow(
            [
                "hub_id",
                "hub_name",
                "full_name",
                "title",
                "research_area",
                "affiliation",
                "evidence",
                "model_confidence",
                "person_action",
                "actor_match",
                "link_action",
            ]
        )

    def close(self) -> None:
        if not self.audit_fh.closed:
            self.audit_fh.close()

    def _load_people_by_normalized_name(self) -> dict[str, Person]:
        rows = self.session.execute(select(Person)).scalars().all()
        return {normalize_name(p.full_name): p for p in rows}

    def _load_actors_by_normalized_name(self) -> dict[str, list[Actor]]:
        actors: dict[str, list[Actor]] = {}
        for actor in self.session.execute(select(Actor)).scalars():
            actors.setdefault(normalize_org(actor.name), []).append(actor)
        return actors

    def _get_or_create_ai_source(self) -> Source:
        desc = f"Task 2: AI researcher extraction from hub talent narratives ({self.model})"
        existing = self.session.execute(
            select(Source).where(Source.description == desc)
        ).scalar_one_or_none()
        if existing:
            return existing
        source = Source(
            source_type="ai_inference",
            url=None,
            retrieved_at=dt.datetime.now(),
            description=desc,
            trust_tier="candidate",
        )
        persist_canonical_record(self.session, source)
        self.session.flush()
        return source

    def _hub_actor_candidates(self, hub: Hub) -> dict[str, Actor]:
        rows = self.session.execute(
            select(Actor)
            .join(HubActor, HubActor.actor_id == Actor.actor_id)
            .where(HubActor.hub_id == hub.hub_id)
        ).scalars()
        return {normalize_org(actor.name): actor for actor in rows}

    def _match_actor(self, hub: Hub, affiliation: Optional[str]) -> Optional[Actor]:
        if not affiliation:
            return None
        key = normalize_org(affiliation)
        if not key:
            return None

        hub_actor = self._hub_actor_candidates(hub).get(key)
        if hub_actor:
            return hub_actor

        global_matches = self.actor_by_name.get(key, [])
        if len(global_matches) == 1:
            return global_matches[0]
        return None

    def _get_or_create_person(self, item: dict, source: Source | None) -> tuple[Person, str]:
        key = normalize_name(item["full_name"])
        existing = self.people_by_name.get(key)
        if existing:
            self.stats.people_existing += 1
            return existing, "person_exists"

        person = Person(
            full_name=item["full_name"][:255],
            title=item.get("title"),
            bio=item.get("research_area"),
            source_id=source.source_id if source else None,
            verification_status="ai_inferred" if source else None,
            confidence=AI_CONFIDENCE if source else None,
        )
        persist_canonical_record(self.session, person)
        self.session.flush()
        self.people_by_name[key] = person
        self.stats.people_created += 1
        return person, "person_created"

    def _link_person(self, actor: Actor | None, person: Person, role: str) -> str:
        if not actor:
            self.stats.no_actor_match += 1
            return "no_actor_match"

        existing = self.session.get(
            ActorPerson,
            {
                "actor_id": actor.actor_id,
                "person_id": person.person_id,
                "role": role,
            },
        )
        if existing:
            self.stats.links_existing += 1
            return "link_exists"

        persist_canonical_record(
            self.session,
            ActorPerson(
                actor_id=actor.actor_id,
                person_id=person.person_id,
                role=role,
                is_current=True,
            )
        )
        self.stats.links_created += 1
        return "link_created"

    def _write_audit(
        self,
        hub: Hub,
        item: dict,
        person_action: str,
        actor: Actor | None,
        link_action: str,
    ) -> None:
        self.audit_writer.writerow(
            [
                hub.hub_id,
                hub.name,
                item.get("full_name"),
                item.get("title"),
                item.get("research_area"),
                item.get("affiliation"),
                item.get("evidence"),
                item.get("confidence"),
                person_action,
                actor.name if actor else "",
                link_action,
            ]
        )

    def run(self) -> RunStats:
        query = (
            select(Hub)
            .where(Hub.talent_narrative.isnot(None), Hub.talent_narrative != "")
            .order_by(Hub.name)
        )
        if self.limit:
            query = query.limit(self.limit)
        hubs = self.session.execute(query).scalars().all()
        self.stats.hubs_seen = len(hubs)

        source = self._get_or_create_ai_source() if self.apply else None
        mode = "APPLY" if self.apply else "DRY-RUN"
        logger.info("[%s] hubs to process: %d", mode, len(hubs))

        for i, hub in enumerate(hubs, 1):
            logger.info("[%d/%d] extracting researchers from %s", i, len(hubs), hub.name)
            try:
                people = extract_researchers(
                    hub.name,
                    hub.talent_narrative or "",
                    model=self.model,
                    tracker=self.tracker,
                )
            except Exception as err:
                self.stats.failures += 1
                self.audit_writer.writerow(
                    [hub.hub_id, hub.name, "", "", "", "", "", "", "ERROR", "", str(err)[:200]]
                )
                logger.exception("Failed on hub %s: %s", hub.name, err)
                continue

            self.stats.people_extracted += len(people)
            if not people:
                logger.info("  no named people found")
                continue

            for item in people:
                person, person_action = self._get_or_create_person(item, source)
                actor = self._match_actor(hub, item.get("affiliation"))
                link_action = self._link_person(actor, person, as_role(item.get("title")))
                self._write_audit(hub, item, person_action, actor, link_action)
                logger.info(
                    "  %s | %s | actor=%s",
                    item["full_name"],
                    person_action,
                    actor.name if actor else "no match",
                )

        if self.apply:
            self.session.commit()
        else:
            self.session.rollback()
        self.close()
        return self.stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Process at most N hubs.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database.")
    parser.add_argument("--model", default=SONNET, help="Anthropic model id.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")

    with SessionLocal() as session:
        enricher = ResearcherEnricher(
            session,
            limit=args.limit,
            apply=args.apply,
            model=args.model,
        )
        try:
            stats = enricher.run()
        except Exception:
            session.rollback()
            enricher.close()
            logger.exception("Researcher enrichment crashed")
            return 2

    print("\n" + "=" * 60)
    print("Task 2 researcher enrichment complete.")
    print("=" * 60)
    print(stats.summary())
    print("\nUsage:")
    print(enricher.tracker.summary())
    print(f"\nAudit log: {enricher.audit_path}")
    if not args.apply:
        print("\nDry-run only - no database changes were committed.")
    return 2 if stats.failures else 0


if __name__ == "__main__":
    sys.exit(main())
