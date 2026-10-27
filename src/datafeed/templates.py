"""The official GHUS Data Feed templates: one Excel workbook and one CSV per type.

Workbook sheets:
    Instructions   what to do, the rules, and what happens after upload
    <Records>      the sheet that is read: headers only, dropdowns on every
                   controlled column, required columns marked " *" and shaded
    Field Guide    every column: required, what to enter, allowed values, example,
                   and where an admitted record keeps it
    Examples       example rows, each named "EXAMPLE - ..." (never read)
    Lists          hidden: the dropdown values and the template's identity

The CSV carries the same headers; it is checked the same way after upload.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from src.datafeed import contract
from src.datafeed.contract import EXAMPLE_PREFIX, Field

DATA_ROWS = 1000
MARKER = "ghus-datafeed"
_HEADER = PatternFill("solid", fgColor="1F3A5F")
_REQUIRED = PatternFill("solid", fgColor="7A1F2B")
_CATEGORY_BOX = PatternFill("solid", fgColor="3E5C76")
_WHITE = Font(bold=True, color="FFFFFF")
_TITLE = Font(bold=True, size=14)
_STRIP = (" ", "/", "(", ")", "&", "-")

EXAMPLES: dict[str, list[dict[str, str]]] = {
    "actor": [
        {"name": "Prairie Water Lab", "alternate_names": "PWL",
         "website": "https://prairiewaterlab.example", "actor_category": "Company / Corporate Actor",
         "category_type": "SME",
         "description": "A company that builds low-cost water-quality sensors for farms.",
         "primary_sector": "Water", "city": "Wichita", "state_code": "Kansas",
         "country": "United States", "source_url": "https://prairiewaterlab.example/about",
         "recent_activity": "Started a sensor pilot with Kansas State University.",
         "recent_activity_date": "2026-05-14", "funding_signal": "USDA SBIR Phase I, 2025",
         "ownership_and_size": "Private, about 25 employees"},
        {"name": "Center for Arid Groundwater Research",
         "website": "https://cagr.example.edu",
         "actor_category": "Research Center / Institute / Laboratory",
         "description": "A university research center studying aquifer recharge.",
         "primary_sector": "Water", "city": "Tucson", "state_code": "AZ",
         "country": "United States", "parent_name": "University of Arizona",
         "parent_relationship": "Unit of", "source_url": "https://cagr.example.edu/about"},
    ],
    "person": [
        {"name": "Ana Ruiz", "role": "Professor of Hydrology",
         "affiliation": "University of Arizona",
         "department": "Department of Hydrology and Atmospheric Sciences",
         "bio_url": "https://www.arizona.example.edu/people/ana-ruiz",
         "linkedin_url": "https://www.linkedin.com/in/example-ana-ruiz",
         "bio": "Hydrologist working on groundwater recharge in arid regions.",
         "expertise": "groundwater; aquifer recharge", "city": "Tucson", "state_code": "Arizona",
         "country": "United States", "sectors": "Water", "topic": "Water",
         "source_url": "https://www.arizona.example.edu/people/ana-ruiz"},
    ],
    "event": [
        {"name": "Great Plains Water Summit 2027", "event_type": "Summit",
         "organizer": "Kansas Water Office", "start_date": "2027-04-02",
         "end_date": "2027-04-03", "event_format": "Hybrid", "venue": "Century II",
         "city": "Wichita", "state_code": "Kansas", "country": "United States",
         "sectors": "Water; Agriculture", "topic": "Water",
         "themes": "groundwater policy; irrigation technology",
         "description": "A two-day summit on water management in the Great Plains.",
         "website": "https://greatplainswatersummit.example", "recurring_pattern": "Annual",
         "source_url": "https://greatplainswatersummit.example/agenda"},
    ],
}


def range_name(label: str) -> str:
    """The defined name holding one category's types: its label without separators."""
    return "T_" + re.sub(r"[^A-Za-z0-9]", "", label)


def _type_formula(cell: str) -> str:
    expr = cell
    for ch in _STRIP:
        expr = f'SUBSTITUTE({expr},"{ch}","")'
    return f'INDIRECT("T_"&{expr})'


def _labels(vocab: dict[str, Any], name: str) -> list[str]:
    return [item["label"] for item in vocab.get(name) or []]


def _allowed(field: Field, vocab: dict[str, Any]) -> str:
    if field.vocab == "category_types":
        return "Depends on the Actor Category (see the dropdown)"
    if not field.vocab:
        return ""
    labels = _labels(vocab, field.vocab)
    if field.vocab == "states":
        return "Any US state: full name or two-letter code"
    text_ = "; ".join(labels) if labels else "Not available: the database could not be read"
    if not field.strict:
        text_ += " (others accepted as written)"
    return text_


def _guide_rows(record_type: str, vocab: dict[str, Any]) -> list[list[str]]:
    rows = []
    for field in contract.fields(record_type):
        categories = contract.box_categories(field)
        what = field.description
        if categories:
            names = [i["label"] for i in vocab["actor_categories"] if i["code"] in categories]
            what = f"Only for {' or '.join(names)}. {what}"
        rows.append([field.template_header, "Yes" if field.required else "No", what,
                     _allowed(field, vocab), field.example, field.target])
    return rows


def build_xlsx(record_type: str, vocab: dict[str, Any]) -> bytes:
    fields = contract.fields(record_type)
    wb = Workbook()
    intro = wb.active
    intro.title = "Instructions"
    data = wb.create_sheet(contract.SHEET_NAMES[record_type])
    guide = wb.create_sheet("Field Guide")
    examples = wb.create_sheet("Examples")
    lists = wb.create_sheet("Lists")

    # ---- Instructions
    label = contract.TYPE_LABELS[record_type]
    lines = [
        (f"GHUS Data Feed - {label}", _TITLE),
        (f"Template version {contract.TEMPLATE_VERSION}", None),
        ("", None),
        ("How to fill it", Font(bold=True)),
        (f"1. Enter one record per row on the '{data.title}' sheet, starting on row 2.", None),
        ("2. Columns marked * are required. Use the dropdowns where they are offered.", None),
        ("3. Dates are MM/DD/YYYY (for example 04/02/2027). Separate several values in one "
         "cell with ';'.", None),
        ("4. Do not rename, reorder or delete the column headers.", None),
        ("5. Type values only: formulas, macros and links to other files are not accepted.",
         None),
        ((f"6. At most {DATA_ROWS} rows and 5 MB per file. Example rows are on the "
          "'Examples' sheet and are never imported."), None),
        (("7. Only enter what a real, checkable source states. Leave a cell empty when "
          "unknown - never guess."), None),
        (("8. Compass imports and Notion CRM exports use this same template: copy their "
          "rows into these columns. The same checks apply."), None),
        ("", None),
        ("What happens after upload", Font(bold=True)),
        (("The file is checked row by row. You see every error with its row number, and "
          "a preview of the records, before anything is saved."), None),
        (("When you confirm, the records go to Review. A GHUS reviewer decides each one: "
          "add it, match it to an existing record, or reject it."), None),
        (("Nothing becomes GHUS Verified because it was uploaded. Your values are kept as "
          "you entered them, labelled as GHUS-supplied."), None),
        ("See the 'Field Guide' sheet for what every column means.", None),
    ]
    for row, (line, font) in enumerate(lines, 1):
        cell = intro.cell(row=row, column=1, value=line)
        if font:
            cell.font = font
    intro.column_dimensions["A"].width = 110

    # ---- Lists (hidden): dropdown values and the template's identity
    lists["A1"] = MARKER
    lists["B1"] = record_type
    lists["C1"] = contract.TEMPLATE_VERSION
    column = 1
    ranges: dict[str, str] = {}

    def put_list(name: str, values: list[str]) -> str | None:
        nonlocal column
        if not values:
            return None
        column += 1
        letter = get_column_letter(column)
        lists.cell(row=2, column=column, value=name)
        for offset, value in enumerate(values, 3):
            lists.cell(row=offset, column=column, value=value)
        return (f"{quote_sheetname(lists.title)}!${letter}$3:${letter}$"
                f"{len(values) + 2}")

    for field in fields:
        if field.vocab and field.vocab not in ranges and field.vocab != "category_types":
            ref = put_list(field.vocab, _labels(vocab, field.vocab))
            if ref:
                ranges[field.vocab] = ref
    if record_type == "actor":
        for category in vocab["actor_categories"]:
            types = [t["label"] for t in vocab["category_types"][category["code"]]]
            ref = put_list(f"types:{category['code']}", types)
            wb.defined_names[range_name(category["label"])] = DefinedName(
                range_name(category["label"]), attr_text=ref)
    lists.sheet_state = "veryHidden"

    # ---- the data sheet
    category_letter = None
    for index, field in enumerate(fields, 1):
        letter = get_column_letter(index)
        cell = data.cell(row=1, column=index, value=field.template_header)
        cell.font = _WHITE
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.fill = (_REQUIRED if field.required
                     else _CATEGORY_BOX if field.category else _HEADER)
        note = ("REQUIRED. " if field.required else "") + field.description
        cell.comment = Comment(note[:1000], "GHUS Data Feed")
        data.column_dimensions[letter].width = 34 if field.kind == "long_text" else 22
        if field.key == "actor_category":
            category_letter = letter
        target = f"{letter}2:{letter}{DATA_ROWS + 1}"
        if field.kind == "date":
            data.column_dimensions[letter].number_format = "mm/dd/yyyy"
        if field.vocab == "category_types" and category_letter:
            rule = DataValidation(type="list", formula1=_type_formula(f"${category_letter}2"),
                                  allow_blank=True)
        elif field.kind == "enum" and field.vocab in ranges:
            rule = DataValidation(type="list", formula1=ranges[field.vocab],
                                  allow_blank=True)
        else:
            rule = None
        if rule is not None:
            rule.showErrorMessage = field.strict
            rule.errorStyle = "stop" if field.strict else "warning"
            rule.error = f"Choose a value from the {field.header} list."
            rule.errorTitle = field.header
            rule.prompt = field.description[:250]
            rule.showInputMessage = True
            data.add_data_validation(rule)
            rule.add(target)
    data.freeze_panes = "B2"
    data.row_dimensions[1].height = 45
    first_box = next((i for i, f in enumerate(fields, 1) if f.category), None)
    if first_box:
        # Category-specific boxes are grouped: collapse them, fill only your category's.
        data.column_dimensions.group(get_column_letter(first_box),
                                     get_column_letter(len(fields)), hidden=False,
                                     outline_level=1)

    # ---- Field Guide
    guide.append(["Column", "Required", "What to enter", "Allowed values", "Example",
                  "Kept in (Architecture V2)"])
    for cell in guide[1]:
        cell.font, cell.fill = _WHITE, _HEADER
    for row in _guide_rows(record_type, vocab):
        guide.append(row)
    for letter, width in zip("ABCDEF", (34, 10, 70, 60, 34, 40)):
        guide.column_dimensions[letter].width = width
    for row in guide.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # ---- Examples (never read)
    examples.append([("Example rows: copy the shape, not the values. This sheet is "
                      "never imported.")])
    examples.append([f.template_header for f in fields])
    for example in EXAMPLES[record_type]:
        values = dict(example)
        values["name"] = f"{EXAMPLE_PREFIX} - {values['name']}"
        examples.append([values.get(f.key, "") for f in fields])
    for cell in examples[2]:
        cell.font, cell.fill = _WHITE, _HEADER

    wb.properties.title = f"GHUS Data Feed template - {label}"
    wb.properties.keywords = f"{MARKER};{record_type};{contract.TEMPLATE_VERSION}"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_csv(record_type: str) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow(
        [f.template_header for f in contract.fields(record_type)])
    # UTF-8 with a byte-order mark, so Excel opens accents correctly.
    return ("﻿" + out.getvalue()).encode("utf-8")


def file_name(record_type: str, extension: str) -> str:
    return f"{contract.FILE_STEMS[record_type]}.{extension}"
