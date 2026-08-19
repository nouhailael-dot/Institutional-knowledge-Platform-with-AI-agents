"""Sector relevance filtering for discovery records."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def load_seeded_sector_codes(project_root: Optional[Path] = None) -> set[str]:
    """Read sector codes from the existing seed script without importing DB code."""
    root = project_root or Path(__file__).resolve().parents[2]
    seed_path = root / "scripts" / "seed_sectors.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "SECTORS" in names:
                return {str(item[0]).upper() for item in ast.literal_eval(node.value)}
    raise RuntimeError(f"could not find SECTORS in {seed_path}")


def filter_relevant_records(
    records: Iterable[dict[str, object]],
    *,
    valid_sector_codes: Optional[set[str]] = None,
    project_root: Optional[Path] = None,
) -> list[dict[str, object]]:
    valid_codes = valid_sector_codes or load_seeded_sector_codes(project_root)
    if not valid_codes:
        raise RuntimeError("sector code set is empty; refusing to silently filter everything")

    kept: list[dict[str, object]] = []
    dropped = 0
    for record in records:
        record_codes = [str(code).upper() for code in record.get("sector_codes", [])]
        matched = [code for code in record_codes if code in valid_codes]
        if matched:
            enriched = record.copy()
            enriched["sector_codes"] = matched
            kept.append(enriched)
        else:
            dropped += 1

    if dropped:
        logger.warning("filtered %d record(s) with no seeded-sector match", dropped)
    if not kept:
        logger.warning("relevance filtering matched zero records")
    return kept
