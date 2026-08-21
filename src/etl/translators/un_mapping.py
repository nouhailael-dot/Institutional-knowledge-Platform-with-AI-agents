"""
Translator for UN_Mapping__FV.xlsx → actor + partnership_profile + organization_hierarchy + event tables.

Per ADR-007, UN entities are institutional actors with a partnership_profile sidecar.
Per ADR-002, hierarchical relationships go in organization_hierarchy.

The spreadsheet has two sheets:
- UN Mapping: 25 entities with 3-level hierarchy (▶ major → ▸ sub → entities)
- UN KEY EVENTS: 113 events using a continuation pattern (— means "same as previous org")

Idempotent: rows matched by actor.slug. Existing rows updated, not duplicated.
"""

from __future__ import annotations

import csv
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    Actor, Event, OrganizationHierarchy, PartnershipProfile, Source,
)
from src.etl.common.text_cleaning import (
    clean_text, slugify, parse_un_name_acronym,
)


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

SOURCE_FILE = "data/raw/UN_Mapping__FV.xlsx"
SHEET_MAIN = "UN Mapping"
SHEET_EVENTS = "UN KEY EVENTS "  # note the trailing space — that's how it is in the file
AUDIT_LOG = "data/interim/un_mapping_audit.csv"
FAILURE_LOG = "data/interim/un_mapping_failures.csv"

DATA_STARTS_AT_ROW = 3  # row 1 = title, row 2 = headers

# Column indices in the main UN Mapping sheet (0-indexed)
COL_NAME = 0
COL_CATEGORY = 1
COL_LOCATION = 2
COL_MAIN_FUNCTION = 3
COL_THEMATIC_FOCUS = 4
COL_STRATEGIC_PLAN = 5
COL_AFRICA_MANDATE = 6
COL_AFRICA_DETAILS = 7
COL_WHY_VALUABLE = 8
COL_BUDGET = 9
COL_PARTNERS_UNIS = 10
COL_UNI_PROGRAMMES = 11
COL_UNI_EXAMPLES = 12
COL_ENTRY_POINTS = 13
COL_FUNDING_DELIVERY = 14
COL_FUNDING_MECHANISMS = 15
COL_CONSTRAINTS = 16

# Map UN System Category → actor_type enum
CATEGORY_TO_TYPE = {
    "main committee of the unga": "un_committee",
    "fund & programme": "un_programme",
    "functional commission": "un_committee",
    "regional commission": "un_committee",
    "research & training institute": "un_programme",
    "research and training institute": "un_programme",
    "specialized agency": "un_agency",
    "department of the un secretariat": "un_secretariat",
    "office of the un secretariat": "un_secretariat",
    "world bank group member": "multilateral_development_bank",
}

# Major headers map to actor_type values for the synthetic parent rows we create
PARENT_TYPES = {
    "UNITED NATIONS GENERAL ASSEMBLY": "intergovernmental_organization",
    "ECONOMIC AND SOCIAL COUNCIL": "intergovernmental_organization",
    "SECRETARIAT": "un_secretariat",
    "SPECIALIZED AGENCIES": "intergovernmental_organization",
}


@dataclass
class RunStats:
    entities_inserted: int = 0
    entities_updated: int = 0
    profiles_inserted: int = 0
    profiles_updated: int = 0
    hierarchy_links_created: int = 0
    parents_created: int = 0
    events_inserted: int = 0
    events_skipped: int = 0
    headers_skipped: int = 0
    rows_failed: int = 0

    def summary(self) -> str:
        return (
            f"  UN Mapping sheet:\n"
            f"    Entities inserted/updated:   {self.entities_inserted} / {self.entities_updated}\n"
            f"    Profiles inserted/updated:   {self.profiles_inserted} / {self.profiles_updated}\n"
            f"    Parent rows created:         {self.parents_created}\n"
            f"    Hierarchy links created:     {self.hierarchy_links_created}\n"
            f"    Headers skipped:             {self.headers_skipped}\n"
            f"  UN KEY EVENTS sheet:\n"
            f"    Events inserted:             {self.events_inserted}\n"
            f"    Events skipped:              {self.events_skipped}\n"
            f"  Failures:                      {self.rows_failed}"
        )


def parse_yes_no(value: object) -> Optional[bool]:
    """Convert Yes/No/various variants into a bool. Anything else → None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return True
    if s in ("no", "n", "false", "0"):
        return False
    return None


def parse_event_string(event_text: str) -> tuple[Optional[date], str]:
    """Parse the leading date out of an event string like:
       '14–16 April 2026 | ECOSOC Youth Forum | UN HQ, New York'
    Returns (first_date_or_none, event_name).
    """
    parts = [p.strip() for p in event_text.split("|")]
    date_part = parts[0] if parts else ""
    name_part = parts[1] if len(parts) > 1 else event_text

    # Try to pull the first date out of the date_part
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", date_part)
    parsed_date = None
    if m:
        day, month_name, year = int(m.group(1)), m.group(2), int(m.group(3))
        try:
            parsed_date = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y").date()
        except ValueError:
            try:
                parsed_date = datetime.strptime(f"{day} {month_name} {year}", "%d %b %Y").date()
            except ValueError:
                parsed_date = None
    return (parsed_date, name_part[:255])


def category_to_actor_type(raw_category: Optional[str]) -> str:
    if not raw_category:
        return "intergovernmental_organization"
    normalized = re.sub(r"\s+", " ", raw_category).strip().lower()
    for key, val in CATEGORY_TO_TYPE.items():
        if key in normalized:
            return val
    return "intergovernmental_organization"


class UnMappingTranslator:

    def __init__(self, project_root: Path, session: Session):
        self.project_root = project_root
        self.session = session
        self.source_path = project_root / SOURCE_FILE
        self.stats = RunStats()

        log_path = project_root / AUDIT_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_fh = open(log_path, "w", newline="", encoding="utf-8")
        self.audit_writer = csv.writer(self.audit_fh)
        self.audit_writer.writerow(
            ["sheet", "row", "verdict", "name", "parent", "notes"]
        )

        fail_path = project_root / FAILURE_LOG
        self.failure_fh = open(fail_path, "w", newline="", encoding="utf-8")
        self.failure_writer = csv.writer(self.failure_fh)
        self.failure_writer.writerow(["sheet", "row", "exception", "raw"])

        # In-memory cache: organization slug → Actor
        self._actor_cache: dict[str, Actor] = {}
        # Track hierarchy links already created this run
        self._pending_hierarchy: set[tuple] = set()

    def _close_logs(self):
        self.audit_fh.close()
        self.failure_fh.close()

    # ----------------------------------------------------------
    # SOURCES
    # ----------------------------------------------------------

    def _get_or_create_source(self) -> Source:
        desc = f"UN Mapping spreadsheet ingested from {SOURCE_FILE}"
        existing = self.session.execute(
            select(Source).where(Source.description == desc)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        source = Source(
            source_id=uuid.uuid4(),
            source_type="spreadsheet",
            url=None,
            retrieved_at=datetime.now(),
            description=desc,
            trust_tier="verified",
        )
        self.session.add(source)
        self.session.flush()
        return source

    # ----------------------------------------------------------
    # ACTOR HELPERS
    # ----------------------------------------------------------

    def _get_or_create_actor(self, name: str, actor_type: str, source: Source,
                             location: Optional[str] = None,
                             description: Optional[str] = None) -> tuple[Actor, bool]:
        slug = slugify(name)
        if slug in self._actor_cache:
            return (self._actor_cache[slug], False)

        existing = self.session.execute(
            select(Actor).where(Actor.slug == slug)
        ).scalar_one_or_none()
        if existing is not None:
            self._actor_cache[slug] = existing
            # Allow updates
            if actor_type and actor_type != "other":
                existing.actor_type = actor_type
            if description:
                existing.description = description
            return (existing, False)

        city, state, country = self._parse_location(location)
        actor = Actor(
            actor_id=uuid.uuid4(),
            name=name,
            slug=slug,
            actor_type=actor_type,
            actor_type_raw=None,
            description=description,
            location_city=city,
            state=state,
            country=country,
            source_id=source.source_id,
            verification_status="phase_1",
            confidence=1.0,
        )
        self.session.add(actor)
        self.session.flush()
        self._actor_cache[slug] = actor
        return (actor, True)

    @staticmethod
    def _parse_location(loc: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not loc:
            return (None, None, None)
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if len(parts) == 1:
            return (parts[0], None, None)
        if len(parts) == 2:
            return (parts[0], None, parts[1])
        return (parts[0], parts[1], parts[-1])

    def _link_hierarchy(self, parent: Actor, child: Actor, rel_type: str) -> bool:
        key = (parent.actor_id, child.actor_id)
        if key in self._pending_hierarchy:
            return False
        existing = self.session.execute(
            select(OrganizationHierarchy).where(
                OrganizationHierarchy.parent_actor_id == parent.actor_id,
                OrganizationHierarchy.child_actor_id == child.actor_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._pending_hierarchy.add(key)
            return False
        link = OrganizationHierarchy(
            parent_actor_id=parent.actor_id,
            child_actor_id=child.actor_id,
            relationship_type=rel_type,
        )
        self.session.add(link)
        self._pending_hierarchy.add(key)
        return True

    # ----------------------------------------------------------
    # SHEET 1: UN MAPPING
    # ----------------------------------------------------------

    def _is_section_header(self, row: list) -> bool:
        """Header row: column 1 starts with ▶ or ▸. Other columns may or may not be filled."""
        if not row or row[0] is None:
            return False
        first = str(row[0]).strip()
        return first.startswith("▶") or first.startswith("▸")

    def _process_un_entity(self, row_idx: int, row: list, source: Source,
                          current_major: Optional[Actor],
                          current_sub: Optional[Actor]):
        raw_name = clean_text(row[COL_NAME])
        if not raw_name:
            return
        full_name, acronym = parse_un_name_acronym(raw_name)

        category = clean_text(row[COL_CATEGORY])
        actor_type = category_to_actor_type(category)
        location = clean_text(row[COL_LOCATION])
        description = clean_text(row[COL_MAIN_FUNCTION])

        # Use the acronym as the canonical name if it exists, otherwise full name
        canonical_name = full_name
        actor, created = self._get_or_create_actor(
            canonical_name, actor_type, source, location, description
        )
        actor.actor_type_raw = category

        if created:
            self.stats.entities_inserted += 1
        else:
            self.stats.entities_updated += 1

        # Partnership profile sidecar
        profile_existing = self.session.execute(
            select(PartnershipProfile).where(PartnershipProfile.actor_id == actor.actor_id)
        ).scalar_one_or_none()

        profile_fields = {
            "thematic_focus": clean_text(row[COL_THEMATIC_FOCUS]),
            "strategic_plan": clean_text(row[COL_STRATEGIC_PLAN]),
            "africa_specific_mandate": clean_text(row[COL_AFRICA_MANDATE]),
            "africa_specific_details": clean_text(row[COL_AFRICA_DETAILS]),
            "why_valuable_for_um6p": clean_text(row[COL_WHY_VALUABLE]),
            "budget_overview": clean_text(row[COL_BUDGET]),
            "partners_with_universities": parse_yes_no(row[COL_PARTNERS_UNIS]),
            "university_programmes": clean_text(row[COL_UNI_PROGRAMMES]),
            "university_partnership_examples": clean_text(row[COL_UNI_EXAMPLES]),
            "key_entry_points": clean_text(row[COL_ENTRY_POINTS]),
            "funding_delivery": parse_yes_no(row[COL_FUNDING_DELIVERY]),
            "funding_delivery_mechanisms": clean_text(row[COL_FUNDING_MECHANISMS]),
            "key_constraints": clean_text(row[COL_CONSTRAINTS]),
        }

        if profile_existing is None:
            profile = PartnershipProfile(
                partnership_profile_id=uuid.uuid4(),
                actor_id=actor.actor_id,
                source_id=source.source_id,
                verification_status="phase_1",
                confidence=1.0,
                **profile_fields,
            )
            self.session.add(profile)
            self.stats.profiles_inserted += 1
        else:
            for k, v in profile_fields.items():
                setattr(profile_existing, k, v)
            self.stats.profiles_updated += 1

        # Hierarchy
        immediate_parent = current_sub or current_major
        if immediate_parent and immediate_parent.actor_id != actor.actor_id:
            rel = "parent_body" if current_sub is None else "programme_within"
            if self._link_hierarchy(immediate_parent, actor, rel):
                self.stats.hierarchy_links_created += 1

        parent_name = immediate_parent.name if immediate_parent else "(none)"
        self.audit_writer.writerow(
            ["un_mapping", row_idx, "inserted" if created else "updated",
             canonical_name, parent_name, f"acronym={acronym}; category={category}"]
        )

    def _ensure_parent_actor(self, name: str, marker_type: str, source: Source) -> Actor:
        """Major and sub-headers become synthetic parent actors so the hierarchy is queryable."""
        actor_type = PARENT_TYPES.get(name.upper(), "intergovernmental_organization")
        existing_slug = slugify(name)
        if existing_slug in self._actor_cache:
            return self._actor_cache[existing_slug]
        existing = self.session.execute(
            select(Actor).where(Actor.slug == existing_slug)
        ).scalar_one_or_none()
        if existing is not None:
            self._actor_cache[existing_slug] = existing
            return existing
        actor = Actor(
            actor_id=uuid.uuid4(),
            name=name,
            slug=existing_slug,
            actor_type=actor_type,
            actor_type_raw=marker_type,
            description=f"Parent UN body (synthetic, generated from {marker_type} header).",
            source_id=source.source_id,
            verification_status="phase_1",
            confidence=1.0,
        )
        self.session.add(actor)
        self.session.flush()
        self._actor_cache[existing_slug] = actor
        self.stats.parents_created += 1
        return actor

    def _run_main_sheet(self, ws, source: Source):
        current_major: Optional[Actor] = None
        current_sub: Optional[Actor] = None

        for row_idx, row in enumerate(
            ws.iter_rows(min_row=DATA_STARTS_AT_ROW, values_only=True),
            start=DATA_STARTS_AT_ROW,
        ):
            row_list = list(row)[:17]
            try:
                first = row_list[0]
                first_str = str(first).strip() if first else ""

                if first_str.startswith("▶"):
                    name = first_str.replace("▶", "").strip()
                    current_major = self._ensure_parent_actor(name, "major_body", source)
                    current_sub = None
                    self.stats.headers_skipped += 1
                    self.audit_writer.writerow(
                        ["un_mapping", row_idx, "header_major", name, "", ""]
                    )
                    continue

                if first_str.startswith("▸"):
                    name = first_str.replace("▸", "").strip()
                    current_sub = self._ensure_parent_actor(name, "sub_category", source)
                    if current_major:
                        if self._link_hierarchy(current_major, current_sub, "parent_body"):
                            self.stats.hierarchy_links_created += 1
                    self.stats.headers_skipped += 1
                    self.audit_writer.writerow(
                        ["un_mapping", row_idx, "header_sub", name,
                         current_major.name if current_major else "", ""]
                    )
                    continue

                # Entity row
                if first is None or not first_str:
                    continue

                self._process_un_entity(row_idx, row_list, source, current_major, current_sub)

            except Exception as e:
                self.stats.rows_failed += 1
                raw_summary = str([str(v)[:50] if v else "" for v in row_list[:5]])
                self.failure_writer.writerow(["un_mapping", row_idx, str(e), raw_summary])
                logger.warning("UN Mapping row %d failed: %s", row_idx, e)

    # ----------------------------------------------------------
    # SHEET 2: UN KEY EVENTS
    # ----------------------------------------------------------

    def _run_events_sheet(self, ws, source: Source):
        current_org_actor: Optional[Actor] = None

        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row_idx <= 1:
                continue  # header row

            org_raw, event_raw, loc_raw = row[0], row[1], row[2]
            org_str = str(org_raw).strip() if org_raw else ""

            try:
                # Section headers
                if org_str.startswith("▶") or org_str.startswith("▸"):
                    continue

                # Continuation row (org column is empty or "—")
                if not org_raw or org_str == "—":
                    if not event_raw:
                        self.stats.events_skipped += 1
                        continue
                    self._insert_event(
                        row_idx, current_org_actor, event_raw, loc_raw, source,
                        org_name=getattr(self, "_current_org_name", None))
                    continue
                # New organization
                org_name, _ = parse_un_name_acronym(clean_text(org_str) or "")
                slug = slugify(org_name) if org_name else None
                if not slug:
                    self.stats.events_skipped += 1
                    continue

                actor = self._actor_cache.get(slug) or self.session.execute(
                    select(Actor).where(Actor.slug == slug)
                ).scalar_one_or_none()

                if actor is None:
                    # Org not yet a canonical actor — keep the event anyway with a
                    # null host (matches the annual events translator). The host link fills in later once the org exists as an actor, rathe than discarding a strategic UN event now.
                    logger.info(
                        "Events sheet row %d: org '%s' not in actor table; "
                        "storing event(s) with null host and organizer text",
                        row_idx, org_name
                    )
                    self.audit_writer.writerow(
                        ["un_events", row_idx, "org_not_found_null_host", org_name, "", ""]
                    )
                    current_org_actor = None
                    self._current_org_name = org_name        # remember for null-host events
                    if event_raw:
                        self._insert_event(row_idx, None, event_raw, loc_raw, source,
                                           org_name=org_name)
                    continue

                current_org_actor = actor
                self._actor_cache[slug] = actor
                self._current_org_name = org_name

                if event_raw:
                    self._insert_event(row_idx, current_org_actor, event_raw, loc_raw, source,
                                       org_name=org_name)
                else:
                    self.stats.events_skipped += 1

            except Exception as e:
                self.stats.rows_failed += 1
                raw_summary = f"org={org_str[:40]}; event={str(event_raw)[:60]}"
                self.failure_writer.writerow(["un_events", row_idx, str(e), raw_summary])
                logger.warning("UN Events row %d failed: %s", row_idx, e)

    def _insert_event(self, row_idx: int, host: Optional[Actor], event_text: object,
                      loc_text: object, source: Source, org_name: Optional[str] = None):
        text = clean_text(event_text)
        if not text:
            self.stats.events_skipped += 1
            return
        parsed_date, name = parse_event_string(text)
        location = clean_text(loc_text)
        host_id = host.actor_id if host else None
        host_label = host.name if host else (org_name or "none")

        # Idempotency: (name, host) for hosted events; (name, organizer) for null-host
        q = select(Event).where(Event.name == name)
        if host_id:
            q = q.where(Event.host_actor_id == host_id)
        else:
            q = q.where(Event.host_actor_id.is_(None),
                        Event.sponsoring_orgs == org_name)
        existing = self.session.execute(q).scalars().first()
        if existing is not None:
            existing.next_date = parsed_date or existing.next_date
            existing.location = location or existing.location
            # backfill organizer text if we now have it
            if org_name and not existing.sponsoring_orgs:
                existing.sponsoring_orgs = org_name
            self.audit_writer.writerow(
                ["un_events", row_idx, "event_updated", name, host_label, ""]
            )
            return

        ev = Event(
            event_id=uuid.uuid4(),
            name=name,
            event_type="UN event",
            location=location,
            next_date=parsed_date,
            host_actor_id=host_id,
            sponsoring_orgs=org_name,      # preserve the organizer even with no actor link
            source_id=source.source_id,
        )
        self.session.add(ev)
        self.stats.events_inserted += 1
        self.audit_writer.writerow(
            ["un_events", row_idx, "event_inserted", name, host_label, ""]
        )

    # ----------------------------------------------------------
    # ENTRY POINT
    # ----------------------------------------------------------

    def run(self) -> RunStats:
        if not self.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {self.source_path}")

        logger.info("Opening %s", self.source_path)
        wb = openpyxl.load_workbook(self.source_path, read_only=True, data_only=True)
        try:
            if SHEET_MAIN not in wb.sheetnames:
                raise ValueError(f"Sheet '{SHEET_MAIN}' not found. Sheets: {wb.sheetnames}")
            events_ws = next((wb[s] for s in wb.sheetnames if s.strip().lower() == "un key events"), None)
            if events_ws is None:
                raise ValueError(f"UN KEY EVENTS sheet not found. Sheets: {wb.sheetnames}")
            source = self._get_or_create_source()

            logger.info("Processing UN Mapping sheet")
            self._run_main_sheet(wb[SHEET_MAIN], source)

            # Flush so the events sheet can look up the actors created above
            self.session.flush()

            logger.info("Processing UN KEY EVENTS sheet")
            self._run_events_sheet(events_ws, source)

            self.session.commit()
        finally:
            wb.close()
            self._close_logs()

        return self.stats