"""Stage 4 — Deduplicate and merge entities.

Multiple search tasks often find the same entity. This module groups
duplicates and merges each group into a single record keeping the most
complete fields.

Organizations follow the intern guide's rule: merge only on a clear match (the
same name, a shared alternate name, the same words reordered, or a similar name
on the same homepage). A close-but-not-exact match is never merged; both records
are kept and marked `_possible_duplicates` for a person to decide. People keep
the original fuzzy-name/website rule.

Events are matched on the name without years or edition words ("RE+ 2026" is
"RE+"), with the same merge-or-flag rule. Two editions of one event are never
mixed field by field: one card keeps one edition - the nearest upcoming one,
otherwise the latest - and the other's date becomes its previous edition. The
date status is recomputed from the dates, never merged (27 Oct 2026).

Pure Python — no LLM calls, no cost.
"""

import re
from urllib.parse import urlparse

from rapidfuzz import fuzz, utils

from src.map_agent.actor_profile import NOT_CLASSIFIED
from src.map_agent.event_dates import PAST, date_status, event_span, same_edition

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


def event_core(name) -> str:
    """An event's name without years, edition numbers or brackets' punctuation:
    "RE+ (Renewable Energy Plus) 2026" -> "re renewable energy plus"."""
    text = re.sub(r"\b(19|20)\d{2}\b|\b\d+(st|nd|rd|th)\b|\b(annual|edition|inaugural)\b",
                  " ", str(name or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _event_match(a: dict, b: dict):
    """MERGE, FLAG or None for two event records. Only the same name (years and
    edition words aside) merges. Close names are flagged for a person: the same
    name once brackets are removed ("RE+ (Renewable Energy Plus)" and "RE+"),
    one name inside the other ("CLEANPOWER" and "CLEANPOWER Conference &
    Exhibition"), or a shared website - often a listing page of many events."""
    core_a, core_b = event_core(a.get("name")), event_core(b.get("name"))
    if not core_a or not core_b:
        return None
    if core_a == core_b:
        return MERGE
    same_home = bool(_homepage(a)) and _homepage(a) == _homepage(b)
    if fuzz.ratio(core_a, core_b) >= NAME_THRESHOLD:
        return MERGE if same_home else FLAG
    bare_a = event_core(re.sub(r"\([^)]*\)", " ", str(a.get("name") or "")))
    bare_b = event_core(re.sub(r"\([^)]*\)", " ", str(b.get("name") or "")))
    words_a, words_b = set(core_a.split()), set(core_b.split())
    same_site = bool(_website_key(a)) and _website_key(a) == _website_key(b)
    if (bare_a and bare_a == bare_b) or words_a <= words_b or words_b <= words_a or same_site:
        return FLAG
    return None


def _is_duplicate(a: dict, b: dict) -> bool:
    if a.get("_entity_type") != b.get("_entity_type"):
        return False
    if a.get("_entity_type") == "actor":
        return _actor_match(a, b) == MERGE
    if a.get("_entity_type") == "event":
        return _event_match(a, b) == MERGE

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


# Fields that describe one edition. They travel together: a card never shows the
# date of one edition with the city of another.
EDITION_FIELDS = ("next_date", "end_date", "date_status", "location", "event_format")


def _edition_order(event: dict):
    """Sort key: the nearest upcoming edition first, then the latest past one,
    then one with no readable date."""
    span = event_span(event.get("next_date"), event.get("end_date"))
    status = date_status(event.get("next_date"), event.get("end_date"))
    if span is None:
        return (2, 0)
    if status == PAST:
        return (1, -span[1].toordinal())
    return (0, span[0].toordinal())


def _latest_earlier(dates, before):
    """The latest of `dates` that ends before the edition starting `before`."""
    best = None
    for value in dates:
        span = event_span(value)
        if span and span[1] < before and (best is None or span[1] > event_span(best)[1]):
            best = value
    return best


def _merge_editions(existing: dict, new: dict) -> dict:
    """Two editions of the same event: keep the better one whole, take only
    edition-independent details from the other, and note the earlier date."""
    kept, other = sorted((existing, new), key=_edition_order)
    merged = dict(kept)
    for k, v in other.items():
        if not v or k in EDITION_FIELDS or k in ("name", "previous_edition"):
            continue
        if k == "sources" and isinstance(merged.get(k), list) and isinstance(v, list):
            merged[k] = merged[k] + v
        elif not merged.get(k):
            merged[k] = v
    start = event_span(kept.get("next_date"), kept.get("end_date"))
    if start:
        previous = _latest_earlier([other.get("next_date"), other.get("previous_edition"),
                                    kept.get("previous_edition")], start[0])
        if previous:
            merged["previous_edition"] = previous
    merged["date_status"] = date_status(merged.get("next_date"), merged.get("end_date"))
    return merged


def _merge_event(existing: dict, new: dict) -> dict:
    if not same_edition(existing, new):
        return _merge_editions(existing, new)
    # The same edition. Its dates travel together, from whichever record gives
    # the more precise start (a whole day over a month), the first on a tie.
    merged = _merge_pair({k: v for k, v in existing.items() if k not in ("next_date", "end_date")},
                         {k: v for k, v in new.items() if k not in ("next_date", "end_date", "date_status")})
    precise = lambda e: (event_span(e.get("next_date")) or (None, None, False))[2]
    dated = new if (precise(new) and not precise(existing)) or not existing.get("next_date") else existing
    for k in ("next_date", "end_date"):
        if dated.get(k):
            merged[k] = dated[k]
        else:
            merged.pop(k, None)
    merged["date_status"] = date_status(merged.get("next_date"), merged.get("end_date"))
    return merged


def mark_possible_duplicates(groups: list[dict]) -> None:
    for kind, match in (("actor", _actor_match), ("event", _event_match)):
        records = [g for g in groups if g.get("_entity_type") == kind]
        for g in records:
            g.pop("_possible_duplicates", None)
        for i, a in enumerate(records):
            for b in records[i + 1:]:
                if match(a, b) == FLAG:
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
                merge = _merge_event if entity.get("_entity_type") == "event" else _merge_pair
                # Every search that found it, so a follow-up can say "also found".
                seen = sorted(set((group.get("_seen_in") or []) + (entity.get("_seen_in") or [])))
                groups[i] = merge(group, entity)
                if seen:
                    groups[i]["_seen_in"] = seen
                matched = True
                break
        if not matched:
            groups.append(dict(entity))

    mark_possible_duplicates(groups)
    return groups
