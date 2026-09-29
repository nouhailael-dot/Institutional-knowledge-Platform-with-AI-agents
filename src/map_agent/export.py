"""Export a map to a spreadsheet (.xlsx) or a deck (.pptx).

Both take the pipeline result and write ONLY the selected entities (the ranked
matches), since that is what a user hands to the team. Nothing here calls an
LLM — it is pure formatting of data already produced.

A downloaded file also sidesteps the in-memory-only storage problem: it survives
the server restarts that otherwise wipe a map.
"""

import io
import json
import textwrap

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

# --- UM6P brand palette (from the team's own deck) ---
ACCENT = RGBColor(0xD7, 0x41, 0x0B)   # deep orange
INK    = RGBColor(0x3D, 0x39, 0x35)   # warm near-black
GRAY   = RGBColor(0xED, 0xED, 0xED)   # light card fill
PEACH  = RGBColor(0xF6, 0xD7, 0xCB)   # orange-tint card fill
MUTED  = RGBColor(0x6B, 0x6B, 0x6B)   # secondary text
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
SERIF  = "Cambria"                    # titles
SANS   = "Calibri"                    # body / labels

# Human-facing columns per entity type: (field, header). Order matters — this is
# the column order in the sheet and the field order on a slide.
FIELDS = {
    "actor": [
        ("name", "Name"), ("actor_type", "Type"), ("description", "Description"),
        ("location_city", "City"), ("state", "State"),
        ("primary_technical_focus", "Focus"), ("technical_approach", "Approach"),
        ("current_activities", "Current activities"),
        ("funding_summary", "Funding"), ("rankings", "University rankings"), ("website", "Website"),
        ("other_names", "Other names"), ("category_note", "Category review"),
        ("country", "Country"), ("region", "Region"), ("multi_location", "Multiple locations"),
        ("sector", "Sector"), ("mapped_topic", "Mapped topic"),
        ("match_strength", "Topic match"), ("match_explanation", "Why it matched"),
        ("international_connections", "International / Africa / Morocco connections"),
        ("actor_relationships", "Organization relationships"), ("category_details", "Category-specific information"),
    ],
    "person": [
        ("full_name", "Name"), ("organizations", "Organizations"),
        ("title", "Title"), ("bio", "Bio"),
        ("email", "Email"), ("linkedin_url", "LinkedIn"),
    ],
    "event": [
        ("name", "Name"), ("event_type", "Type"), ("description", "Description"),
        ("location", "Location"), ("next_date", "Next date"),
        ("recurring_pattern", "Recurs"), ("sponsoring_orgs", "Sponsors"),
        ("thematic_focus", "Themes"), ("expected_attendance", "Attendance"),
        ("access_type", "Access"), ("website", "Website"),
    ],
}

GROUPS = [("actor", "Organizations"), ("person", "People"), ("event", "Events")]

_HEADER_FILL = PatternFill("solid", fgColor="D7410B")   # UM6P brand orange
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _name(e: dict) -> str:
    return e.get("full_name") or e.get("name") or "—"


def _sources_text(e: dict) -> str:
    return "\n".join(s.get("url", "") for s in (e.get("sources") or []) if s.get("url"))


def _field_value(entity: dict, field: str):
    """Human-readable value for scalar and relationship fields."""
    value = entity.get(field)
    if field in ("category_details", "actor_relationships"):
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in (value or []))
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

    # ---------- One slide per entity ----------
    for key, label in GROUPS:
        for e in selected.get(key) or []:
            entries = []
            for field, head in FIELDS[key]:
                value = _field_value(e, field)
                if value is None or value == "" or field in ("name", "full_name", "website"):
                    continue
                for part in textwrap.wrap(str(value), width=420, replace_whitespace=False):
                    entries.append((head, part))
            pages, page, used = [], [], 0
            for head, value in entries:
                # Approximate wrapped lines including label and paragraph spacing.
                lines = (len(head) + len(value)) // 70 + 2
                if page and used + lines > 21:
                    pages.append(page); page, used = [], 0
                page.append((head, value)); used += lines
            pages.append(page)
            for page_number, entries_page in enumerate(pages):
                s = prs.slides.add_slide(blank)
                rank = f"  ·  #{e['_rank']}" if e.get("_rank") else ""
                _kicker_and_title(s, label[:-1].upper() + rank, _name(e) + (f" · continued {page_number + 1}" if page_number else ""))

                # left column: the schema fields, in a gray card
                _box(s, 0.65, 1.75, 7.2, 5.15, fill=GRAY)
                body = _tb(s, 0.95, 1.95, 6.7, 4.8)
                tf = body.text_frame; tf.word_wrap = True
                first = True
                for head, v in entries_page:
                    p = tf.paragraphs[0] if first else tf.add_paragraph()
                    first = False
                    r1 = p.add_run(); r1.text = f"{head}:  "
                    r1.font.size = Pt(12); r1.font.bold = True
                    r1.font.name = SANS; r1.font.color.rgb = INK
                    r2 = p.add_run(); r2.text = str(v)
                    r2.font.size = Pt(12); r2.font.name = SANS; r2.font.color.rgb = INK
                    p.space_after = Pt(7)

                # right column: why-relevant (peach) over sources
                _box(s, 8.05, 1.75, 4.6, 2.6, fill=PEACH)
                _box(s, 8.05, 1.75, 0.08, 2.6, fill=ACCENT)   # left accent stripe
                _text(_tb(s, 8.35, 1.95, 4.1, 0.3), "WHY RELEVANT", 11, ACCENT, bold=True)
                _text(_tb(s, 8.35, 2.35, 4.1, 1.9),
                      e.get("_why") or "—", 13, INK, bold=True)

                srcs = [x.get("url") for x in (e.get("sources") or []) if x.get("url")]
                web = e.get("website")
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
                    _text(sf.paragraphs[0]._parent if False else _tb(s, 8.35, 5.08, 4.1, 0.4),
                          "none recorded", 10, MUTED)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
