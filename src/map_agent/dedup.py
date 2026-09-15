"""Stage 4 — Deduplicate and merge entities.

Multiple search tasks often find the same entity. This module groups
duplicates by fuzzy name matching + shared website/location, then merges
each group into a single record keeping the most complete fields.

Pure Python — no LLM calls, no cost.
"""

from rapidfuzz import fuzz

NAME_THRESHOLD = 85


def _name_key(entity: dict) -> str:
    """Extract the name field regardless of entity type."""
    return (entity.get("name") or entity.get("full_name") or "").strip().lower()


def _website_key(entity: dict) -> str:
    url = (entity.get("website") or "").strip().lower()
    url = url.rstrip("/")
    for prefix in ("https://www.", "http://www.", "https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url


def _is_duplicate(a: dict, b: dict) -> bool:
    """Two entities are duplicates if names are very similar OR websites match."""
    if a.get("_entity_type") != b.get("_entity_type"):
        return False

    name_a, name_b = _name_key(a), _name_key(b)
    if not name_a or not name_b:
        return False

    if fuzz.ratio(name_a, name_b) >= NAME_THRESHOLD:
        return True

    web_a, web_b = _website_key(a), _website_key(b)
    if web_a and web_b and web_a == web_b:
        return True

    return False


def _merge_pair(existing: dict, new: dict) -> dict:
    """Merge two entity dicts, preferring non-empty values.

    If both have a value for a field, keep the longer one (more detail).
    """
    merged = dict(existing)
    for k, v in new.items():
        if not v:
            continue
        old = merged.get(k)
        if not old:
            merged[k] = v
        elif k in ("sources", "people") and isinstance(old, list) and isinstance(v, list):
            # Preserve evidence and people found by every search task. A later
            # normalization pass de-duplicates people and records affiliations.
            merged[k] = old + v
        elif isinstance(v, str) and isinstance(old, str) and len(v) > len(old):
            merged[k] = v
    return merged


def deduplicate(entities: list[dict]) -> list[dict]:
    """Group duplicates and merge each group into one record."""
    groups: list[dict] = []

    for entity in entities:
        matched = False
        for i, group in enumerate(groups):
            if _is_duplicate(group, entity):
                groups[i] = _merge_pair(group, entity)
                matched = True
                break
        if not matched:
            groups.append(dict(entity))

    return groups
