"""Gap semantics for enrichment.

Only NULL, empty strings, and explicit placeholder values are gaps. Existing
non-placeholder content is never treated as missing.
"""

from __future__ import annotations

from typing import Any


PLACEHOLDER_VALUES = frozenset(
    {
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "not applicable",
        "not available",
        "tba",
        "tbd",
        "to be announced",
        "to be determined",
        "unknown",
    }
)


def is_gap(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return not normalized or normalized in PLACEHOLDER_VALUES


def is_present(value: Any) -> bool:
    return not is_gap(value)


def sql_gap_condition(column_name: str) -> str:
    placeholders = ", ".join(f"'{value}'" for value in sorted(PLACEHOLDER_VALUES))
    return (
        f"{column_name} IS NULL OR "
        f"NULLIF(BTRIM(CAST({column_name} AS text)), '') IS NULL OR "
        f"LOWER(BTRIM(CAST({column_name} AS text))) IN ({placeholders})"
    )
