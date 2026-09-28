"""
Task 4: Reclassify actors currently typed as 'other' using Claude Haiku 4.5.

Reads every actor where actor_type = 'other', sends each to Claude with
available context, and updates the actor's type based on Claude's classification.

Updates verification_status to 'ai_inferred' and confidence to 0.7.

Idempotent: only touches actors still typed as 'other', so re-runs skip
actors already reclassified.

Full audit trail written to data/interim/ai_reclassification_audit.csv.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.enrichment.decisions import persist_canonical_record
from src.ai.client import HAIKU, UsageTracker, call_claude, parse_json_response
from src.db.models import Actor, Hub, HubActor, Source

logger = logging.getLogger(__name__)


AUDIT_LOG = "data/interim/ai_reclassification_audit.csv"


# ============================================================
# ALLOWED ACTOR TYPES
# Must match the enum documented in ADR-006 and the schema.
# ============================================================

ALLOWED_TYPES = [
    "university_lab",
    "national_research_lab",
    "startup",
    "corporate_rd_lab",
    "federal_agency",
    "federal_research_system",
    "national_research_center",
    "industrial_partner",
    "project_developer",
    "un_agency",
    "un_programme",
    "un_committee",
    "un_secretariat",
    "multilateral_development_bank",
    "intergovernmental_organization",
    "university",
    "company",
    "accelerator",
    "consortium",
    "state_agency",              # new
    "government_agency",         # new
    "industry_association",      # new
    "venture_capital",           # new
    "nonprofit",                 # new
    "research_organization",     # new
    "other",
]


# ============================================================
# PROMPT
# ============================================================

SYSTEM_PROMPT = f"""You are an expert at classifying research and industry organizations.

Given an organization's name and any available context, classify it into one of these exact types:

{chr(10).join(f"- {t}" for t in ALLOWED_TYPES)}

Type definitions:
- university_lab: A specific lab, center, or department inside a university (e.g., "MIT Energy Initiative", "Center for Watershed Sciences")
- national_research_lab: A national laboratory operated by or for a government (e.g., "NREL", "Argonne National Laboratory", "Oak Ridge")
- startup: An early-stage venture-backed company
- corporate_rd_lab: A large corporation's R&D arm or the company itself when acting as an industrial player (e.g., "Ford", "Bayer", "Shell")
- federal_agency: A national government agency (e.g., "USDA", "NSF", "DOE", "EPA")
- federal_research_system: A large multi-institution federal research network
- national_research_center: A specialized national research center
- industrial_partner: A large industrial operator (e.g., mining companies, chemical processors)
- project_developer: An early-stage project or infrastructure developer
- un_agency / un_programme / un_committee / un_secretariat: UN system entities
- multilateral_development_bank: World Bank Group, IFC, IDA, IBRD, regional development banks
- intergovernmental_organization: Other cross-country institutions
- university: A university or college as a whole (e.g., "MIT", "Stanford", "UC Davis")
- company: A general commercial company that doesn't fit corporate_rd_lab
- accelerator: A startup accelerator, incubator, or venture studio
- consortium: A multi-organization consortium or collaborative body
- other: Only if none of the above genuinely fit

Return ONLY a JSON object with this exact structure:
{{"type": "one_of_the_types_above", "confidence": 0.0_to_1.0, "reasoning": "one short sentence"}}

Do not include markdown code fences. Do not add extra text before or after the JSON.
"""


def build_user_prompt(actor: Actor, hub_names: list[str]) -> str:
    """Build the user message describing a single actor for Claude."""
    parts = [f"Organization name: {actor.name}"]

    if actor.description:
        parts.append(f"Description: {actor.description[:500]}")

    if actor.website:
        parts.append(f"Website: {actor.website}")

    if actor.location_city or actor.state:
        loc = ", ".join(filter(None, [actor.location_city, actor.state]))
        parts.append(f"Location: {loc}")

    if hub_names:
        parts.append(f"Appears in these hubs: {', '.join(hub_names[:5])}")

    parts.append("\nClassify this organization.")
    return "\n".join(parts)


# ============================================================
# STATS
# ============================================================

@dataclass
class RunStats:
    total_others_found: int = 0
    reclassified: int = 0
    stayed_other: int = 0
    invalid_response: int = 0
    api_failures: int = 0
    low_confidence: int = 0

    def summary(self) -> str:
        return (
            f"  Total 'other' actors found:    {self.total_others_found}\n"
            f"  Reclassified to real types:    {self.reclassified}\n"
            f"  Stayed 'other' (Claude's call):{self.stayed_other}\n"
            f"  Low confidence (<0.5) skipped: {self.low_confidence}\n"
            f"  Invalid JSON responses:        {self.invalid_response}\n"
            f"  API failures:                  {self.api_failures}"
        )


# ============================================================
# CORE
# ============================================================

class OtherReclassifier:

    def __init__(self, project_root: Path, session: Session, limit: Optional[int] = None):
        self.project_root = project_root
        self.session = session
        self.limit = limit  # None = process all; otherwise a test batch size
        self.stats = RunStats()
        self.tracker = UsageTracker(model=HAIKU)

        # Open audit log
        log_path = project_root / AUDIT_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_fh = open(log_path, "w", newline="", encoding="utf-8")
        self.audit_writer = csv.writer(self.audit_fh)
        self.audit_writer.writerow([
            "actor_id", "name", "old_type", "new_type",
            "confidence", "reasoning", "verdict"
        ])

    def _close_logs(self):
        self.audit_fh.close()

    def _get_or_create_ai_source(self) -> Source:
        """Source row representing this AI reclassification run."""
        desc = "Task 4: AI reclassification of 'other' actors (Claude Haiku 4.5)"
        existing = self.session.execute(
            select(Source).where(Source.description == desc)
        ).scalar_one_or_none()
        if existing:
            return existing
        source = Source(
            source_type="ai_inference",
            url=None,
            retrieved_at=datetime.now(),
            description=desc,
            trust_tier="candidate",
        )
        persist_canonical_record(self.session, source)
        self.session.flush()
        return source

    def _get_actor_hubs(self, actor: Actor) -> list[str]:
        """Return names of hubs the actor is linked to."""
        rows = self.session.execute(
            select(Hub.name).join(HubActor, HubActor.hub_id == Hub.hub_id)
            .where(HubActor.actor_id == actor.actor_id)
        ).all()
        return [r[0] for r in rows]

    def _process_actor(self, actor: Actor, source: Source):
        hub_names = self._get_actor_hubs(actor)
        user_prompt = build_user_prompt(actor, hub_names)

        response_text = call_claude(
            model=HAIKU,
            system=SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=200,
            tracker=self.tracker,
        )

        if response_text is None:
            self.stats.api_failures += 1
            self.audit_writer.writerow([
                str(actor.actor_id), actor.name, "other", "",
                "", "", "api_failure"
            ])
            return

        parsed = parse_json_response(response_text)
        if not parsed or "type" not in parsed:
            self.stats.invalid_response += 1
            self.audit_writer.writerow([
                str(actor.actor_id), actor.name, "other", "",
                "", response_text[:200] if response_text else "", "invalid_json"
            ])
            return

        new_type = parsed.get("type", "").strip()
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = parsed.get("reasoning", "")[:200]

        # Validate the type
        if new_type not in ALLOWED_TYPES:
            self.stats.invalid_response += 1
            self.audit_writer.writerow([
                str(actor.actor_id), actor.name, "other", new_type,
                confidence, reasoning, "invalid_type"
            ])
            return

        # Skip low-confidence classifications
        if confidence < 0.5:
            self.stats.low_confidence += 1
            self.audit_writer.writerow([
                str(actor.actor_id), actor.name, "other", new_type,
                confidence, reasoning, "low_confidence_skipped"
            ])
            return

        # Skip if Claude said "other" — no improvement
        if new_type == "other":
            self.stats.stayed_other += 1
            self.audit_writer.writerow([
                str(actor.actor_id), actor.name, "other", new_type,
                confidence, reasoning, "stayed_other"
            ])
            return

        # Apply the reclassification
        actor.actor_type = new_type
        actor.verification_status = "ai_inferred"
        actor.confidence = 0.7  # AI-inferred trust level
        actor.source_id = source.source_id
        self.stats.reclassified += 1

        self.audit_writer.writerow([
            str(actor.actor_id), actor.name, "other", new_type,
            confidence, reasoning, "reclassified"
        ])

    def run(self) -> RunStats:
        # Find all 'other' actors
        query = select(Actor).where(Actor.actor_type == "other")
        if self.limit:
            query = query.limit(self.limit)

        actors = self.session.execute(query).scalars().all()
        self.stats.total_others_found = len(actors)

        if not actors:
            logger.info("No 'other' actors found — nothing to do.")
            self._close_logs()
            return self.stats

        source = self._get_or_create_ai_source()

        logger.info("Processing %d 'other' actors with %s", len(actors), HAIKU)
        for i, actor in enumerate(actors, 1):
            if i % 25 == 0:
                logger.info("Progress: %d/%d (running cost: $%.4f)",
                            i, len(actors), self.tracker.cost_estimate())
            self._process_actor(actor, source)

        self.session.commit()
        self._close_logs()
        return self.stats