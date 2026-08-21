"""Sector relevance filtering for discovery records."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

IN_SECTOR = "in_sector"
OUT_OF_SECTOR = "out_of_sector"


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
    return [
        record
        for record in classify_sector_matches(
            records,
            valid_sector_codes=valid_sector_codes,
            project_root=project_root,
        )
        if record["sector_match"] == IN_SECTOR
    ]


def classify_sector_matches(
    records: Iterable[dict[str, object]],
    *,
    valid_sector_codes: Optional[set[str]] = None,
    project_root: Optional[Path] = None,
) -> list[dict[str, object]]:
    raw_valid_codes = load_seeded_sector_codes(project_root) if valid_sector_codes is None else valid_sector_codes
    valid_codes = {str(code).upper() for code in raw_valid_codes}
    if not valid_codes:
        raise RuntimeError("sector code set is empty; refusing to silently filter everything")

    classified: list[dict[str, object]] = []
    in_sector = 0
    out_of_sector = 0
    for record in records:
        record_codes = [str(code).upper() for code in record.get("sector_codes", [])]
        matched = [code for code in record_codes if code in valid_codes]
        enriched = record.copy()
        if matched:
            enriched["sector_codes"] = matched
            enriched["sector_match"] = IN_SECTOR
            in_sector += 1
        else:
            enriched["sector_codes"] = record_codes
            enriched["sector_match"] = OUT_OF_SECTOR
            out_of_sector += 1
        classified.append(enriched)

    if out_of_sector:
        logger.warning("classified %d record(s) as out_of_sector with no seeded-sector match", out_of_sector)
    if not in_sector:
        logger.warning("sector relevance matched zero in_sector records")
    return classified
