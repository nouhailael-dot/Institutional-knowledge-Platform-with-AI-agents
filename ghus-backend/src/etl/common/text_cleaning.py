"""
Shared text-cleaning utilities used by all ETL translators.

These are deliberately small, pure functions — each does one thing.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Values that should be normalized to NULL across all spreadsheets.
# Update with care — these are the "missing" tokens we'll never accept as data.
MISSING_TOKENS = {
    "", "n/a", "na", "n.a.", "unknown", "-", "—", "--",
    "null", "none", "tbd", "to be determined", "?",
}


def clean_text(value: object) -> Optional[str]:
    """Return a cleaned string, or None if the value should be treated as missing.

    - Strips whitespace
    - Collapses runs of internal whitespace
    - Normalizes Unicode (e.g., curly quotes → straight)
    - Returns None for any MISSING_TOKEN match (case-insensitive)
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    # Normalize unicode form so curly quotes etc. don't fragment our matching
    value = unicodedata.normalize("NFKC", value)
    # Collapse all internal whitespace (including \n, \t) to single spaces
    value = re.sub(r"\s+", " ", value).strip()

    if value.lower() in MISSING_TOKENS:
        return None
    return value or None


def slugify(value: str) -> str:
    """Convert a hub or actor name into a URL-safe slug.

    Examples:
        'UC Davis / Sacramento Valley' -> 'uc-davis-sacramento-valley'
        'Bay Area AI Hub (Stanford – UC Berkeley)' -> 'bay-area-ai-hub-stanford-uc-berkeley'
    """
    if not value:
        raise ValueError("Cannot slugify empty value")
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    # Replace any non-alphanumeric sequence with a single hyphen
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


# Detect ecosystem-mapping section header rows. They use these visual markers.
SECTION_HEADER_MARKERS = ("▶", "▸", "►", "▼")


def is_section_header(row_values: list[object]) -> bool:
    """A section header row has a value only in column 1 (Actor Name)
    and nothing in any other column."""
    if not row_values:
        return False
    first = row_values[0]
    others = row_values[1:]
    has_first = first is not None and str(first).strip() != ""
    has_others = any(v is not None and str(v).strip() != "" for v in others)
    return has_first and not has_others


def parse_sector_from_category(category: Optional[str]) -> Optional[str]:
    """Extract a sector code from a value like 'Ecosystem Hub (Agriculture)'.

    Returns the sector code (AGRI, AI, WATER, etc.) or None if unrecognized.
    """
    if not category:
        return None

    # Map common phrases to sector codes
    sector_keywords: list[tuple[str, str]] = [
        # More specific patterns first
        ("agriculture", "AGRI"),
        ("ag-biotech", "AGRI"),
        ("agritech", "AGRI"),
        ("artificial intelligence", "AI"),
        (" ai ", "AI"),
        ("water", "WATER"),
        ("energy", "ENERGY"),
        ("climate", "ENERGY"),  # climate hubs are categorized under energy/sustainability
        ("mining", "MINING"),
        ("mineral", "MINING"),
        ("metallurgy", "MINING"),
        ("chemical", "CHEM"),
        ("chemistry", "CHEM"),
        ("catalysis", "CHEM"),
        ("materials science", "CHEM"),
        ("sustainability", "SUSTAIN"),
        ("earth system", "SUSTAIN"),
        ("urban system", "SUSTAIN"),
        ("health", "HEALTH"),
        ("medicine", "HEALTH"),
        ("biomedical", "HEALTH"),
    ]
    lowered = " " + category.lower() + " "
    for keyword, code in sector_keywords:
        if keyword in lowered:
            return code
    return None


# UN Mapping 
def parse_un_name_acronym(raw: str) -> tuple[str, Optional[str]]:
    """Parse a UN entity name string, returning (full_name, acronym).

    Handles these patterns seen in the UN Mapping spreadsheet:
        'United Nations Development Programme (UNDP)'   → ('United Nations Development Programme', 'UNDP')
        'United Nations Institute for Training and research UNITAR'
            → ('United Nations Institute for Training and Research', 'UNITAR')
        'UNESCO — United Nations Educational, Scientific and Cultural Organization'
            → ('United Nations Educational, Scientific and Cultural Organization', 'UNESCO')
        'IBRD : International Bank for Reconstruction and development'
            → ('International Bank for Reconstruction and Development', 'IBRD')
        'UNIDO'  → ('UNIDO', 'UNIDO')
        'UN Women' → ('UN Women', None)
    """
    if not raw:
        return ("", None)
    cleaned = re.sub(r"\s+", " ", raw).strip()

    # Pattern 1: 'Full Name (ACRONYM)'
    m = re.match(r"^(.+?)\s*\(([A-Z][A-Z0-9]{1,15})\)\s*$", cleaned)
    if m:
        return (m.group(1).strip(), m.group(2).strip())

    # Pattern 2: 'ACRONYM — Full Name' or 'ACRONYM - Full Name'
    m = re.match(r"^([A-Z][A-Z0-9]{1,15})\s*[—\-]\s*(.+)$", cleaned)
    if m:
        return (m.group(2).strip(), m.group(1).strip())

    # Pattern 3: 'ACRONYM : Full Name'
    m = re.match(r"^([A-Z][A-Z0-9]{1,15})\s*:\s*(.+)$", cleaned)
    if m:
        return (m.group(2).strip(), m.group(1).strip())

    # Pattern 4: 'Full Name ACRONYM' (acronym at end, no parens — rare but appears in UN data)
    m = re.match(r"^(.+?)\s+([A-Z][A-Z0-9]{2,15})\s*$", cleaned)
    if m and len(m.group(1).split()) >= 3:
        return (m.group(1).strip(), m.group(2).strip())

    # Pattern 5: bare acronym (no full name)
    if re.match(r"^[A-Z][A-Z0-9 ]{1,20}$", cleaned):
        return (cleaned, cleaned)

    # Pattern 6: plain name without recognizable acronym (e.g., 'UN Women')
    return (cleaned, None)