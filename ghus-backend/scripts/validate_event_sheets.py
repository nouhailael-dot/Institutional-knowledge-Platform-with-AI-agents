"""
validate_event_sheets.py — pre-flight check BEFORE any event migration.

Run this first. For every sheet in the new event files it prints which columns
matched a known field and which did not, so column typos, casing, reorderings,
and dropped fields surface on screen instead of as silent bad data.

It writes NOTHING to the database. Green = safe to migrate. Any red = fix first.

    python scripts/validate_event_sheets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from src.etl.common.header_resolver import HeaderMap, find_header_row, normalize_header
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    from header_resolver import HeaderMap, find_header_row, normalize_header

# Fields each sheet type is expected to provide. Intentionally-dropped columns
# (Potential Strategic Value, Strategic Positioning) are NOT required here.
SECTOR_EXPECTED = [
    "Event Name", "Event Description", "Official website", "Location", "Date",
    "Frequency", "Organizer", "Thematic Focus",
    "Agriculture", "Water", "Healthcare", "Artificial Intelligence",
    "Energy Transition", "Mining", "Specialty Chemicals",
    "Event Longevity", "Event Recognition Level", "Audience Size",
    "Speakers Profile", "Organizer Credibility", "Geographic Reach",
    "Longevity Score", "Recognition Score", "Scale Score",
    "Audience Profile Score", "Organizer Profile Score", "Geography Reach Score",
    "TOTAL /18", "TIER",
]
UN_KEY_EXPECTED = ["Event Name", "UN Category", "Event Description", "Location",
                   "Date / Frequency", "Organizer", "Official Website",
                   "Thematic Focus"]
UNGA_EXPECTED = ["Event name", "Event type", "Number of attendance (people)",
                 "Organiser", "Date and time", "Location", "Core theme",
                 "2026 Theme", "Short description", "Access type", "Link"]

NON_SECTOR_TABS = {"un key events", "scoring guide & methodology",
                   "event tracking websites"}

FILES = {
    "data/raw/UM6P_EVENT_VF.xlsx": "sector",
    "data/raw/UNGA_&_CLIMATE_WEEK_MAPPING_2026.xlsx": "unga",
}


def check_sheet(ws, expected, label):
    header_row, data_start = find_header_row(ws, expected)
    hm = HeaderMap(header_row or [])
    missing = hm.missing(expected)
    matched = [e for e in expected if e not in missing]
    extra = [normalize_header(c) for c in (header_row or [])
             if c is not None and normalize_header(c) not in
             {normalize_header(e) for e in expected}]
    status = "OK  " if not missing else "WARN"
    print(f"  [{status}] {label:<26} header@row{data_start-1} data@row{data_start} "
          f"| matched {len(matched)}/{len(expected)}")
    if missing:
        print(f"         MISSING: {missing}")
    if extra:
        print(f"         (unmapped columns, ignored): {extra}")
    return not missing


def main():
    all_ok = True
    for path, kind in FILES.items():
        p = Path(path)
        print("=" * 74)
        print(path)
        if not p.exists():
            print(f"  [SKIP] file not found at {path}")
            all_ok = False
            continue
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        for ws in wb.worksheets:
            tab = ws.title.strip().lower()
            if kind == "sector":
                if tab in NON_SECTOR_TABS:
                    if tab == "un key events":
                        all_ok &= check_sheet(ws, UN_KEY_EXPECTED, ws.title.strip())
                    continue
                all_ok &= check_sheet(ws, SECTOR_EXPECTED, ws.title.strip())
            else:
                if tab.startswith("unga") or "event" in tab and "website" not in tab:
                    all_ok &= check_sheet(ws, UNGA_EXPECTED, ws.title.strip())
        wb.close()
    print("=" * 74)
    print("ALL SHEETS OK — safe to migrate." if all_ok
          else "SOME SHEETS HAVE MISSING COLUMNS — fix before migrating.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()