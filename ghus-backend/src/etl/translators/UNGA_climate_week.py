"""
Translator for UNGA___CLIMATE_WEEK_MAPPING_2026.xlsx
→ event table only (these events are NOT scored, so no event_scoring rows).

The sheet is a flat 11-column list that grows continuously as new UNGA/Climate
Week events are announced. Columns:
  Event name | Event type | Number of attendance (people) | Organiser |
  Date and time | Location | Core theme | 2026 Theme | Short description |
  Access type | Link

Mapping to the event table:
  Event name        -> name
  Event type        -> event_type
  Organiser         -> sponsoring_orgs   (and used to look up a host actor)
  Date and time     -> next_date (parsed) ; raw kept in description
  Location          -> location
  Link              -> website
  Number of attendance, Core theme, 2026 Theme, Short description, Access type
                    -> folded into a single descriptive text (event has no
                       dedicated columns for these, and they are not dropped —
                       they are preserved in the description)

Idempotent by (name, host_actor_id) — same rule as the other event translator,
so re-ingesting the updated sheet updates rows instead of duplicating them.

    python scripts/run_unga_climate_week.py            # dry run
    python scripts/run_unga_climate_week.py --apply
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.enrichment.decisions import persist_canonical_record

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db.models import Actor, Event, Source
from src.etl.common.text_cleaning import clean_text, slugify

try:
    from src.etl.common.header_resolver import HeaderMap, find_header_row
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from header_resolver import HeaderMap, find_header_row

logger = logging.getLogger(__name__)

SOURCE_FILE = "data/raw/UNGA_&_CLIMATE_WEEK_MAPPING_2026.xlsx"
EVENTS_SHEET_HINT = ["Event name", "Organiser", "Date and time", "Link"]
AUDIT_LOG = "data/interim/unga_climate_week_audit.csv"
SCORING_METHODOLOGY_VERSION = "unga2026"

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


@dataclass
class RunStats:
    events_inserted: int = 0
    events_matched: int = 0
    rows_skipped_header: int = 0
    rows_skipped_empty: int = 0
    rows_failed: int = 0


def parse_date(text: Optional[str]):
    """Best-effort date from '21 September 2026, 5:00 PM'. Returns date or None."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", str(text))
    if m:
        day, mon, year = int(m.group(1)), MONTHS.get(m.group(2).lower()), int(m.group(3))
        if mon:
            try:
                return datetime(year, mon, day).date()
            except ValueError:
                return None
    return None


def is_section_header(row: list, hm: HeaderMap) -> bool:
    """Section banners ('OFFICIAL UNGA EVENT ...') fill only the first cell."""
    name_i = hm.index("Event name") or 0
    filled = [c for c in row if c not in (None, "")]
    return len(filled) == 1 and name_i < len(row) and row[name_i] not in (None, "")


class UngaClimateWeekTranslator:
    def __init__(self, project_root: Path, session: Session, apply: bool):
        self.root = project_root
        self.session = session
        self.apply = apply
        self.stats = RunStats()
        self._event_cache: dict = {}
        Path(self.root / AUDIT_LOG).parent.mkdir(parents=True, exist_ok=True)
        self._audit_fp = open(self.root / AUDIT_LOG, "w", newline="", encoding="utf-8")
        self.audit = csv.writer(self._audit_fp)
        self.audit.writerow(["row", "verdict", "event_name", "host", "next_date"])

    def _source(self) -> Source:
        desc = f"UNGA & Climate Week 2026 mapping ingested from {SOURCE_FILE}"
        existing = self.session.execute(
            select(Source).where(Source.description == desc)).scalar_one_or_none()
        if existing:
            return existing
        src = Source(source_id=uuid.uuid4(), source_type="spreadsheet",
                     description=desc, url=SOURCE_FILE)
        persist_canonical_record(self.session, src)
        self.session.flush()
        return src

    def _find_host(self, organiser: Optional[str]) -> Optional[Actor]:
        if not organiser:
            return None
        slug = slugify(organiser)
        # exact-ish match against canonical actors only
        return self.session.execute(
            select(Actor).where(Actor.slug == slug,
                                Actor.merged_into_actor_id.is_(None))
        ).scalar_one_or_none()

    @staticmethod
    def _clean_opt(v):
        v = clean_text(v)
        if v and v.lower() in ("not confirmed", "tbc", "tba", "n/a"):
            return None
        return v

    def _thematic(self, hm: HeaderMap, row: list):
        """Core theme + 2026 theme folded into one thematic_focus value."""
        parts = []
        for col in ("Core theme", "2026 Theme"):
            v = self._clean_opt(hm.get(row, col))
            if v:
                parts.append(v)
        return " | ".join(parts) or None

    def _upsert(self, hm: HeaderMap, row_idx: int, row: list, source: Source):
        name = clean_text(hm.get(row, "Event name"))
        if not name:
            self.stats.rows_skipped_empty += 1
            return
        organiser = clean_text(hm.get(row, "Organiser"))
        host = self._find_host(organiser)
        host_id = host.actor_id if host else None
        date_raw = clean_text(hm.get(row, "Date and time"))
        next_date = parse_date(date_raw)

        key = (name.lower(), str(host_id) if host_id else None)
        if key in self._event_cache:
            return
        q = select(Event).where(Event.name == name)
        q = q.where(Event.host_actor_id == host_id) if host_id else q.where(Event.host_actor_id.is_(None))
        existing = self.session.execute(q).scalar_one_or_none()

        website = self._clean_opt(hm.get(row, "Link"))
        location = self._clean_opt(hm.get(row, "Location"))
        description = self._clean_opt(hm.get(row, "Short description"))
        raw_type = self._clean_opt(hm.get(row, "Event type"))
        event_type = "UNGA/Climate Week event"
        thematic = self._thematic(hm, row)
        if raw_type:
            thematic = f"{raw_type} | {thematic}" if thematic else raw_type
        attendance = self._clean_opt(hm.get(row, "Number of attendance (people)"))
        access = self._clean_opt(hm.get(row, "Access type"))

        if existing:
            existing.event_type = event_type
            existing.location = existing.location or location
            existing.website = existing.website or website
            existing.sponsoring_orgs = existing.sponsoring_orgs or organiser
            existing.next_date = existing.next_date or next_date
            existing.description = existing.description or description
            existing.thematic_focus = existing.thematic_focus or thematic
            existing.expected_attendance = existing.expected_attendance or attendance
            existing.access_type = existing.access_type or access
            self._event_cache[key] = existing
            self.stats.events_matched += 1
            self.audit.writerow([row_idx, "matched", name, organiser or "", next_date or ""])
            return

        ev = Event(event_id=uuid.uuid4(), name=name, event_type=event_type,
                   location=location, website=website, next_date=next_date,
                   sponsoring_orgs=organiser, host_actor_id=host_id,
                   description=description, thematic_focus=thematic,
                   expected_attendance=attendance, access_type=access,
                   source_id=source.source_id)
        persist_canonical_record(self.session, ev)
        self.session.flush()
        self._event_cache[key] = ev
        self.stats.events_inserted += 1
        self.audit.writerow([row_idx, "inserted", name, organiser or "", next_date or ""])

    def run(self) -> RunStats:
        wb = openpyxl.load_workbook(self.root / SOURCE_FILE, read_only=True, data_only=True)
        # find the events sheet by content, tolerant of trailing spaces
        target = None
        for ws in wb.worksheets:
            if "website" in ws.title.strip().lower():
                continue
            hr, _ = find_header_row(ws, EVENTS_SHEET_HINT)
            if hr and HeaderMap(hr).index("Event name") is not None:
                target = ws
                break
        if target is None:
            raise SystemExit("No events sheet found in the UNGA workbook")

        header_row, data_start = find_header_row(target, EVENTS_SHEET_HINT)
        hm = HeaderMap(header_row)
        source = self._source()
        for row_idx, row in enumerate(
                target.iter_rows(min_row=data_start, values_only=True), start=data_start):
            row = list(row)
            if all(c in (None, "") for c in row):
                continue
            if is_section_header(row, hm):
                self.stats.rows_skipped_header += 1
                continue
            try:
                self._upsert(hm, row_idx, row, source)
            except Exception as e:
                self.stats.rows_failed += 1
                logger.warning("UNGA row %d failed: %s", row_idx, e)
        wb.close()

        if self.apply:
            self.session.commit()
        else:
            self.session.rollback()
        self._audit_fp.close()
        return self.stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    from src.db.session import SessionLocal
    root = Path(__file__).resolve().parents[1]
    s = SessionLocal()
    try:
        stats = UngaClimateWeekTranslator(root, s, apply=args.apply).run()
    finally:
        s.close()
    print(f"[{'APPLIED' if args.apply else 'DRY RUN'}] "
          f"inserted={stats.events_inserted} matched={stats.events_matched} "
          f"header_rows={stats.rows_skipped_header} empty={stats.rows_skipped_empty} "
          f"failed={stats.rows_failed}")
    if not args.apply:
        print("Dry run — nothing committed. Re-run with --apply.")


if __name__ == "__main__":
    main()