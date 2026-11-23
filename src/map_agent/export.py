"""Export a map to a spreadsheet (.xlsx) or a deck (.pptx).

Both take the pipeline result and write ONLY the selected entities (the ranked
matches), since that is what a user hands to the team. Nothing here calls an
LLM — it is pure formatting of data already produced.

A downloaded file also sidesteps the in-memory-only storage problem: it survives
the server restarts that otherwise wipe a map.
"""

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from src.map_agent.event_dates import dates_text

# --- UM6P brand palette (from the team's own deck) ---
ACCENT = RGBColor(0xD7, 0x41, 0x0B)   # deep orange
INK    = RGBColor(0x3D, 0x39, 0x35)   # warm near-black
GRAY   = RGBColor(0xED, 0xED, 0xED)   # light card fill
PEACH  = RGBColor(0xF6, 0xD7, 0xCB)   # orange-tint card fill
MUTED  = RGBColor(0x6B, 0x6B, 0x6B)   # secondary text
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
SERIF  = "Cambria"                    # titles
SANS   = "Calibri"                    # body / labels

# Human-facing columns per entity type: (field, header). Order matters: it is
# the column order in the sheet and the field order on a slide, and it follows
# the Explore and Map cards (2 Nov 2026). Fields starting with "_" are computed.
FIELDS = {
    "actor": [
        ("name", "Name"), ("_review", "Review"), ("_found_by", "Found by"),
        ("description", "Description"), ("_relationships", "Organization relationships"),
        ("actor_type", "Category"), ("category_type", "Category type"), ("sector", "Sector"),
        ("_public_private", "Public/Private"),
        ("location_city", "City"), ("state", "State"), ("region", "Region"), ("country", "Country"),
        ("primary_technical_focus", "Focus"), ("current_activities", "Activity"),
        ("funding_summary", "Funding"),
        ("other_names", "Other names"), ("international_connections", "Africa / Morocco connections"),
        ("rankings", "University rankings"), ("_category_facts", "Category facts"),
        ("_additional", "Additional information"), ("website", "Website"),
        ("mapped_topic", "Mapped topic"), ("match_strength", "Topic match"),
        ("match_explanation", "Why it matched"),
    ],
    # People: LinkedIn only, no biography or affiliation note (30 Oct and 2 Nov 2026).
    "person": [
        ("full_name", "Name"), ("_review", "Review"), ("_found_by", "Found by"),
        ("title", "Title"), ("organization_name", "Organization"),
        ("organization_location", "Location"),
        ("expertise", "Expertise"), ("work_evidence", "Relevant work"),
        ("um6p_ocp_status", "UM6P/OCP connection"), ("um6p_ocp_detail", "UM6P/OCP details"),
        ("_linkedin", "LinkedIn / profile page"), ("email", "Email"),
    ],
    "event": [
        ("name", "Name"), ("_review", "Review"), ("_found_by", "Found by"),
        ("description", "Description"),
        ("event_type", "Type"), ("event_format", "Format"), ("sector", "Sector"),
        ("next_date", "Date"), ("date_status", "Date status"), ("recurring_pattern", "Frequency"),
        ("previous_edition", "Previous edition"),
        ("location", "Location"), ("_event_region", "Region"),
        ("organizer", "Organizer"), ("thematic_focus", "Topic"),
        ("expected_attendance", "Scale"), ("audience", "Audience"),
        ("um6p_ocp_status", "UM6P/OCP involvement"), ("um6p_ocp_detail", "UM6P/OCP details"),
        ("website", "Website"), ("match_explanation", "Why it matched"),
    ],
}
# On a slide these go to the "Why it's on this map" panel, not the facts card.
WHY_FIELDS = ("mapped_topic", "match_strength", "match_explanation")

# The category's light-pull facts (actor_profile.LIGHT_GUIDANCE); anything else
# the AI labelled itself is "Additional information". Mirrors the Explore and
# Map card, so a repeat of Focus or of "Operated by" is left out here too.
_FOCUS_LIKE = re.compile(r"focus|program area", re.I)
_PUBLIC_PRIVATE = re.compile(r"^public\s*/?\s*(or\s*)?private$", re.I)
_LISTED_FACT = re.compile(
    r"^(land.grant|relevant cent|program|key program|operator|type|.*\btype$|recent project|projects?$|"
    r"main funders?|funders?|sponsor|formal designation|facility|what it tests|current project|clinical|"
    r"academic link|scale|initiative|size|company size|products?|key products?|relevant products?|segment|"
    r"operating location|current activity|technology|problem|found|stage|trl|funding stage|pilot|customer|"
    r"offerings?|headquarters|fund size|thesis|jurisdiction|parent|mandate|funding programs?|mission|"
    r"geography|grant themes?|member|documented members|institution type|governance)", re.I)


def _plain(text) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _restates(value, names) -> bool:
    """A fact that only repeats a relationship's organization; one adding detail stays."""
    v = _plain(value)
    return any(n and (v == n or (v.startswith(n) and len(v) - len(n) <= 12) or (n.startswith(v) and len(v) > 3))
               for n in names)


def _merged_details(details) -> list[dict]:
    """One row per label: a label given twice keeps both values, once each."""
    rows: dict[str, dict] = {}
    for d in details or []:
        if not isinstance(d, dict) or not d.get("label") or not d.get("value"):
            continue
        key, row = _plain(d["label"]), rows.get(_plain(d["label"]))
        if row is None:
            rows[key] = {"label": d["label"], "value": str(d["value"])}
        elif _plain(d["value"]) not in _plain(row["value"]):
            row["value"] += "; " + str(d["value"])
    return list(rows.values())


def org_facts(entity: dict) -> dict:
    """The category details split as the card shows them, without repeats."""
    rels = entity.get("actor_relationships") or []
    operated = any("operated by" in str(r.get("relationship", "")).lower() for r in rels if isinstance(r, dict))
    names = [_plain(re.sub(r"\s*\([^)]*\)", "", str(r.get("organization_name") or "")))
             for r in rels if isinstance(r, dict)]
    funding = _plain(entity.get("funding_summary"))
    listed, extra, public_private = [], [], None
    for d in _merged_details(entity.get("category_details")):
        label = str(d.get("label") or "").strip()
        if _restates(d.get("value"), names):
            continue
        if re.search(r"fund|sponsor", label, re.I) and funding and \
                _plain(re.sub(r"\s*\([^)]*\)", "", str(d.get("value")))) in funding:
            continue
        if _PUBLIC_PRIVATE.match(label):
            public_private = d.get("value")
        elif _FOCUS_LIKE.search(label) and entity.get("primary_technical_focus"):
            continue
        elif label.lower() == "operator" and operated:
            continue
        else:
            (listed if _LISTED_FACT.match(label) else extra).append(d)
    return {"listed": listed, "extra": extra, "public_private": public_private}


def _lines(rows) -> str:
    return "\n".join(f"{d.get('label')}: {d.get('value')}" for d in rows if d.get("value"))


GROUPS = [("actor", "Organizations"), ("person", "People"), ("event", "Events")]

_HEADER_FILL = PatternFill("solid", fgColor="D7410B")   # UM6P brand orange
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _name(e: dict) -> str:
    return e.get("full_name") or e.get("name") or "—"


def _sources_text(e: dict) -> str:
    return "\n".join(s.get("url", "") for s in (e.get("sources") or []) if s.get("url"))


CAPITALIZED_FIELDS = frozenset({
    "event_type", "date_status", "event_format", "recurring_pattern", "audience", "access_type",
    "expected_attendance", "thematic_focus", "sector", "actor_type", "category_type",
})


def _field_value(entity: dict, field: str):
    """Human-readable value for scalar and relationship fields."""
    value = entity.get(field)
    if field in ("next_date", "previous_edition"):
        end = entity.get("end_date") if field == "next_date" else None
        return dates_text(value, end) if value else value
    if field == "um6p_ocp_status" and value:
        # Old maps wrote "not found in what's been read"; Compass says Not Found.
        return "Found" if value == "found" else "Not Found"
    # 12 Nov 2026 (GHUS): every data value starts with a capital letter.
    if field in CAPITALIZED_FIELDS and isinstance(value, str) and value:
        return value[0].upper() + value[1:]
    if field == "_review":
        if (entity.get("_db_save") or {}).get("outcome") in ("directory", "review"):
            return "Verified, saved"
        return {"ready": "Verified", "parked": "Parked"}.get(value, "Pending review")
    if field == "_relationships":
        return "\n".join(f"{str(r.get('relationship', '')).replace('_', ' ').capitalize()}: {r.get('organization_name', '')}"
                         for r in entity.get("actor_relationships") or [] if isinstance(r, dict))
    if field == "_public_private":
        return org_facts(entity)["public_private"]
    if field == "_category_facts":
        return _lines(org_facts(entity)["listed"])
    if field == "_additional":
        return _lines(org_facts(entity)["extra"])
    if field == "_linkedin":
        # LinkedIn when found, otherwise the person's profile page (3 Nov 2026).
        linked = next((u for u in (entity.get("linkedin_url"), entity.get("profile_url"))
                       if re.match(r"^https?://([a-z]+\.)?linkedin\.com/", str(u or ""), re.I)), None)
        profile = entity.get("profile_url") if re.match(r"^https?://", str(entity.get("profile_url") or "")) else None
        return linked or profile
    if field == "_event_region":
        from src.map_agent.actor_profile import region_for
        from src.map_agent.save import _place
        _, state, country = _place(entity.get("location"))
        return region_for(country, state) or None
    if field == "region" and not value and entity.get("_entity_type", "actor") == "actor":
        from src.map_agent.actor_profile import region_for
        return region_for(entity.get("country"), entity.get("state")) or None
    if field == "rankings":
        from src.map_agent.rankings import is_university, PUBLISHERS
        if not is_university(entity):
            return ""
        return "\n".join(dict.fromkeys(
            f"{r['system']}: {r.get('rank', '')} ({r.get('year', '')}), "
            f"{r.get('subject') if r.get('scope') == 'subject' else 'Overall'}; "
            f"{r.get('source_url', '')}"
            for r in (value or []) if isinstance(r, dict) and r.get("system") in PUBLISHERS))
    if field == "organizations":
        return "\n".join(
            f"{x.get('actor_name')}{' — ' + x['title'] if x.get('title') else ''}"
            for x in (value or []) if x.get("actor_name"))
    return value


def _selected(result: dict) -> dict[str, list]:
    """Selected entities per type, best-first (the pipeline already ordered them)."""
    out = {}
    for key, _ in GROUPS:
        items = (result.get("entities") or {}).get(key) or []
        picked = [e for e in items if e.get("_rank")]
        selected = [e for e in items if e.get("_selected") is True]
        has_selection = any("_selected" in e for e in items)
        # If nothing was ranked (a plain topic map with no requirements), the
        # whole list IS the result — export all of it rather than an empty file.
        out[key] = picked or (selected if has_selection else items)
    # A selection that rejected every candidate still has to export something.
    # The user paid to discover them, and an empty workbook is not a valid file.
    if not any(out.values()):
        return {key: (result.get("entities") or {}).get(key) or [] for key, _ in GROUPS}
    return out


def to_xlsx(result: dict, request: str = "") -> bytes:
    """Render the map as an .xlsx: one sheet per non-empty entity type."""
    wb = Workbook()
    wb.remove(wb.active)                       # drop the default empty sheet
    selected = _selected(result)

    for key, label in GROUPS:
        rows = selected.get(key) or []
        if not rows:
            continue
        ws = wb.create_sheet(title=label)
        cols = FIELDS[key]
        headers = ["#"] + [h for _, h in cols] + ["Why relevant", "Sources"]

        for c, head in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=head)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)

        for r, e in enumerate(rows, start=2):
            ws.cell(row=r, column=1, value=e.get("_rank") or (r - 1))
            for c, (field, _) in enumerate(cols, start=2):
                ws.cell(row=r, column=c, value=_field_value(e, field))
            ws.cell(row=r, column=len(cols) + 2, value=e.get("_why"))
            ws.cell(row=r, column=len(cols) + 3, value=_sources_text(e))

        # Reasonable widths; wrap the long text columns.
        for c in range(1, len(headers) + 1):
            letter = get_column_letter(c)
            ws.column_dimensions[letter].width = 10 if c == 1 else 26
            for r in range(2, len(rows) + 2):
                ws.cell(row=r, column=c).alignment = Alignment(
                    vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"

    if not wb.sheetnames:                      # openpyxl cannot save a sheetless workbook
        wb.create_sheet(title="Map")["A1"] = "This map has no entities to export."

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _text(shape, s, size, color, *, font=SANS, bold=False, align=None):
    """Set a shape's text with one run's formatting."""
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    if align is not None:
        p.alignment = align
    run = p.add_run()
    run.text = s
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = font
    run.font.color.rgb = color
    return tf


def _box(slide, x, y, w, h, fill=None, line=None):
    """A rounded rectangle at inch coordinates, optionally filled."""
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    shp.adjustments[0] = 0.06
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
    shp.shadow.inherit = False
    return shp


def _tb(slide, x, y, w, h):
    """A plain textbox at inch coordinates."""
    return slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))


def _kicker_and_title(slide, kicker, title):
    """The recurring header: small orange eyebrow over a large Cambria title."""
    _text(_tb(slide, 0.7, 0.45, 11, 0.3), kicker.upper(), 11.5, ACCENT, bold=True)
    _text(_tb(slide, 0.65, 0.78, 12, 0.9), title, 27, INK, font=SERIF, bold=True)


def to_pptx(result: dict, request: str = "") -> bytes:
    """Render the map as a branded .pptx: a cover, then one slide per entity."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)           # 16:9
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    selected = _selected(result)
    counts = {k: len(v) for k, v in selected.items()}
    total = sum(counts.values())

    # ---------- Cover ----------
    s = prs.slides.add_slide(blank)
    _text(_tb(s, 0.9, 1.5, 11, 0.3), "US INNOVATION MAP", 13, ACCENT, bold=True)
    title = (request.strip() or "Research organizations, people & events")
    _text(_tb(s, 0.85, 1.95, 11.6, 1.8), title, 40, INK, font=SERIF, bold=True)
    _box(s, 0.9, 3.9, 2.0, 0.05, fill=ACCENT)   # accent rule
    # count chips
    chips = [(counts.get("actor", 0), "Organizations"),
             (counts.get("person", 0), "People"),
             (counts.get("event", 0), "Events")]
    x = 0.9
    for n, lbl in chips:
        if not n:
            continue
        w = 0.5 + 0.11 * len(lbl)
        _box(s, x, 4.3, w, 0.5, fill=GRAY)
        _text(_tb(s, x + 0.15, 4.38, w, 0.35), f"{n}  {lbl}", 12, INK, bold=True)
        x += w + 0.25
    _text(_tb(s, 0.9, 6.7, 10, 0.3), "UM6P Intelligence  ·  cited web sources",
          12, MUTED)

    # ---------- One slide per record (2 Nov 2026: never "continued") ----------
    for key, label in GROUPS:
        for e in selected.get(key) or []:
            entries = []
            for field, head in FIELDS[key]:
                if field in ("name", "full_name", "website", "_review", "_found_by") or field in WHY_FIELDS:
                    continue
                value = _field_value(e, field)
                if value in (None, ""):
                    continue
                entries.append((head, " ".join(str(value).split())))
            # One Location line on a slide, as on the card: City, State, Region, Country.
            place = [v for h, v in entries if h in ("City", "State", "Region", "Country")]
            if len(place) > 1:
                at = next(i for i, (h, _) in enumerate(entries) if h in ("City", "State", "Region", "Country"))
                entries = [x for x in entries if x[0] not in ("City", "State", "Region", "Country")]
                entries.insert(at, ("Location", ", ".join(place)))
            # Fit one slide: shorten long values, then stop with a pointer to the Excel.
            budget, used, page, cut = 24, 0, [], False
            for head, value in entries:
                if len(value) > 330:
                    value = value[:330].rsplit(" ", 1)[0] + "…"
                lines = (len(head) + len(value)) // 82 + 1
                if used + lines > budget:
                    cut = True
                    break
                page.append((head, value)); used += lines
            s = prs.slides.add_slide(blank)
            rank = f"  ·  #{e['_rank']}" if e.get("_rank") else ""
            _kicker_and_title(s, {"actor": "Organization", "person": "Person", "event": "Event"}[key].upper() + rank, _name(e))

            # left column: the record's facts, in the card's order, in a gray card
            _box(s, 0.65, 1.75, 7.2, 5.15, fill=GRAY)
            tf = _tb(s, 0.95, 1.95, 6.7, 4.8).text_frame
            tf.word_wrap = True
            rows = page + ([("More", "the full record is in the Excel export")] if cut else [])
            for i, (head, v) in enumerate(rows):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                r1 = p.add_run(); r1.text = f"{head}:  "
                r1.font.size = Pt(10.5); r1.font.bold = True; r1.font.name = SANS; r1.font.color.rgb = INK
                r2 = p.add_run(); r2.text = v
                r2.font.size = Pt(10.5); r2.font.name = SANS; r2.font.color.rgb = MUTED if head == "More" else INK
                p.space_after = Pt(4)

            # right column: why it is on this map (peach) over sources
            why = [(h, _field_value(e, f)) for f, h in FIELDS[key] if f in WHY_FIELDS and _field_value(e, f)]
            _box(s, 8.05, 1.75, 4.6, 2.6, fill=PEACH)
            _box(s, 8.05, 1.75, 0.08, 2.6, fill=ACCENT)   # left accent stripe
            _text(_tb(s, 8.35, 1.95, 4.1, 0.3), "WHY IT'S ON THIS MAP", 11, ACCENT, bold=True)
            wf = _tb(s, 8.35, 2.32, 4.1, 1.95).text_frame
            wf.word_wrap = True
            why_rows = why or [("", e.get("_why") or "—")]
            for i, (h, v) in enumerate(why_rows):
                p = wf.paragraphs[0] if i == 0 else wf.add_paragraph()
                text = " ".join(str(v).split())
                if h:
                    r = p.add_run(); r.text = f"{h}:  "; r.font.size = Pt(10.5); r.font.bold = True
                    r.font.name = SANS; r.font.color.rgb = INK
                r = p.add_run(); r.text = text[:260] + ("…" if len(text) > 260 else "")
                r.font.size = Pt(10.5); r.font.name = SANS; r.font.color.rgb = INK
                p.space_after = Pt(3)

            srcs = [x.get("url") for x in (e.get("sources") or []) if x.get("url")]
            web = e.get("website") or (_field_value(e, "_linkedin") if key == "person" else None)
            _box(s, 8.05, 4.55, 4.6, 2.35, fill=GRAY)
            _text(_tb(s, 8.35, 4.72, 4.1, 0.3), "SOURCES", 11, ACCENT, bold=True)
            links = ([web] if web else []) + [u for u in srcs if u != web]
            sf = _tb(s, 8.35, 5.08, 4.1, 1.7).text_frame
            sf.word_wrap = True
            for i, u in enumerate(links[:6]):
                p = sf.paragraphs[0] if i == 0 else sf.add_paragraph()
                r = p.add_run(); r.text = u
                r.font.size = Pt(9.5); r.font.name = SANS; r.font.color.rgb = MUTED
            if not links:
                r = sf.paragraphs[0].add_run(); r.text = "none recorded"
                r.font.size = Pt(10); r.font.name = SANS; r.font.color.rgb = MUTED

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
