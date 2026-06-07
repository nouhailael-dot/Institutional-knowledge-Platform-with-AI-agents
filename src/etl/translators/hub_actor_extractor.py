"""
Hub actor extractor.

Reads the Ecosystem Mapping spreadsheet directly (with newlines preserved),
parses the Actor Composition and Programs and Labs columns into individual
organizations, and creates actor + hub_actor rows in the database.

Every extracted actor is marked verification_status='needs_review' and
confidence=0.5 so they're visibly imperfect and can be cleaned up later
by AI enrichment or human review.

Usage (from project root, with .venv active):
    python -m scripts.extract_hub_actors
"""

from __future__ import annotations

import csv
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Actor, Hub, HubActor, Source
from src.etl.common.text_cleaning import slugify


logger = logging.getLogger(__name__)


SOURCE_FILE = "data/raw/Ecosystem_Mapping_The_Final_UpV.xlsx"
SHEET_NAME = "Ecosystem Mapping"
AUDIT_LOG_PATH = "data/interim/hub_actor_extraction_audit.csv"
DATA_STARTS_AT_ROW = 2

COL_NAME = 0
COL_COMPOSITION = 3
COL_PROGRAMS = 12

# Phrases that should never become actor names (noise filters)
NOISE_PATTERNS = {
    "tbd", "to be determined", "see above", "see below",
    "various", "multiple", "other", "etc", "etc.",
}

# Minimum length for a candidate to be treated as an organization
MIN_ACTOR_NAME_LENGTH = 4

# Strings that strongly suggest the line is a section/category, not a real org
SKIP_IF_STARTS_WITH = ("• ", "- ", "* ")  # bullet markers from original Excel

# Common organization-type hints used to classify the extracted actor
TYPE_HINTS: list[tuple[str, str]] = [
    ("national laboratory", "national_research_lab"),
    ("national lab", "national_research_lab"),
    ("national research", "national_research_lab"),
    ("university", "university"),
    ("college of", "university"),
    ("institute of technology", "university"),
    ("school of", "university"),
    ("department of", "university_lab"),
    ("center for", "university_lab"),
    ("centre for", "university_lab"),
    ("laboratory", "university_lab"),
    (" lab", "university_lab"),
    ("institute", "university_lab"),
    ("startup", "startup"),
    ("ventures", "startup"),
    ("corporation", "corporate_rd_lab"),
    ("inc.", "corporate_rd_lab"),
    ("llc", "corporate_rd_lab"),
    ("agency", "federal_agency"),
    ("department", "federal_agency"),
]


@dataclass
class ExtractionStats:
    actors_created: int = 0
    actors_existing: int = 0
    links_created: int = 0
    links_existing: int = 0
    candidates_rejected: int = 0
    hubs_processed: int = 0

    def summary(self) -> str:
        return (
            f"  Hubs processed:         {self.hubs_processed}\n"
            f"  Actors created (new):   {self.actors_created}\n"
            f"  Actors matched (exist): {self.actors_existing}\n"
            f"  Hub-actor links new:    {self.links_created}\n"
            f"  Hub-actor links exist:  {self.links_existing}\n"
            f"  Candidates rejected:    {self.candidates_rejected}"
        )


def split_narrative(text: str) -> list[str]:
    """Split a multi-organization narrative into individual candidate names.

    Rules:
    - Split on actual line breaks first (the source spreadsheet uses these as the primary separator)
    - Within a line, do not split on commas blindly — many real org names contain commas
      (e.g., 'University of California, Davis')
    - Trim each candidate and drop empties
    """
    if not text:
        return []

    # Split on newlines (the source spreadsheet uses these as line breaks)
    lines = re.split(r"[\r\n]+", text)
    candidates = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip leading bullets/markers
        for marker in SKIP_IF_STARTS_WITH:
            if line.startswith(marker):
                line = line[len(marker):].strip()
        candidates.append(line)
    return candidates


def looks_like_organization(name: str) -> bool:
    """Filter to decide whether a candidate string is plausibly an organization."""
    if not name or len(name) < MIN_ACTOR_NAME_LENGTH:
        return False
    lower = name.lower().strip(".:- ")
    if lower in NOISE_PATTERNS:
        return False
    # Must contain at least one letter
    if not re.search(r"[a-zA-Z]", name):
        return False
    # Must have at least one capital letter (real org names are proper nouns)
    if not re.search(r"[A-Z]", name):
        return False
    return True


def classify_actor_type(name: str) -> str:
    """Heuristically classify an actor name into an actor_type enum value."""
    lower = name.lower()
    for hint, type_code in TYPE_HINTS:
        if hint in lower:
            return type_code
    return "other"




class HubActorExtractor:
    def __init__(self, project_root: Path, session: Session):
        self.project_root = project_root
        self.session = session
        self.source_path = project_root / SOURCE_FILE
        self.stats = ExtractionStats()

        # Open audit log
        log_path = project_root / AUDIT_LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_fh = open(log_path, "w", newline="", encoding="utf-8")
        self.audit_writer = csv.writer(self.audit_fh)
        self.audit_writer.writerow(
            ["hub_name", "source_column", "candidate", "verdict", "actor_id_or_reason"]
        )

        # In-memory cache for normalized name -> actor
        # This is the deduplication layer across hubs
        self._actor_cache: dict[str, Actor] = {}
        self._pending_links: set[tuple] = set()

    def _close_logs(self):
        self.audit_fh.close()

    def _get_or_create_source(self) -> Source:
        description = f"Hub actor extraction (rule-based) from {SOURCE_FILE}"
        existing = self.session.execute(
            select(Source).where(Source.description == description)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        source = Source(
            source_id=uuid.uuid4(),
            source_type="ai_inference",
            url=None,
            retrieved_at=datetime.now(),
            description=description,
            trust_tier="candidate",
        )
        self.session.add(source)
        self.session.flush()
        return source

    def _find_hub_by_name(self, name: str) -> Optional[Hub]:
        slug = slugify(name)
        return self.session.execute(
            select(Hub).where(Hub.slug == slug)
        ).scalar_one_or_none()

    def _get_or_create_actor(self, name: str, source: Source) -> tuple[Actor, bool]:
        """Returns (actor, was_created).
        
        Slug is the single source of truth for actor identity. Two names that
        produce the same slug are the same actor.
        """
        slug = slugify(name)

        # In-memory cache check (fastest)
        if slug in self._actor_cache:
            return (self._actor_cache[slug], False)

        # Database lookup by slug (cheap because slug is indexed and unique)
        existing = self.session.execute(
            select(Actor).where(Actor.slug == slug)
        ).scalar_one_or_none()
        if existing is not None:
            self._actor_cache[slug] = existing
            return (existing, False)

        # Create new
        actor = Actor(
            actor_id=uuid.uuid4(),
            name=name,
            slug=slug,
            actor_type=classify_actor_type(name),
            actor_type_raw=None,
            description=None,
            website=None,
            location_city=None,
            state=None,
            country=None,
            source_id=source.source_id,
            verification_status="needs_review",
            confidence=0.5,
        )
        self.session.add(actor)
        self.session.flush()
        self._actor_cache[slug] = actor
        return (actor, True)

    def _link_hub_actor(self, hub: Hub, actor: Actor) -> bool:
        """Returns True if a new link was created, False if it already existed.
        
        Checks both the database AND the pending session for existing links, to
        handle the case where the same actor appears in both narrative columns
        of the same hub.
        """
        link_key = (hub.hub_id, actor.actor_id)
        
        # Track links already added in this run, to prevent within-transaction duplicates
        if link_key in self._pending_links:
            return False
        
        # Check the database for an existing link (from prior runs)
        existing = self.session.execute(
            select(HubActor).where(
                HubActor.hub_id == hub.hub_id,
                HubActor.actor_id == actor.actor_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._pending_links.add(link_key)
            return False

        link = HubActor(
            hub_id=hub.hub_id,
            actor_id=actor.actor_id,
            relationship_type="member",
            is_primary=False,
        )
        self.session.add(link)
        self._pending_links.add(link_key)
        return True
    
    def _process_candidates(self, hub: Hub, candidates: list[str],
                            source_column: str, source: Source):
        for candidate in candidates:
            if not looks_like_organization(candidate):
                self.stats.candidates_rejected += 1
                self.audit_writer.writerow(
                    [hub.name, source_column, candidate, "rejected",
                     "did not pass organization filter"]
                )
                continue

            actor, created = self._get_or_create_actor(candidate, source)
            if created:
                self.stats.actors_created += 1
            else:
                self.stats.actors_existing += 1

            link_created = self._link_hub_actor(hub, actor)
            if link_created:
                self.stats.links_created += 1
                verdict = "linked_new" if created else "linked_existing_actor"
            else:
                self.stats.links_existing += 1
                verdict = "already_linked"

            self.audit_writer.writerow(
                [hub.name, source_column, candidate, verdict, str(actor.actor_id)]
            )

    def run(self) -> ExtractionStats:
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_path}")

        logger.info("Opening %s", self.source_path)
        wb = openpyxl.load_workbook(self.source_path, read_only=True, data_only=True)
        try:
            ws = wb[SHEET_NAME]
            source = self._get_or_create_source()

            for row_idx, row in enumerate(
                ws.iter_rows(min_row=DATA_STARTS_AT_ROW, values_only=True),
                start=DATA_STARTS_AT_ROW,
            ):
                row = row[:16]
                hub_name_raw = row[COL_NAME]
                composition_raw = row[COL_COMPOSITION]
                programs_raw = row[COL_PROGRAMS]

                # Skip section headers and empty rows
                if not hub_name_raw:
                    continue
                if composition_raw is None and programs_raw is None:
                    continue
                if hub_name_raw and not any(v for v in row[1:]):
                    # section header
                    continue

                # Find the hub in the database
                hub = self._find_hub_by_name(str(hub_name_raw).strip())
                if hub is None:
                    logger.warning("Hub not found in DB: %s", hub_name_raw)
                    continue

                self.stats.hubs_processed += 1

                # Process composition
                if composition_raw:
                    candidates = split_narrative(str(composition_raw))
                    self._process_candidates(hub, candidates, "composition", source)

                # Process programs
                if programs_raw:
                    candidates = split_narrative(str(programs_raw))
                    self._process_candidates(hub, candidates, "programs_and_labs", source)

            self.session.commit()
        finally:
            wb.close()
            self._close_logs()

        return self.stats