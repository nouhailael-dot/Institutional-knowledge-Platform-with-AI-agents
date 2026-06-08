"""
Translator for UM6P_Dashboard_v8.xlsx
→ event + event_scoring + event_sector tables.

Processes two sheets:
- Event Mapping (13 events): full scoring data populates event_scoring,
  per-sector Yes/No becomes event_sector tags.
- UN Key Events (16 events): event records only, no scoring (this sheet
  is a higher-level summary without the scoring rubric).

Idempotent: events matched by (name, organizer slug) composite. Existing
events updated, not duplicated. Cross-references the UN events already
imported by un_mapping translator.
"""

from __future__ import annotations

import csv
import logging
import re
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    Actor, Event, EventScoring, EventSector, Sector, Source,
)
from src.etl.common.text_cleaning import clean_text, slugify


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

SOURCE_FILE = "data/raw/UM6P_Dashboard_v8.xlsx"
SHEET_SCORED = "Event Mapping"
SHEET_NY_EVENTS = "UN Key Events"
AUDIT_LOG = "data/interim/um6p_dashboard_audit.csv"
FAILURE_LOG = "data/interim/um6p_dashboard_failures.csv"

# Event Mapping sheet column indices (0-indexed)
EM_NAME = 0
EM_DESCRIPTION = 1
EM_LOCATION = 2
EM_DATE = 3
EM_FREQUENCY = 4
EM_ORGANIZER = 5
EM_WEBSITE = 6
EM_THEMATIC = 7
EM_SECTOR_AGRI = 8
EM_SECTOR_WATER = 9
EM_SECTOR_HEALTH = 10
EM_SECTOR_AI = 11
EM_SECTOR_ENERGY = 12
EM_SECTOR_MINING = 13
EM_SECTOR_CHEM = 14
EM_VALUE_NARRATIVE = 15
EM_POSITIONING_INTERIM = 16
EM_LONGEVITY_DESC = 17
EM_RECOGNITION_DESC = 18
EM_SCALE_DESC = 19
EM_AUDIENCE_DESC = 20
EM_ORGANIZER_DESC = 21
EM_GEOGRAPHY_DESC = 22
EM_LONGEVITY_SCORE = 23
EM_RECOGNITION_SCORE = 24
EM_SCALE_SCORE = 25
EM_AUDIENCE_SCORE = 26
EM_ORGANIZER_SCORE = 27
EM_GEOGRAPHY_SCORE = 28
EM_TOTAL = 29
EM_TIER = 30
EM_POSITIONING_FINAL = 31

EM_DATA_STARTS_AT = 5  # rows 1-2 title, 3 section headers, 4 column names

# UN Key Events sheet column indices (0-indexed)
NY_NAME = 0
NY_CATEGORY = 1
NY_DESCRIPTION = 2
NY_LOCATION = 3
NY_DATE = 4
NY_ORGANIZER = 5
NY_WEBSITE = 6
NY_THEMATIC = 7
NY_VALUE = 8

NY_DATA_STARTS_AT = 6  # skip title rows + section header

# Map sector column → sector code
SECTOR_COLUMNS = {
    EM_SECTOR_AGRI: "AGRI",
    EM_SECTOR_WATER: "WATER",
    EM_SECTOR_HEALTH: "HEALTH",
    EM_SECTOR_AI: "AI",
    EM_SECTOR_ENERGY: "ENERGY",
    EM_SECTOR_MINING: "MINING",
    EM_SECTOR_CHEM: "CHEM",
}

SCORING_METHODOLOGY_VERSION = "v8"


# ============================================================
# RUN STATS
# ============================================================

@dataclass
class RunStats:
    events_inserted: int = 0
    events_matched_existing: int = 0
    events_updated: int = 0
    scoring_inserted: int = 0
    scoring_updated: int = 0
    sector_tags_created: int = 0
    sector_tags_existing: int = 0
    ny_events_inserted: int = 0
    ny_events_skipped: int = 0
    rows_failed: int = 0
    skipped_section_headers: int = 0

    def summary(self) -> str:
        return (
            f"  Event Mapping sheet:\n"
            f"    Events new / matched / updated:    {self.events_inserted} / {self.events_matched_existing} / {self.events_updated}\n"
            f"    Scoring rows inserted / updated:   {self.scoring_inserted} / {self.scoring_updated}\n"
            f"    Sector tags new / existing:        {self.sector_tags_created} / {self.sector_tags_existing}\n"
            f"  UN Key Events sheet:\n"
            f"    Events inserted / skipped:         {self.ny_events_inserted} / {self.ny_events_skipped}\n"
            f"  Section headers skipped:             {self.skipped_section_headers}\n"
            f"  Rows failed:                         {self.rows_failed}"
        )


# ============================================================
# HELPERS
# ============================================================

def parse_yes_no(value: object) -> Optional[bool]:
    """Return True for Yes-like values, False for No-like, None otherwise."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return True
    if s in ("no", "n", "false", "0"):
        return False
    return None


def parse_score(value: object) -> Optional[int]:
    """Score must be 1, 2, or 3."""
    if value is None:
        return None
    try:
        n = int(float(str(value).strip()))
        return n if 1 <= n <= 3 else None
    except (ValueError, TypeError):
        return None


def parse_total(value: object) -> Optional[int]:
    """Total is 6-18."""
    if value is None:
        return None
    try:
        n = int(float(str(value).strip()))
        return n if 6 <= n <= 18 else None
    except (ValueError, TypeError):
        return None


def normalize_tier(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Returns (normalized_tier, raw_tier).
    Raw values look like '🟢 Tier 1 — High-Influence Events'."""
    if not raw:
        return (None, None)
    raw_clean = str(raw).strip()
    match = re.search(r"tier\s*(\d)", raw_clean.lower())
    if match:
        return (f"tier_{match.group(1)}", raw_clean)
    return (None, raw_clean)


def is_section_header_row(row: list) -> bool:
    """A section header has content only in col 0 (e.g., 'KEY ANNUAL UNITED NATIONS EVENTS — New York')."""
    if not row or not row[0]:
        return False
    has_first = bool(str(row[0]).strip())
    has_others = any(v is not None and str(v).strip() != "" for v in row[1:])
    return has_first and not has_others


# ============================================================
# TRANSLATOR
# ============================================================

class Um6pDashboardTranslator:

    def __init__(self, project_root: Path, session: Session):
        self.project_root = project_root
        self.session = session
        self.source_path = project_root / SOURCE_FILE
        self.stats = RunStats()

        # Logs
        self.audit_fh = self._open_log(AUDIT_LOG,
            ["sheet", "row", "verdict", "event_name", "notes"])
        self.failure_fh = self._open_log(FAILURE_LOG,
            ["sheet", "row", "exception", "raw_summary"])

        # In-run caches
        self._event_cache: dict[tuple, Event] = {}
        self._sector_id_cache: dict[str, uuid.UUID] = {}

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
        for fh, _ in (self.audit_fh, self.failure_fh):
            fh.close()

    # ----------------------------------------------------------
    # SOURCE + SECTOR LOOKUPS
    # ----------------------------------------------------------

    def _get_or_create_source(self) -> Source:
        desc = f"UM6P Dashboard v8 ingested from {SOURCE_FILE}"
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

    def _get_sector_id(self, code: str) -> Optional[uuid.UUID]:
        if code in self._sector_id_cache:
            return self._sector_id_cache[code]
        sector = self.session.execute(
            select(Sector).where(Sector.code == code)
        ).scalar_one_or_none()
        if sector:
            self._sector_id_cache[code] = sector.sector_id
            return sector.sector_id
        return None

    # ----------------------------------------------------------
    # EVENT UPSERT
    # ----------------------------------------------------------

    def _find_host_actor(self, organizer_text: Optional[str]) -> Optional[Actor]:
        """Try to match the organizer string to an existing actor."""
        if not organizer_text:
            return None
        # Take the first organization mentioned (often "Org A / Org B" or "Org A, Org B")
        first = re.split(r"[/,]", organizer_text)[0].strip()
        if not first:
            return None
        slug = slugify(first)
        return self.session.execute(
            select(Actor).where(Actor.slug == slug)
        ).scalar_one_or_none()

    def _upsert_event(self, name: str, host: Optional[Actor], location: Optional[str],
                      description: Optional[str], date_text: Optional[str],
                      website: Optional[str], frequency: Optional[str],
                      sponsoring_orgs: Optional[str], source: Source,
                      event_type: str = "Strategic event") -> tuple[Event, str]:
        """Returns (event, verdict)."""
        # Idempotency by (name, host_actor_id) — host can be NULL
        host_id = host.actor_id if host else None
        cache_key = (name.lower(), str(host_id) if host_id else None)
        if cache_key in self._event_cache:
            return (self._event_cache[cache_key], "cached")

        if host_id is not None:
            existing = self.session.execute(
                select(Event).where(
                    Event.name == name,
                    Event.host_actor_id == host_id,
                )
            ).scalar_one_or_none()
        else:
            existing = self.session.execute(
                select(Event).where(
                    Event.name == name,
                    Event.host_actor_id.is_(None),
                )
            ).scalar_one_or_none()

        if existing:
            # Enrich missing fields
            existing.event_type = existing.event_type or event_type
            existing.location = existing.location or location
            existing.website = existing.website or website
            existing.recurring_pattern = existing.recurring_pattern or frequency
            existing.sponsoring_orgs = existing.sponsoring_orgs or sponsoring_orgs
            self._event_cache[cache_key] = existing
            self.stats.events_matched_existing += 1
            return (existing, "matched_existing")

        ev = Event(
            event_id=uuid.uuid4(),
            name=name,
            event_type=event_type,
            location=location,
            website=website,
            recurring_pattern=frequency,
            sponsoring_orgs=sponsoring_orgs,
            host_actor_id=host_id,
            source_id=source.source_id,
        )
        self.session.add(ev)
        self.session.flush()
        self._event_cache[cache_key] = ev
        self.stats.events_inserted += 1
        return (ev, "inserted")

    def _upsert_scoring(self, event: Event, row: list, source: Source):
        existing = self.session.execute(
            select(EventScoring).where(EventScoring.event_id == event.event_id)
        ).scalar_one_or_none()

        tier_norm, tier_raw = normalize_tier(clean_text(row[EM_TIER]))

        fields = {
            "longevity_description": clean_text(row[EM_LONGEVITY_DESC]),
            "recognition_description": clean_text(row[EM_RECOGNITION_DESC]),
            "scale_description": clean_text(row[EM_SCALE_DESC]),
            "audience_profile_description": clean_text(row[EM_AUDIENCE_DESC]),
            "organizer_credibility_description": clean_text(row[EM_ORGANIZER_DESC]),
            "geographic_reach_description": clean_text(row[EM_GEOGRAPHY_DESC]),
            "longevity_score": parse_score(row[EM_LONGEVITY_SCORE]),
            "recognition_score": parse_score(row[EM_RECOGNITION_SCORE]),
            "scale_score": parse_score(row[EM_SCALE_SCORE]),
            "audience_profile_score": parse_score(row[EM_AUDIENCE_SCORE]),
            "organizer_profile_score": parse_score(row[EM_ORGANIZER_SCORE]),
            "geographic_reach_score": parse_score(row[EM_GEOGRAPHY_SCORE]),
            "total_score": parse_total(row[EM_TOTAL]),
            "tier": tier_norm,
            "tier_raw": tier_raw,
            "strategic_value_narrative": clean_text(row[EM_VALUE_NARRATIVE]),
            "strategic_positioning": clean_text(row[EM_POSITIONING_FINAL]) or clean_text(row[EM_POSITIONING_INTERIM]),
            "scoring_methodology_version": SCORING_METHODOLOGY_VERSION,
            "scored_at": datetime.now(),
        }

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            self.stats.scoring_updated += 1
        else:
            scoring = EventScoring(
                event_scoring_id=uuid.uuid4(),
                event_id=event.event_id,
                source_id=source.source_id,
                **fields,
            )
            self.session.add(scoring)
            self.stats.scoring_inserted += 1

    def _upsert_event_sector(self, event: Event, sector_code: str, source: Source):
        sector_id = self._get_sector_id(sector_code)
        if not sector_id:
            logger.warning("Sector code %s not found in DB; skipping tag", sector_code)
            return
        existing = self.session.execute(
            select(EventSector).where(
                EventSector.event_id == event.event_id,
                EventSector.sector_id == sector_id,
            )
        ).scalar_one_or_none()
        if existing:
            self.stats.sector_tags_existing += 1
            return
        tag = EventSector(event_id=event.event_id, sector_id=sector_id)
        self.session.add(tag)
        self.stats.sector_tags_created += 1

    # ----------------------------------------------------------
    # SHEET 1: EVENT MAPPING (the scored events)
    # ----------------------------------------------------------

    def _process_em_row(self, row_idx: int, row: list, source: Source):
        name = clean_text(row[EM_NAME])
        if not name:
            return

        organizer_text = clean_text(row[EM_ORGANIZER])
        host = self._find_host_actor(organizer_text)

        event, verdict = self._upsert_event(
            name=name,
            host=host,
            location=clean_text(row[EM_LOCATION]),
            description=clean_text(row[EM_DESCRIPTION]),
            date_text=clean_text(row[EM_DATE]),
            website=clean_text(row[EM_WEBSITE]),
            frequency=clean_text(row[EM_FREQUENCY]),
            sponsoring_orgs=organizer_text,
            source=source,
            event_type="Strategic event (v8)",
        )

        # Scoring sidecar
        self._upsert_scoring(event, row, source)

        # Sector tags (Yes/No → only "Yes" creates a tag)
        for col_idx, sector_code in SECTOR_COLUMNS.items():
            if parse_yes_no(row[col_idx]) is True:
                self._upsert_event_sector(event, sector_code, source)

        host_name = host.name if host else "(no host match)"
        self._log(self.audit_fh, "event_mapping", row_idx, verdict, name,
                  f"host={host_name}")

    def _run_event_mapping(self, ws, source: Source):
        for row_idx, row in enumerate(
            ws.iter_rows(min_row=EM_DATA_STARTS_AT, values_only=True),
            start=EM_DATA_STARTS_AT,
        ):
            row = list(row[:32])
            while len(row) < 32:
                row.append(None)
            try:
                self._process_em_row(row_idx, row, source)
            except Exception as e:
                self.stats.rows_failed += 1
                raw_summary = str([str(v)[:30] if v else "" for v in row[:5]])
                self._log(self.failure_fh, "event_mapping", row_idx, str(e), raw_summary)
                logger.warning("Event Mapping row %d failed: %s", row_idx, e)

    # ----------------------------------------------------------
    # SHEET 2: UN KEY EVENTS (event records only)
    # ----------------------------------------------------------

    def _process_ny_row(self, row_idx: int, row: list, source: Source):
        # Skip section headers ("KEY ANNUAL UNITED NATIONS EVENTS — New York" etc.)
        if is_section_header_row(row):
            self.stats.skipped_section_headers += 1
            return

        name = clean_text(row[NY_NAME])
        if not name:
            return

        organizer = clean_text(row[NY_ORGANIZER])
        host = self._find_host_actor(organizer)

        ev, verdict = self._upsert_event(
            name=name,
            host=host,
            location=clean_text(row[NY_LOCATION]),
            description=clean_text(row[NY_DESCRIPTION]),
            date_text=clean_text(row[NY_DATE]),
            website=clean_text(row[NY_WEBSITE]),
            frequency=None,
            sponsoring_orgs=organizer,
            source=source,
            event_type="UN strategic event",
        )

        if verdict == "inserted":
            self.stats.ny_events_inserted += 1
        else:
            self.stats.ny_events_skipped += 1

        self._log(self.audit_fh, "un_key_events", row_idx, verdict, name,
                  f"host={host.name if host else 'none'}")

    def _run_ny_events(self, ws, source: Source):
        for row_idx, row in enumerate(
            ws.iter_rows(min_row=NY_DATA_STARTS_AT, values_only=True),
            start=NY_DATA_STARTS_AT,
        ):
            row = list(row[:9])
            while len(row) < 9:
                row.append(None)
            try:
                self._process_ny_row(row_idx, row, source)
            except Exception as e:
                self.stats.rows_failed += 1
                raw_summary = str([str(v)[:30] if v else "" for v in row[:4]])
                self._log(self.failure_fh, "un_key_events", row_idx, str(e), raw_summary)
                logger.warning("UN Key Events row %d failed: %s", row_idx, e)

    # ----------------------------------------------------------
    # ENTRY POINT
    # ----------------------------------------------------------

    def run(self) -> RunStats:
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_path}")

        logger.info("Opening %s", self.source_path)
        wb = openpyxl.load_workbook(self.source_path, read_only=True, data_only=True)
        try:
            if SHEET_SCORED not in wb.sheetnames:
                raise ValueError(f"Sheet '{SHEET_SCORED}' not found.")
            if SHEET_NY_EVENTS not in wb.sheetnames:
                raise ValueError(f"Sheet '{SHEET_NY_EVENTS}' not found.")

            source = self._get_or_create_source()

            logger.info("Processing Event Mapping sheet (scored events)")
            self._run_event_mapping(wb[SHEET_SCORED], source)

            self.session.flush()

            logger.info("Processing UN Key Events sheet (NY-focused events)")
            self._run_ny_events(wb[SHEET_NY_EVENTS], source)

            self.session.commit()
        finally:
            wb.close()
            self._close_logs()

        return self.stats