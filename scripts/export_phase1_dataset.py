"""Export the Phase 1 organizations as one clean, architecture-aligned Excel sheet.

    python -m scripts.export_phase1_dataset [--out PATH]

Read-only. The rows are the verified Phase 1 organizations exactly as COMPASS
holds them (``actor_read``), so the workbook and the Ecosystem Directory cannot
disagree. The columns are the Data Feed organization template's (the approved
Architecture V2 fields) plus the Directory's "What it does" fields, grouped:
identity, sector, location, what it does, V2 evidence boxes - then, apart, the
tags and technical codes.

Cleaning, applied the same way to every row:

* one spelling per value: "United States" (never USA / US), full state names,
  category and type display names, sector names, https:// websites;
* text that is not evidence is left empty, never rewritten: the "should be
  verified from primary sources" placeholder, SEC-filing boilerplate, and any
  legacy profile sentence repeated word for word across many organizations;
* rows that describe themselves as aggregates or synthetic placeholders
  ("Aggregate category for ...", "Representative or aggregate actor row") are
  not organizations (standing rule 5) and are listed on their own sheet, with
  the reason, for removal from the Directory.
"""

from __future__ import annotations

import argparse
import re
from urllib.parse import urlsplit
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.browse import normalize_country
from src.db import get_readonly_connection

DEFAULT_OUT = Path(r"C:\Users\Ismail\GHUS-data\exports") / (
    f"GHUS_Phase1_Organizations_Clean_{date.today():%Y-%m-%d}.xlsx")

# (group, header, key). Headers follow the Data Feed template and the Directory.
COLUMNS = [
    ("Identity", "Official name", "name"),
    ("Identity", "Other names", "alt_names"),
    ("Identity", "Website", "website"),
    ("Identity", "Organization Category", "category"),
    ("Identity", "Category Type", "category_type"),
    ("Identity", "Category note", "category_note"),
    ("Sector", "Sector", "sector"),
    ("Sector", "Additional sectors", "additional_sectors"),
    ("Sector", "Hubs", "hubs"),
    ("Location", "City", "city"),
    ("Location", "State", "state"),
    ("Location", "Region", "region"),
    ("Location", "Country", "country"),
    ("What it does", "Description", "description"),
    ("What it does", "Primary technical focus", "primary_technical_focus"),
    ("What it does", "Technical approach", "technical_approach"),
    ("What it does", "Current activities", "current_activities"),
    ("What it does", "Technology and IP", "technology_ip_notes"),
    ("What it does", "Key constraints", "key_constraints"),
    ("What it does", "Funding", "funding_summary"),
    ("What it does", "Lifecycle role", "primary_lifecycle_role"),
    ("Evidence (V2 Light Pull)", "Recent activity", "recent_activity"),
    ("Evidence (V2 Light Pull)", "Funding signal", "funding_signal"),
    ("Evidence (V2 Light Pull)", "International connection", "international_connection"),
    ("Evidence (V2 Light Pull)", "UM6P/OCP connection", "um6p_ocp_connection"),
    ("Evidence (V2 Light Pull)", "Category-specific details", "category_details"),
    ("Evidence (V2 Light Pull)", "Source URL", "source_url"),
]
TECH_COLUMNS = [
    ("Tags and technical codes", "COMPASS ID", "actor_id"),
    ("Tags and technical codes", "Record status", "status"),
    ("Tags and technical codes", "Source", "source"),
    ("Tags and technical codes", "Category code", "actor_category"),
    ("Tags and technical codes", "Category type code", "category_type_code"),
    ("Tags and technical codes", "Sector codes", "sector_codes"),
    ("Tags and technical codes", "State code", "state_code"),
    ("Tags and technical codes", "Region code", "region_code"),
    ("Tags and technical codes", "Website domain", "website_domain"),
    ("Tags and technical codes", "Latitude", "latitude"),
    ("Tags and technical codes", "Longitude", "longitude"),
    ("Tags and technical codes", "Last updated", "updated"),
    ("Tags and technical codes", "Data notes", "notes"),
]
LEGACY_TEXT = ("primary_technical_focus", "technical_approach", "current_activities",
               "technology_ip_notes", "key_constraints", "funding_summary")
V2_FACTS = ("recent_activity", "funding_signal", "international_connection", "um6p_ocp_connection")
# A legacy sentence shared word for word by this many organizations is a template, not evidence.
TEMPLATE_REPEATS = 3
PLACEHOLDER = re.compile(r"should be verified from primary sources|^SEC registrant record for", re.I)
AGGREGATE_MARKERS = (
    ("description", re.compile(r"^Aggregate category", re.I), "Describes itself as an aggregate category"),
    ("description", re.compile(r"^Parent UN body \(synthetic", re.I), "Synthetic placeholder row"),
    ("key_constraints", re.compile(r"^Not directly actionable as one partner", re.I),
     "Describes itself as not one partner (a group of organizations)"),
    ("key_constraints", re.compile(r"^Requires identification of the specific constituent", re.I),
     "Describes itself as a group of organizations"),
    ("funding_summary", re.compile(r"^Representative or aggregate actor row", re.I),
     "Describes itself as a representative or aggregate row"),
    ("technology_ip_notes", re.compile(r"^Aggregate/category row", re.I),
     "Describes itself as an aggregate row"),
    ("current_activities", re.compile(r"^(Aggregate mapping row|Used as a GHUS mapping label)", re.I),
     "Describes itself as a mapping label"),
    ("primary_technical_focus", re.compile(r"^Representative .* category for actors", re.I),
     "Describes itself as a representative category"),
)
LIFECYCLE = {"discovery": "Discovery", "validation": "Validation", "deployment": "Deployment",
             "demonstration": "Demonstration", "scaling": "Scaling", "multiple roles": "Multiple Roles"}
SOURCE_LABELS = {"imported_phase1": "Phase 1 import (GHUS ecosystem mapping)"}

ACTORS_SQL = """
SELECT a.actor_id::text, a.name, a.alt_names, a.website, a.website_domain, a.actor_category,
       replace(coalesce(cd.display_name, a.actor_category), 'Corporate Actor', 'Corporate Organization')
         AS category,
       a.category_type AS category_type_code, td.display_name AS category_type, a.category_note,
       a.city, a.state_code, rs.state_name, a.region_code, rd.display_name AS region, a.country,
       a.latitude, a.longitude, a.description, a.status, a.source_origin, a.updated_at,
       a.primary_technical_focus, a.technical_approach, a.current_activities, a.technology_ip_notes,
       a.key_constraints, a.funding_summary, a.primary_lifecycle_role
FROM actor_read a
LEFT JOIN actor_category_definition cd ON cd.category_code = a.actor_category
LEFT JOIN actor_category_type_definition td
       ON td.category_code = a.actor_category AND td.type_code = a.category_type
LEFT JOIN region_state rs ON rs.state_code = a.state_code
LEFT JOIN region_definition rd ON rd.region_code = a.region_code
WHERE a.status = 'verified' AND a.source_origin = 'imported_phase1'
  AND a.merged_into_actor_id IS NULL
ORDER BY a.name
"""
SECTORS_SQL = """
SELECT x.actor_id::text, s.code, s.name, x.is_primary FROM actor_sector x
JOIN sector s ON s.sector_id = x.sector_id WHERE x.actor_id = ANY(%s::uuid[])
ORDER BY x.is_primary DESC, s.name
"""
HUBS_SQL = """
SELECT ha.actor_id::text, h.name FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id
WHERE ha.actor_id = ANY(%s::uuid[]) ORDER BY h.name
"""
FACTS_SQL = """
SELECT p.actor_id::text, p.fact_key, f.fact_value, s.url FROM actor_fact_current_pointer p
JOIN actor_fact f ON f.actor_fact_id = p.actor_fact_id
LEFT JOIN source s ON s.source_id = f.source_id
WHERE p.actor_id = ANY(%s::uuid[]) ORDER BY p.changed_at
"""


def clean_text(value) -> str:
    return " ".join(str(value or "").split())


def fact_text(value) -> str:
    """A fact's readable value, whatever shape it was stored in."""
    if isinstance(value, dict):
        for key in ("value", "text", "summary", "name"):
            if value.get(key):
                return fact_text(value[key])
        return ""
    if isinstance(value, list):
        return "; ".join(t for t in (fact_text(v) for v in value) if t)
    text_ = clean_text(value)
    return "" if text_.lower() in {"not found", "not_found", "none", "null", "n/a"} else text_


def https(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    return re.sub(r"^http://", "https://", url, flags=re.I)


def site_key(url: str) -> tuple[str, str]:
    """(domain, page) of a website: the domain without www, and the page without scheme or
    trailing slash - two records with the same page are the same website."""
    parts = urlsplit(https(url))
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return host, (host + path).lower() if host else ""


def aggregate_reason(row: dict) -> str | None:
    for key, pattern, reason in AGGREGATE_MARKERS:
        if pattern.search(clean_text(row.get(key))):
            return reason
    return None


def box_label(key: str) -> str:
    from src.datafeed.contract import ACTOR_FIELDS

    for field in ACTOR_FIELDS:
        if field.key == key:
            return field.header
    return key.replace("_", " ").capitalize()


def load(conn) -> tuple[list[dict], dict, dict, dict]:
    with conn.cursor() as cur:
        cur.execute(ACTORS_SQL)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        ids = [r["actor_id"] for r in rows]
        sectors, hubs, facts = {}, {}, {}
        cur.execute(SECTORS_SQL, (ids,))
        for actor_id, code, name, primary in cur.fetchall():
            sectors.setdefault(actor_id, []).append((code, name, primary))
        cur.execute(HUBS_SQL, (ids,))
        for actor_id, name in cur.fetchall():
            hubs.setdefault(actor_id, []).append(name)
        cur.execute(FACTS_SQL, (ids,))
        for actor_id, key, value, url in cur.fetchall():
            facts.setdefault(actor_id, {})[key] = (fact_text(value), url)
    return rows, sectors, hubs, facts


def build_rows(rows, sectors, hubs, facts):
    from src.datafeed.contract import ACTOR_FIELDS

    boxes = {f.key for f in ACTOR_FIELDS if f.category}
    repeats = {key: Counter(clean_text(r[key]) for r in rows if clean_text(r[key]))
               for key in LEGACY_TEXT}
    names_by_page: dict[str, list[str]] = {}
    for r in rows:
        if not aggregate_reason(r) and site_key(r["website"])[1]:
            names_by_page.setdefault(site_key(r["website"])[1], []).append(clean_text(r["name"]))
    kept, excluded = [], []
    for r in rows:
        reason = aggregate_reason(r)
        if reason:
            excluded.append({"name": r["name"], "category": r["category"],
                             "website": https(r["website"]), "reason": reason,
                             "description": clean_text(r["description"])[:300],
                             "actor_id": r["actor_id"]})
            continue
        notes = []
        description = clean_text(r["description"])
        if PLACEHOLDER.search(description):
            description = ""
            notes.append("Description not yet collected (Phase 1 placeholder removed)")
        legacy = {}
        blanked = []
        for key in LEGACY_TEXT:
            value = clean_text(r[key])
            if value and repeats[key][value] >= TEMPLATE_REPEATS:
                blanked.append(key.replace("_", " "))
                value = ""
            legacy[key] = value
        if blanked:
            notes.append("Generic Phase 1 text left empty: " + ", ".join(blanked))
        own = sorted(sectors.get(r["actor_id"], []), key=lambda s: (not s[2], s[1]))
        primary = next((s for s in own if s[2]), own[0] if len(own) == 1 else None)
        others = [s for s in own if s is not primary]
        if not own:
            notes.append("Sector not yet assigned")
            sector_cell = ""
        elif primary is None:
            # Several sectors and none chosen as the main one: all are shown, none is promoted.
            notes.append("Main sector to choose among: " + ", ".join(s[1] for s in own))
            sector_cell, others = "; ".join(s[1] for s in own), []
        else:
            sector_cell = primary[1]
        country = normalize_country(r["country"]) or ("United States" if r["state_code"] else "")
        if r["country"] and not normalize_country(r["country"]):
            notes.append(f"Country unclear in source: {clean_text(r['country'])}")
        domain, page = site_key(r["website"])
        same = [n for n in names_by_page.get(page, []) if n != clean_text(r["name"])]
        if same:
            notes.append("Possible duplicate - same website as: " + "; ".join(same[:5]))
        if page and len(urlsplit(https(r["website"])).path.strip("/").split("/")) >= 3:
            notes.append("Website is a deep page, not the organization's home page")
        own_facts = facts.get(r["actor_id"], {})
        details = "; ".join(f"{box_label(k)}: {v}" for k, (v, _) in sorted(own_facts.items())
                            if k in boxes and v)
        source_urls = [u for k, (v, u) in own_facts.items()
                       if k in V2_FACTS and v and u and u.startswith("http")]
        lifecycle = clean_text(r["primary_lifecycle_role"]).replace("_", " ")
        if lifecycle and lifecycle.lower() not in LIFECYCLE:
            notes.append(f"Lifecycle role in Phase 1 was not a lifecycle stage: {lifecycle}")
            lifecycle = ""
        kept.append({
            "name": clean_text(r["name"]),
            "alt_names": "; ".join(clean_text(n) for n in (r["alt_names"] or []) if clean_text(n)),
            "website": https(r["website"]),
            "category": r["category"] or "",
            "category_type": r["category_type"] or "",
            "category_note": clean_text(r["category_note"]),
            "sector": sector_cell,
            "additional_sectors": "; ".join(s[1] for s in others),
            "hubs": "; ".join(hubs.get(r["actor_id"], [])),
            "city": clean_text(r["city"]),
            "state": r["state_name"] or "",
            "region": r["region"] or "",
            "country": country,
            "description": description,
            **legacy,
            "primary_lifecycle_role": LIFECYCLE.get(lifecycle.lower(), ""),
            **{k: own_facts.get(k, ("", None))[0] for k in V2_FACTS},
            "category_details": details,
            "source_url": source_urls[0] if source_urls else "",
            "actor_id": r["actor_id"],
            "status": "Verified",
            "source": SOURCE_LABELS.get(r["source_origin"], r["source_origin"] or ""),
            "actor_category": r["actor_category"] or "",
            "category_type_code": r["category_type_code"] or "",
            "sector_codes": "; ".join(s[0] for s in own),
            "state_code": r["state_code"] or "",
            "region_code": r["region_code"] or "",
            "website_domain": r["website_domain"] or domain,
            "latitude": float(r["latitude"]) if r["latitude"] is not None else None,
            "longitude": float(r["longitude"]) if r["longitude"] is not None else None,
            "updated": r["updated_at"].strftime("%m/%d/%Y") if r["updated_at"] else "",
            "notes": " | ".join(notes),
        })
    return kept, excluded


GROUP_FILL = {"Identity": "1F3A5F", "Sector": "2E5E4E", "Location": "4B3F72",
              "What it does": "5B4636", "Evidence (V2 Light Pull)": "6B4E16",
              "Tags and technical codes": "6E6E6E"}
WIDE = {"description", "primary_technical_focus", "technical_approach", "current_activities",
        "technology_ip_notes", "key_constraints", "funding_summary", "recent_activity",
        "funding_signal", "international_connection", "um6p_ocp_connection", "category_details",
        "notes", "hubs"}


def write(kept, excluded, out: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Organizations"
    columns = COLUMNS + TECH_COLUMNS
    white = Font(bold=True, color="FFFFFF")
    for index, (group, header, key) in enumerate(columns, 1):
        fill = PatternFill("solid", fgColor=GROUP_FILL[group])
        top = ws.cell(row=1, column=index, value=group)
        top.font, top.fill = white, fill
        cell = ws.cell(row=2, column=index, value=header)
        cell.font, cell.fill = white, fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(index)].width = (
            48 if key in WIDE else 38 if key == "actor_id" else 22)
    # One label per group band.
    start = 1
    for index in range(2, len(columns) + 2):
        if index > len(columns) or columns[index - 1][0] != columns[start - 1][0]:
            if index - 1 > start:
                ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=index - 1)
            start = index
    for r_index, row in enumerate(kept, 3):
        for c_index, (_, _, key) in enumerate(columns, 1):
            value = row.get(key)
            ws.cell(row=r_index, column=c_index, value=value if value not in ("", None) else None)
    ws.freeze_panes = "B3"
    ws.auto_filter.ref = f"A2:{get_column_letter(len(columns))}{len(kept) + 2}"

    ex = wb.create_sheet("Not organizations")
    headers = ["Name", "Category in Phase 1", "Website", "Why it is not an organization",
               "Phase 1 description (first 300 characters)", "COMPASS ID"]
    for index, header in enumerate(headers, 1):
        cell = ex.cell(row=1, column=index, value=header)
        cell.font, cell.fill = white, PatternFill("solid", fgColor="8A2D2D")
        ex.column_dimensions[get_column_letter(index)].width = [44, 30, 34, 48, 70, 38][index - 1]
    for r_index, row in enumerate(excluded, 2):
        for c_index, key in enumerate(("name", "category", "website", "reason", "description",
                                        "actor_id"), 1):
            ex.cell(row=r_index, column=c_index, value=row[key] or None)
    ex.freeze_panes = "A2"
    ex.auto_filter.ref = f"A1:F{len(excluded) + 1}"

    about = wb.create_sheet("About")
    filled = lambda key: sum(1 for r in kept if r.get(key))
    lines = [
        ("GHUS Phase 1 organizations - clean dataset", True),
        (f"Exported from COMPASS on {date.today():%m/%d/%Y}. The rows are the records in the "
         "Ecosystem Directory, so this file and the platform agree.", False),
        ("", False),
        ("Sheets", True),
        (f"Organizations: {len(kept)} verified Phase 1 organizations, one row each.", False),
        (f"Not organizations: {len(excluded)} Phase 1 rows that describe themselves as aggregate "
         "categories, groups or synthetic placeholders. Proposed for removal from the Directory.", False),
        ("", False),
        ("Columns", True),
        ("Coloured bands group related fields: Identity, Sector, Location, What it does, Evidence "
         "(V2 Light Pull). Tags and technical codes are kept apart, in grey, at the right.", False),
        ("Column names match the Data Feed organization template and the Ecosystem Directory.", False),
        ("", False),
        ("Cleaning rules (the same for every row)", True),
        ("Country is always 'United States' for US organizations (never USA or US); states are "
         "full names; categories, types, sectors and regions use their display names.", False),
        ("Text that is not evidence is left empty, never rewritten: the 'should be verified from "
         "primary sources' placeholder, SEC-filing boilerplate, and legacy profile sentences "
         f"repeated word for word across {TEMPLATE_REPEATS} or more organizations. 'Data notes' "
         "says what was left empty. Empty cells are enriched through Monitor and Update.", False),
        ("Websites start with https://. Nothing is invented: a value missing in COMPASS is empty here.",
         False),
        ("", False),
        ("Completeness", True),
        *[(f"{label}: {filled(key)} of {len(kept)}", False) for label, key in (
            ("Sector", "sector"), ("Category Type", "category_type"), ("Website", "website"),
            ("City", "city"), ("State", "state"), ("Description", "description"),
            ("Recent activity", "recent_activity"), ("Funding signal", "funding_signal"))],
    ]
    for r_index, (text_, bold) in enumerate(lines, 1):
        cell = about.cell(row=r_index, column=1, value=text_ or None)
        cell.font = Font(bold=bold, size=13 if r_index == 1 else 11)
        cell.alignment = Alignment(wrap_text=True)
    about.column_dimensions["A"].width = 120
    wb.move_sheet("About", offset=-2)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    with get_readonly_connection() as conn:
        rows, sectors, hubs, facts = load(conn)
    kept, excluded = build_rows(rows, sectors, hubs, facts)
    write(kept, excluded, args.out)
    print(f"{len(kept)} organizations, {len(excluded)} not organizations -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
