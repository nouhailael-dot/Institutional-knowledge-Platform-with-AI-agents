"""
Translator for NutriCrops_Ecosystem_Mapping_Template.xlsx
→ challenge (one row) + actor (~144 rows, deduplicated by slug) + actor_relevance (~144 rows)

Per ADR-003:
- Actor Category contains 12 free-text values beyond the 4 official dropdown values.
  Mapped through data/processed/actor_type_mapping.csv to the actor_type enum.
- Cols 13, 14, 15 are ghost columns from template damage. Ignored entirely.
- Cols 12 (Lifecycle) and 18 (Maturity Risk) have partial Yes/No corruption.
  Anything outside the controlled vocabulary is quarantined to NULL with a CSV log.
- TRL field has the typo "TRL 4-5 Lab  or Pilot" (double space). Normalized.

Cross-references existing actors by slug. If an actor from prior translators
(hub extraction, UN mapping) already exists, this translator reuses the actor_id
and only adds an actor_relevance row — not a duplicate actor.
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

from src.db.models import Actor, ActorRelevance, Challenge, Source
from src.etl.common.text_cleaning import clean_text, slugify


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

SOURCE_FILE = "data/raw/NutriCrops_Ecosystem_Mapping_Template.xlsx"
SHEET_DATA = "NutriCrops Ecosystem Map"
SHEET_LISTS = "Lists"
ACTOR_TYPE_MAPPING_CSV = "data/processed/actor_type_mapping.csv"

AUDIT_LOG = "data/interim/nutricrops_audit.csv"
FAILURE_LOG = "data/interim/nutricrops_failures.csv"
QUARANTINE_LOG = "data/interim/nutricrops_quarantine.csv"

# Column indices (0-indexed) — verified by direct file inspection
COL_NAME = 0
COL_CATEGORY = 1
COL_DESCRIPTION = 2
COL_LOCATION = 3
COL_WEBSITE = 4
COL_TECH_FOCUS = 5
COL_TECH_APPROACH = 6
COL_RELEVANCE_PHOSPHOGYPSUM = 7
COL_CURRENT_ACTIVITIES = 8
COL_TECH_IP_NOTES = 9
COL_TRL = 10
COL_LIFECYCLE = 11
# Cols 12, 13, 14 (0-indexed) — ghost columns. Ignored.
COL_COLLABORATION = 15
COL_RELEVANCE_SCORE = 16
COL_MATURITY_RISK = 17
COL_CONSTRAINTS = 18
COL_WHY_VALUABLE = 19
COL_SOURCE_LINKS = 20
COL_ANALYST_NOTES = 21
COL_FUNDINGS = 22

DATA_STARTS_AT_ROW = 2  # row 1 is header

# The NutriCrops challenge itself — created once
CHALLENGE_NAME = "NutriCrops Phosphogypsum"
CHALLENGE_DESCRIPTION = (
    "OCP-sponsored initiative to identify and engage U.S. and international actors "
    "with relevance to phosphogypsum management, valorization, and downstream uses. "
    "Spans mineral processing, chemistry, agriculture, and environmental remediation."
)
CHALLENGE_SPONSOR = "OCP Group"
CHALLENGE_TARGET_SECTORS = ["AGRI", "CHEM", "MINING"]


# ============================================================
# CONTROLLED VOCABULARY
# Loaded from the Lists sheet at runtime, but defaults below match ADR-006.
# ============================================================

OFFICIAL_LIFECYCLE_VALUES = {
    "Discovery", "Validation", "Scale-Up", "Deployment", "Multiple Roles",
}
OFFICIAL_MATURITY_VALUES = {"Low", "Medium", "High"}

# Yes/No tokens we explicitly quarantine when found in Lifecycle/Maturity cells
CORRUPTION_TOKENS = {"yes", "no", "y", "n", "true", "false"}


@dataclass
class RunStats:
    challenge_created: bool = False
    actors_inserted: int = 0
    actors_reused_from_prior_runs: int = 0
    actors_enriched: int = 0
    relevance_inserted: int = 0
    relevance_updated: int = 0
    lifecycle_quarantined: int = 0
    maturity_quarantined: int = 0
    actor_type_unmapped: list[str] = field(default_factory=list)
    rows_failed: int = 0

    def summary(self) -> str:
        lines = [
            f"  Challenge:                       {'created' if self.challenge_created else 'reused'}",
            f"  Actors inserted (new to DB):     {self.actors_inserted}",
            f"  Actors reused (already in DB):   {self.actors_reused_from_prior_runs}",
            f"  Actors enriched with NutriCrops: {self.actors_enriched}",
            f"  ActorRelevance inserted:         {self.relevance_inserted}",
            f"  ActorRelevance updated:          {self.relevance_updated}",
            f"  Lifecycle values quarantined:    {self.lifecycle_quarantined}",
            f"  Maturity values quarantined:     {self.maturity_quarantined}",
            f"  Rows failed:                     {self.rows_failed}",
        ]
        if self.actor_type_unmapped:
            lines.append(f"\n  Actor category values not in mapping (needs review):")
            for v in set(self.actor_type_unmapped):
                lines.append(f"    - {v}")
        return "\n".join(lines)


# ============================================================
# HELPERS
# ============================================================

def parse_trl(value: object) -> Optional[int]:
    """Normalize TRL string into integer (1-9).

    Examples:
        'TRL 4-5 Lab  or Pilot' -> 4   (double-space tolerated)
        'TRL 1-3 Early Research' -> 1
        'TRL 8-9 Commercial' -> 8
        None / '' / 'N/A' -> None
    """
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    if not s:
        return None
    m = re.match(r"^TRL\s+(\d+)", s, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 9 else None
    # Sometimes the cell just contains a bare integer "5"
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 9 else None
    return None


def parse_relevance_score(value: object) -> Optional[float]:
    """Relevance Score is 1-5. Return as float for the NUMERIC(3,2) column."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        n = float(s)
        if 1 <= n <= 5:
            return n
    except ValueError:
        pass
    return None


def validate_lifecycle(value: object) -> tuple[Optional[str], Optional[str]]:
    """Return (clean_value, reason_for_quarantine).
    clean_value is the value to store; reason is non-None when we quarantined."""
    if value is None:
        return (None, None)
    s = str(value).strip()
    if not s:
        return (None, None)

    # Direct match against the official vocabulary
    for official in OFFICIAL_LIFECYCLE_VALUES:
        if s.lower() == official.lower():
            return (official, None)

    # Recognized corruption — quarantine
    if s.lower() in CORRUPTION_TOKENS:
        return (None, f"corruption token '{s}'")

    # Free text containing a lifecycle keyword — preserve as 'Multiple Roles'
    # (e.g., 'Discovery / validation / pilot design')
    if any(off.lower() in s.lower() for off in OFFICIAL_LIFECYCLE_VALUES):
        return ("Multiple Roles", None)

    # Anything else — quarantine
    return (None, f"unrecognized lifecycle value '{s[:80]}'")


def validate_maturity(value: object) -> tuple[Optional[str], Optional[str]]:
    if value is None:
        return (None, None)
    s = str(value).strip()
    if not s:
        return (None, None)

    for official in OFFICIAL_MATURITY_VALUES:
        if s.lower() == official.lower():
            return (official, None)

    if s.lower() in CORRUPTION_TOKENS:
        return (None, f"corruption token '{s}'")

    # Soft variants
    if "low" in s.lower() and "med" in s.lower():
        return ("Medium", None)  # 'Low-to-Medium' rounds up
    if "low" in s.lower():
        return ("Low", None)
    if "high" in s.lower():
        return ("High", None)
    if "med" in s.lower():
        return ("Medium", None)

    return (None, f"unrecognized maturity value '{s[:80]}'")


def load_actor_type_mapping(csv_path: Path) -> dict[str, str]:
    """Load the raw_value → canonical_enum mapping from CSV.
    Keys are lowercased + whitespace-collapsed for tolerant matching."""
    mapping = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get("raw_value", "").strip()
            enum_val = row.get("canonical_enum", "").strip()
            if raw and enum_val:
                key = re.sub(r"\s+", " ", raw).strip().lower()
                mapping[key] = enum_val
    return mapping


def map_actor_type(raw: Optional[str], mapping: dict[str, str]) -> tuple[str, Optional[str]]:
    """Returns (canonical_enum, unmapped_warning_or_none)."""
    if not raw:
        return ("other", None)
    key = re.sub(r"\s+", " ", raw).strip().lower()
    if key in mapping:
        return (mapping[key], None)
    return ("other", raw)


# ============================================================
# TRANSLATOR
# ============================================================

class NutriCropsTranslator:

    def __init__(self, project_root: Path, session: Session):
        self.project_root = project_root
        self.session = session
        self.source_path = project_root / SOURCE_FILE
        self.stats = RunStats()

        # Load actor type mapping
        mapping_path = project_root / ACTOR_TYPE_MAPPING_CSV
        if not mapping_path.exists():
            raise FileNotFoundError(
                f"Actor type mapping not found at {mapping_path}. "
                f"It must be present before running this translator."
            )
        self.actor_type_mapping = load_actor_type_mapping(mapping_path)

        # Open log files
        self.audit_fh = self._open_log(AUDIT_LOG,
            ["row", "verdict", "actor_name", "actor_id", "notes"])
        self.failure_fh = self._open_log(FAILURE_LOG,
            ["row", "actor_name", "exception", "raw_summary"])
        self.quarantine_fh = self._open_log(QUARANTINE_LOG,
            ["row", "actor_name", "field", "raw_value", "reason"])

        self._actor_cache: dict[str, Actor] = {}

    def _open_log(self, rel_path: str, header: list[str]):
        path = self.project_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "w", newline="", encoding="utf-8")
        writer = csv.writer(fh)
        writer.writerow(header)
        return (fh, writer)

    def _log(self, log_pair, *cells):
        log_pair[1].writerow(cells)

    def _close_logs(self):
        for fh, _ in (self.audit_fh, self.failure_fh, self.quarantine_fh):
            fh.close()

    # ----------------------------------------------------------
    # SOURCE + CHALLENGE
    # ----------------------------------------------------------

    def _get_or_create_source(self) -> Source:
        desc = f"NutriCrops Ecosystem Mapping ingested from {SOURCE_FILE}"
        existing = self.session.execute(
            select(Source).where(Source.description == desc)
        ).scalar_one_or_none()
        if existing:
            return existing
        s = Source(
            source_id=uuid.uuid4(),
            source_type="spreadsheet",
            url=None,
            retrieved_at=datetime.now(),
            description=desc,
            trust_tier="verified",
        )
        self.session.add(s)
        self.session.flush()
        return s

    def _get_or_create_challenge(self, source: Source) -> Challenge:
        existing = self.session.execute(
            select(Challenge).where(Challenge.name == CHALLENGE_NAME)
        ).scalar_one_or_none()
        if existing:
            return existing
        challenge = Challenge(
            challenge_id=uuid.uuid4(),
            name=CHALLENGE_NAME,
            sponsoring_org=CHALLENGE_SPONSOR,
            description=CHALLENGE_DESCRIPTION,
            target_sectors=CHALLENGE_TARGET_SECTORS,
            target_technologies=[
                "phosphogypsum_management", "phosphogypsum_valorization",
                "radium_uranium_removal", "rare_earth_recovery",
                "agricultural_amendments", "construction_materials",
            ],
            created_date=datetime.now().date(),
        )
        self.session.add(challenge)
        self.session.flush()
        self.stats.challenge_created = True
        return challenge

    # ----------------------------------------------------------
    # ROW PROCESSING
    # ----------------------------------------------------------

    @staticmethod
    def _parse_location(loc: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Parse a free-text location into (city, state, country).

        NutriCrops cells can contain multi-line entries with multiple addresses
        (e.g., 'Parent Company HQ (Xylem): Washington, DC, USA\\n\\nOperational Footprint: ...').
        We only take the FIRST line and truncate each part to fit the schema's varchar limits.
        """
        if not loc:
            return (None, None, None)

        # Only use the first line — discard secondary addresses and free-text notes
        first_line = loc.split("\n")[0].strip()
        if not first_line:
            return (None, None, None)

        parts = [p.strip() for p in first_line.split(",") if p.strip()]

        def trunc(s: Optional[str], limit: int) -> Optional[str]:
            if not s:
                return None
            return s[:limit] if len(s) > limit else s

        if len(parts) == 1:
            return (trunc(parts[0], 120), None, None)
        if len(parts) == 2:
            return (trunc(parts[0], 120), None, trunc(parts[1], 80))
        return (trunc(parts[0], 120), trunc(parts[1], 80), trunc(parts[-1], 80))

    def _upsert_actor(self, name: str, row: list, source: Source) -> tuple[Actor, str]:
        """Returns (actor, verdict). verdict is one of:
           'inserted_new', 'reused_existing', 'enriched_existing'."""
        slug = slugify(name)

        # Check in-run cache first
        if slug in self._actor_cache:
            return (self._actor_cache[slug], "reused_existing")

        existing = self.session.execute(
            select(Actor).where(Actor.slug == slug)
        ).scalar_one_or_none()

        category_raw = clean_text(row[COL_CATEGORY])
        actor_type, unmapped = map_actor_type(category_raw, self.actor_type_mapping)
        if unmapped:
            self.stats.actor_type_unmapped.append(unmapped)

        description = clean_text(row[COL_DESCRIPTION])
        website = clean_text(row[COL_WEBSITE])
        location = clean_text(row[COL_LOCATION])
        city, state, country = self._parse_location(location)

        tech_focus = clean_text(row[COL_TECH_FOCUS])
        tech_approach = clean_text(row[COL_TECH_APPROACH])
        current_activities = clean_text(row[COL_CURRENT_ACTIVITIES])
        tech_ip = clean_text(row[COL_TECH_IP_NOTES])
        constraints = clean_text(row[COL_CONSTRAINTS])

        trl = parse_trl(row[COL_TRL])

        # Lifecycle for the actor (separate from relevance) — same validation
        lifecycle_clean, _ = validate_lifecycle(row[COL_LIFECYCLE])

        if existing:
            # Enrich the existing actor with NutriCrops-specific fields,
            # only overwriting where existing is null or where NutriCrops adds new info
            verdict = "enriched_existing"
            existing.actor_type = actor_type if existing.actor_type in (None, "other") else existing.actor_type
            existing.actor_type_raw = category_raw or existing.actor_type_raw
            existing.description = existing.description or description
            existing.website = existing.website or website
            existing.location_city = existing.location_city or city
            existing.state = existing.state or state
            existing.country = existing.country or country
            existing.primary_technical_focus = existing.primary_technical_focus or tech_focus
            existing.technical_approach = existing.technical_approach or tech_approach
            existing.current_activities = existing.current_activities or current_activities
            existing.technology_ip_notes = existing.technology_ip_notes or tech_ip
            existing.key_constraints = existing.key_constraints or constraints
            existing.estimated_trl = existing.estimated_trl or trl
            existing.primary_lifecycle_role = existing.primary_lifecycle_role or lifecycle_clean
            self._actor_cache[slug] = existing
            self.stats.actors_enriched += 1
            return (existing, verdict)

        # Brand new
        actor = Actor(
            actor_id=uuid.uuid4(),
            name=name,
            slug=slug,
            actor_type=actor_type,
            actor_type_raw=category_raw,
            description=description,
            website=website,
            location_city=city,
            state=state,
            country=country,
            primary_technical_focus=tech_focus,
            technical_approach=tech_approach,
            current_activities=current_activities,
            technology_ip_notes=tech_ip,
            key_constraints=constraints,
            estimated_trl=trl,
            primary_lifecycle_role=lifecycle_clean,
            source_id=source.source_id,
            verification_status="phase_1",
            confidence=1.0,
        )
        self.session.add(actor)
        self.session.flush()
        self._actor_cache[slug] = actor
        self.stats.actors_inserted += 1
        return (actor, "inserted_new")

    def _upsert_relevance(self, actor: Actor, challenge: Challenge,
                          row: list, source: Source, row_idx: int, name: str):
        # Validate lifecycle and maturity, with quarantine
        lifecycle_clean, lifecycle_quar = validate_lifecycle(row[COL_LIFECYCLE])
        if lifecycle_quar:
            self.stats.lifecycle_quarantined += 1
            self._log(self.quarantine_fh, row_idx, name, "primary_lifecycle",
                      str(row[COL_LIFECYCLE])[:120], lifecycle_quar)

        maturity_clean, maturity_quar = validate_maturity(row[COL_MATURITY_RISK])
        if maturity_quar:
            self.stats.maturity_quarantined += 1
            self._log(self.quarantine_fh, row_idx, name, "maturity_risk",
                      str(row[COL_MATURITY_RISK])[:120], maturity_quar)

        relevance_score = parse_relevance_score(row[COL_RELEVANCE_SCORE])
        # Normalize 1-5 to 0-1 by dividing by 5 (so the column is consistent
        # with other relevance scoring across the platform)
        normalized_score = relevance_score / 5.0 if relevance_score is not None else None

        existing = self.session.execute(
            select(ActorRelevance).where(
                ActorRelevance.actor_id == actor.actor_id,
                ActorRelevance.challenge_id == challenge.challenge_id,
            )
        ).scalar_one_or_none()

        fields = {
            "relevance_score": normalized_score,
            "maturity_risk": maturity_clean,
            "collaboration_orientation": (clean_text(row[COL_COLLABORATION]) or "")[:60] or None,
            "why_relevant": clean_text(row[COL_WHY_VALUABLE]),
            "current_evidence": clean_text(row[COL_CURRENT_ACTIVITIES]),
            "additional_validation_needed": clean_text(row[COL_ANALYST_NOTES]),
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.stats.relevance_updated += 1
        else:
            rel = ActorRelevance(
                actor_relevance_id=uuid.uuid4(),
                actor_id=actor.actor_id,
                challenge_id=challenge.challenge_id,
                source_id=source.source_id,
                **fields,
            )
            self.session.add(rel)
            self.stats.relevance_inserted += 1

    def _process_row(self, row_idx: int, row: list, challenge: Challenge, source: Source):
        name = clean_text(row[COL_NAME])
        if not name:
            return  # empty row, skip silently

        try:
            actor, actor_verdict = self._upsert_actor(name, row, source)
            self._upsert_relevance(actor, challenge, row, source, row_idx, name)

            if actor_verdict == "reused_existing":
                self.stats.actors_reused_from_prior_runs += 1

            self._log(self.audit_fh, row_idx, actor_verdict, name,
                      str(actor.actor_id), "")
        except Exception as e:
            self.stats.rows_failed += 1
            raw_summary = str([str(v)[:40] if v else "" for v in row[:6]])
            self._log(self.failure_fh, row_idx, name, str(e), raw_summary)
            logger.warning("Row %d (%s) failed: %s", row_idx, name, e)

    # ----------------------------------------------------------
    # ENTRY POINT
    # ----------------------------------------------------------

    def run(self) -> RunStats:
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_path}")

        logger.info("Opening %s", self.source_path)
        wb = openpyxl.load_workbook(self.source_path, read_only=True, data_only=True)
        try:
            if SHEET_DATA not in wb.sheetnames:
                raise ValueError(f"Sheet '{SHEET_DATA}' not found.")
            ws = wb[SHEET_DATA]
            source = self._get_or_create_source()
            challenge = self._get_or_create_challenge(source)

            for row_idx, row in enumerate(
                ws.iter_rows(min_row=DATA_STARTS_AT_ROW, values_only=True),
                start=DATA_STARTS_AT_ROW,
            ):
                # Truncate to 23 cols. Ignore everything beyond.
                row = list(row[:23])
                # Pad if short
                while len(row) < 23:
                    row.append(None)
                self._process_row(row_idx, row, challenge, source)

            self.session.commit()
        finally:
            wb.close()
            self._close_logs()

        return self.stats