"""Stage 4 — Deduplicate and merge entities.

Multiple search tasks often find the same entity. This module groups
duplicates and merges each group into a single record keeping the most
complete fields.

Organizations follow the intern guide's rule: merge only on a clear match (the
same name, a shared alternate name, the same words reordered, or a similar name
on the same homepage). A close-but-not-exact match is never merged; both records
are kept and marked `_possible_duplicates` for a person to decide. People and
events keep the original fuzzy-name/website rule.

Pure Python — no LLM calls, no cost.
"""

import re
from urllib.parse import urlparse

from rapidfuzz import fuzz, utils

from src.map_agent.actor_profile import NOT_CLASSIFIED

NAME_THRESHOLD = 85
REORDERED_THRESHOLD = 95
# Shorter alternate names ("UF", "MIT") are usually the parent's abbreviation,
# which several units of the same university share.
ALIAS_MIN = 4
MERGE, FLAG = "merge", "flag"


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


def _norm(text) -> str:
    return utils.default_process(str(text or ""))


def _split(value) -> list[str]:
    return [p.strip() for p in str(value or "").split(";") if p.strip()]


def _bracketed(name) -> set[str]:
    return {_norm(m) for m in re.findall(r"\(([^)]*)\)", str(name or "")) if _norm(m)}


def _core(name) -> str:
    return _norm(re.sub(r"\([^)]*\)", " ", str(name or "")))


def _homepage(entity: dict) -> str:
    """The host, only when the website is a homepage.

    A deeper page is often where the organization was found (a lab listing, a
    news story), and several organizations can share it.
    """
    url = (entity.get("website") or "").strip().lower()
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else "http://" + url)
    if parsed.path.strip("/") or parsed.query:
        return ""
    return parsed.netloc.removeprefix("www.")


def _actor_match(a: dict, b: dict):
    """MERGE, FLAG or None for two organization records."""
    name_a, name_b = _norm(a.get("name")), _norm(b.get("name"))
    if not name_a or not name_b:
        return None
    if name_a == name_b:
        return MERGE
    alts_a = {n for n in map(_norm, _split(a.get("other_names"))) if len(n) >= ALIAS_MIN}
    alts_b = {n for n in map(_norm, _split(b.get("other_names"))) if len(n) >= ALIAS_MIN}
    if alts_a & alts_b:
        return MERGE
    # "(FIPR Institute)" in one name, "FIPR Institute" listed as the other's
    # alternate name. Brackets are not compared with each other: two units can
    # both carry "(University of Florida)".
    brackets_a, brackets_b = _bracketed(a.get("name")), _bracketed(b.get("name"))
    if {n for n in brackets_a if len(n) >= ALIAS_MIN} & alts_b \
            or {n for n in brackets_b if len(n) >= ALIAS_MIN} & alts_a:
        return MERGE
    if _core(a.get("name")) == _core(b.get("name")):
        # "University of Florida" vs "University of Florida (UF)" is the same
        # place; "WRRI (NMSU)" vs "WRRI (Texas A&M)" may not be, and a long
        # bracket ("NMSU (Water Institute / Dept. of Civil Engineering lab)")
        # describes a unit rather than giving a short name.
        short = lambda brackets: all(len(b.split()) <= 4 for b in brackets)
        if brackets_a == brackets_b or (not brackets_a and short(brackets_b)) \
                or (not brackets_b and short(brackets_a)):
            return MERGE
        return FLAG
    if fuzz.token_sort_ratio(name_a, name_b) >= REORDERED_THRESHOLD:
        return MERGE
    same_home = bool(_homepage(a)) and _homepage(a) == _homepage(b)
    if fuzz.ratio(name_a, name_b) >= NAME_THRESHOLD:
        return MERGE if same_home else FLAG
    # One record lists the other's full name as its own alternate name. The
    # model sometimes puts a parent there (a department naming its school).
    if name_b in alts_a or name_a in alts_b:
        return FLAG
    return FLAG if same_home else None


def _is_duplicate(a: dict, b: dict) -> bool:
    if a.get("_entity_type") != b.get("_entity_type"):
        return False
    if a.get("_entity_type") == "actor":
        return _actor_match(a, b) == MERGE

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
        if not v or k in ("category_type", "other_names"):
            continue
        old = merged.get(k)
        if not old:
            merged[k] = v
        elif k in ("sources", "people", "rankings", "actor_relationships", "category_details") and isinstance(old, list) and isinstance(v, list):
            # Preserve evidence and people found by every search task. A later
            # normalization pass de-duplicates people and records affiliations.
            merged[k] = old + v
        elif isinstance(v, str) and isinstance(old, str) and len(v) > len(old):
            merged[k] = v
    # A category type only means something next to the category it was chosen
    # with, so it follows whichever record's category was kept.
    if merged.get("actor_type") != existing.get("actor_type"):
        if new.get("category_type"):
            merged["category_type"] = new["category_type"]
        else:
            merged.pop("category_type", None)
    elif new.get("actor_type") == existing.get("actor_type") \
            and existing.get("category_type") in (None, "", NOT_CLASSIFIED) \
            and new.get("category_type") not in (None, "", NOT_CLASSIFIED):
        merged["category_type"] = new["category_type"]
    if existing.get("_entity_type") == "actor":
        # Every name either record went by stays findable as an alternate name.
        names = _split(existing.get("other_names")) + _split(new.get("other_names")) \
            + [n for n in (existing.get("name"), new.get("name")) if n]
        seen, alternates = {_norm(merged.get("name"))}, []
        for n in names:
            if _norm(n) and _norm(n) not in seen:
                seen.add(_norm(n))
                alternates.append(n)
        if alternates:
            merged["other_names"] = "; ".join(alternates)
    elif new.get("other_names") and not existing.get("other_names"):
        merged["other_names"] = new["other_names"]
    return merged


def mark_possible_duplicates(groups: list[dict]) -> None:
    actors = [g for g in groups if g.get("_entity_type") == "actor"]
    for g in actors:
        g.pop("_possible_duplicates", None)
    for i, a in enumerate(actors):
        for b in actors[i + 1:]:
            if _actor_match(a, b) == FLAG:
                a.setdefault("_possible_duplicates", []).append(b.get("name"))
                b.setdefault("_possible_duplicates", []).append(a.get("name"))


def deduplicate(entities: list[dict]) -> list[dict]:
    """Group duplicates, merge each group into one record, and mark the
    organizations that look alike but were not merged."""
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

    mark_possible_duplicates(groups)
    return groups
