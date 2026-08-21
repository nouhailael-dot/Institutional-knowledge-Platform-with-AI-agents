"""
header_resolver.py — resolve spreadsheet columns by HEADER NAME, not position.

The new event spreadsheets reordered columns (e.g. 'Official website' moved
before 'Location'). Any translator that reads by fixed index (row[EM_LOCATION])
will silently put the wrong data in the wrong field. This resolver builds a
{normalized_header: column_index} map from the real header row, so translators
ask for a column by name and get the right index regardless of order.

Normalization makes matching robust to the differences we actually saw:
  * case:            'Official Website' vs 'Official website'
  * whitespace:      trailing spaces, doubled spaces, newlines in headers
  * the known typo:  'Geograpghy Reach Score' == 'Geography Reach Score'

Drop into src/etl/common/.
"""
from __future__ import annotations

import re
import unicodedata


# Canonical fixes for headers known to vary between file versions. Keyed by the
# normalized form; value is the canonical field the translator will ask for.
HEADER_ALIASES = {
    "geograpghy reach score": "geography reach score",   # typo in v8
    "official website": "official website",
}


def normalize_header(value) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return HEADER_ALIASES.get(s, s)


class HeaderMap:
    """Maps header names to 0-indexed column positions for one sheet."""

    def __init__(self, header_row: list):
        self.by_name: dict[str, int] = {}
        for idx, cell in enumerate(header_row):
            name = normalize_header(cell)
            if name and name not in self.by_name:
                self.by_name[name] = idx
        self.raw = list(header_row)

    def index(self, *names: str):
        """First matching column index for any of the given header names, else None."""
        for n in names:
            i = self.by_name.get(normalize_header(n))
            if i is not None:
                return i
        return None

    def get(self, row: list, *names: str, default=None):
        """Value from `row` for the first matching header name."""
        i = self.index(*names)
        if i is None or i >= len(row):
            return default
        return row[i]

    def missing(self, required: list[str]) -> list[str]:
        """Which required headers are absent (for pre-flight validation)."""
        return [r for r in required if self.index(r) is None]

    def __contains__(self, name: str) -> bool:
        return self.index(name) is not None


def find_header_row(ws, expected_any: list[str], max_scan: int = 8):
    """Return (header_row_values, data_start_row_number).

    Scans the first `max_scan` rows for the one containing the most of the
    expected header names. Handles the two-row banner+header layout without a
    hardcoded row number, so a future file that adds a title row won't break it.
    """
    expected = {normalize_header(e) for e in expected_any}
    best_row, best_hits, best_idx = None, -1, 1
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True), 1):
        names = {normalize_header(c) for c in row if c is not None}
        hits = len(names & expected)
        if hits > best_hits:
            best_row, best_hits, best_idx = list(row), hits, i
    return best_row, best_idx + 1