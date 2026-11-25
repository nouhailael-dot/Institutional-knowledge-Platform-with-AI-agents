"""Verify -> the database: verified map results go in through the Data Feed.

Asked for on 28 Oct 2026. The platform never writes canonical records itself
(AGENTS.md rule 1): each verified card becomes a Data Feed record (method
"map") and the backend's own staging and admission do the rest -

  every organization, event and person -> stored in the directory

12 Nov 2026 (GHUS): a map is reviewed on its own page, never in Review Results,
which is for new requests and organization updates only. A record matching one
already in the directory updates it; a possible duplicate, or one the writer
refuses, is not added and its card says why.

A value the map holds in a form the Data Feed does not accept (a partial date,
an event type outside the list) is left empty, never guessed (rule 7); if the
field is required, the record says what it needs instead of being saved.

No paid calls.
"""
from __future__ import annotations

import re

from src.datafeed import reference
from src.map_agent.actor_profile import CATEGORY_FACTS

KINDS = ("actor", "event", "person")
# What a card shows after saving.
DIRECTORY, REVIEW, NOT_SAVED = "directory", "review", "not_saved"

_FORMATS = {"in-person": "In person", "virtual": "Online", "hybrid": "Hybrid"}
_FREQUENCIES = {"annual": "Annual", "one-time": "One-time", "every two years": "Recurring",
                "twice a year": "Recurring", "quarterly": "Recurring", "monthly": "Recurring",
                "irregular": "Recurring"}
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _us_day(value) -> str:
    """A whole ISO day as MM/DD/YYYY; a partial date ("2026-02") stays empty."""
    found = _DAY.match(str(value or "").strip()[:10])
    return f"{found[2]}/{found[3]}/{found[1]}" if found and len(str(value).strip()) >= 10 else ""


def _source(entity) -> str:
    for source in entity.get("sources") or []:
        if isinstance(source, dict) and str(source.get("url") or "").startswith("http"):
            return source["url"]
    return ""


def _place_parts(location) -> tuple[str, str, str, str]:
    """(venue, city, state, country) from free text like "Oregon Convention Center,
    Portland, Oregon": the venue is what comes before the city (25 Nov 2026)."""
    parts = [p.strip() for p in str(location or "").split(",") if p.strip()]
    states = {name.casefold(): name for name in reference.taxonomy.STATE_NAMES.values()}
    states.update({code.casefold(): code for code in reference.taxonomy.STATE_NAMES})
    # From the end: in "…, New York, NY, 10019" the state is NY, and New York the city.
    for i in range(len(parts) - 1, -1, -1):
        word = re.sub(r"\s+\d{5}(-\d{4})?$", "", parts[i])   # "TX 77002" -> "TX"
        if word.casefold() in states:
            venue = ", ".join(parts[:i - 1]) if i > 1 else ""
            return venue, (parts[i - 1] if i else ""), states[word.casefold()], "USA"
    return "", "", "", ""


def _place(location) -> tuple[str, str, str]:
    """(city, state, country) from free text like "Westminster, Colorado, USA"."""
    return _place_parts(location)[1:]


def event_type(raw) -> str:
    """One of the approved event types when the map's own words name it."""
    text = _clean(raw).casefold()
    return next((t for t in reference.EVENT_TYPES if t in text), "")


# Card fields that are bookkeeping, not facts about the record.
_NOT_FACTS = frozenset({"sources", "profile_version", "record_status", "field_evidence",
                        "unsupported_fields", "verification_history", "ghus_notes", "hub_status",
                        "id", "entity_id", "_why", "selected", "excluded", "reason"})
# Organization card fields stored under the name the update agent uses for the same fact.
_FACT_NAMES = {"match_explanation": "why_matched"}
# Card fields to_record reads, per kind: everything else goes to map_facts.
_READ = {
    "actor": {"name", "other_names", "website", "actor_type", "category_type", "category_note",
              "description", "location_city", "state", "country", "funding_summary",
              "um6p_ocp_detail", "international_connections"},
    "event": {"name", "event_type", "organizer", "next_date", "end_date", "event_format",
              "location", "thematic_focus", "description", "website", "recurring_pattern",
              "expected_attendance"},
    "person": {"full_name", "title", "organization_name", "profile_url", "linkedin_url",
               "expertise"},
}


def _category_facts(entity: dict) -> tuple[dict, list]:
    """(facts for the template's own columns, the rest kept as category details).

    24 Nov 2026: a fact keyed from the card's own category fills that column, as the
    update agent's does; one with no key (maps before this date) or 'other' stays a detail."""
    own = CATEGORY_FACTS.get(entity.get("actor_type"), {})
    fixed, rest = {}, []
    for detail in entity.get("category_details") or []:
        if not isinstance(detail, dict):
            continue
        key, value = detail.get("key"), _clean(detail.get("value"))
        if key in own and key not in fixed and value:
            fixed[key] = value
        else:
            rest.append(detail)
    return fixed, rest


def map_facts(kind: str, entity: dict) -> dict:
    """Every non-empty card field the Data Feed record does not carry (4 Nov 2026):
    stored as sourced facts at admission, so nothing the card showed is lost."""
    if kind == "actor" and entity.get("category_details"):
        entity = {**entity, "category_details": _category_facts(entity)[1]}
    names = _FACT_NAMES if kind == "actor" else {}
    return {names.get(key, key): value for key, value in entity.items()
            if key not in _READ[kind] and key not in _NOT_FACTS and not str(key).startswith("_")
            and value not in (None, "", [], {}) and str(value).strip().casefold()
            not in ("not found", "not classified")}


def to_record(kind: str, entity: dict, sector: str) -> dict:
    """The Data Feed record (contract field keys) for one map card, its other
    fields under map_facts."""
    record = _contract_record(kind, entity, sector)
    extra = map_facts(kind, entity)
    if extra:
        record["map_facts"] = extra
    return record


def _contract_record(kind: str, entity: dict, sector: str) -> dict:
    """The Data Feed record (contract field keys) for one map card."""
    if kind == "actor":
        category_type = _clean(entity.get("category_type"))
        return {k: v for k, v in {
            "name": _clean(entity.get("name")),
            "alternate_names": _clean(entity.get("other_names")),
            "website": _clean(entity.get("website")),
            "actor_category": _clean(entity.get("actor_type")),
            "category_type": "" if category_type.casefold() == "not classified" else category_type,
            "category_note": _clean(entity.get("category_note")),
            "description": _clean(entity.get("description")),
            "primary_sector": sector,
            "city": _clean(entity.get("location_city")),
            "state_code": _clean(entity.get("state")),
            "country": _clean(entity.get("country")),
            "source_url": _source(entity),
            # Not "recent_activity": the Data Feed needs its date, and the map
            # records none (a date is never guessed).
            "funding_summary": _clean(entity.get("funding_summary")),
            "international_connection": _clean(entity.get("international_connections")),
            "um6p_ocp_connection": _clean(entity.get("um6p_ocp_detail")),
            **_category_facts(entity)[0],
        }.items() if v}
    if kind == "event":
        venue, city, state, country = _place_parts(entity.get("location"))
        return {k: v for k, v in {
            "name": _clean(entity.get("name")),
            "event_type": event_type(entity.get("event_type")),
            "organizer": _clean(entity.get("organizer")),
            "start_date": _us_day(entity.get("next_date")),
            "end_date": _us_day(entity.get("end_date")),
            "event_format": _FORMATS.get(_clean(entity.get("event_format")).casefold(), ""),
            "venue": venue, "city": city, "state_code": state, "country": country,
            "sectors": sector,
            "themes": _clean(entity.get("thematic_focus")),
            "description": _clean(entity.get("description")),
            "website": _clean(entity.get("website")),
            "recurring_pattern": _FREQUENCIES.get(_clean(entity.get("recurring_pattern")).casefold(), ""),
            "expected_attendance": _clean(entity.get("expected_attendance")),
            "source_url": _source(entity),
        }.items() if v}
    # People: no biography (the backend's people rules keep it out). The full
    # name is split at its last space; the Data Feed joins the two back as is.
    first, _, last = _clean(entity.get("full_name")).rpartition(" ")
    return {k: v for k, v in {
        "first_name": first or last,
        "last_name": last if first else "",
        "role": _clean(entity.get("title")),
        "affiliation": _clean(entity.get("organization_name")),
        "bio_url": _clean(entity.get("profile_url")),
        "linkedin_url": _clean(entity.get("linkedin_url")),
        "expertise": _clean(entity.get("expertise")),
        "sectors": sector,
        "source_url": _source(entity),
    }.items() if v}


def _check_outcome(row) -> tuple[str, str]:
    """What saving would do with one checked record."""
    if row["status"] == "invalid":
        return NOT_SAVED, "Needs: " + "; ".join(e.split(": ", 1)[-1] for e in row["errors"])[:400]
    if row["status"] == "waiting":
        return NOT_SAVED, "It is already waiting to be added from another import."
    if row["status"] == "deleted":
        # The match waits for permanent deletion (24 Nov 2026): say so, store nothing.
        from src.datafeed.service import pending_deletion_note
        return NOT_SAVED, pending_deletion_note(row.get("match") or {})
    if row["status"] == "existing":
        return DIRECTORY, "Matches a record already in the directory, which it updates."
    if row["status"] == "possible":
        return DIRECTORY, ("May match a record already in the directory; if it is not clearly "
                           "the same, it is not added twice and this card says so.")
    return DIRECTORY, ""


def check(service, picks: list[tuple[str, dict, str]]) -> list[dict]:
    """Writes nothing: per card, whether it would be added, go to Review, or not save.
    `picks` are (kind, entity, sector)."""
    out = []
    for kind in KINDS:
        group = [(i, e, sector) for i, (k, e, sector) in enumerate(picks) if k == kind]
        if not group:
            continue
        preview = service.validate_manual(kind, [to_record(kind, e, s) for _, e, s in group],
                                          method="map")
        for (index, entity, _), row in zip(group, preview["rows"]):
            outcome, reason = _check_outcome(row)
            out.append({"index": index, "kind": kind, "outcome": outcome, "reason": reason,
                        "preview_id": preview["preview_id"], "row_number": row["row_number"],
                        # The record it matches, named on the card after saving.
                        "matched_name": (row.get("match") or {}).get("name")
                        if row.get("status") in ("existing", "possible") else None})
    return sorted(out, key=lambda r: r["index"])


def import_name(map_name: str) -> str:
    """The Data Feed import a map's saved cards arrive under (Review shows it)."""
    return _clean(f"Explore and Map: {map_name}")[:120]


def save(service, picks: list[tuple[str, dict, str]], *, uploader: str, map_name: str) -> list[dict]:
    """Send verified cards to the database through the Data Feed; one result per card."""
    checked = check(service, picks)
    results = {r["index"]: {**r} for r in checked}
    name = import_name(map_name)
    for kind in KINDS:
        rows = [r for r in checked if r["kind"] == kind and r["outcome"] != NOT_SAVED]
        if not rows:
            continue
        # Stored in the directory by the approved admission path (the Data
        # Feed's "directory" admission, GHUS decision of 3 Nov 2026): the person
        # verified it on the map and confirms the source. No AI enrichment: the
        # map already researched it.
        answer = service.confirm(rows[0]["preview_id"], import_name=name, accept_left_out=True,
                                 uploaded_by=uploader, attest_source=True,
                                 admission="directory", attest_authorized=True,
                                 ai_enrichment=False)
        staged = {r.get("row_number"): r.get("outcome") for r in answer.get("rows") or []}
        refused = {a.get("row_number"): a for a in answer.get("not_stored") or []}
        placed = {a.get("row_number"): a for a in answer.get("placed") or []}
        for r in rows:
            result = results[r["index"]]
            if staged.get(r["row_number"]) == "already_awaiting_review":
                result.update(outcome=NOT_SAVED,
                              reason="It is already waiting to be added from another import.")
            elif staged.get(r["row_number"]) != "staged":
                result.update(outcome=NOT_SAVED, reason="The database did not accept it.")
            elif r["row_number"] in refused:
                result.update(outcome=NOT_SAVED, reason=refused[r["row_number"]].get("reason")
                              or "The directory did not accept it.")
            else:
                # Where it went (24 Nov 2026): added as new, or merged into a record there.
                where = placed.get(r["row_number"]) or {}
                result.update(outcome=DIRECTORY, reason="",
                              placed="matched" if where.get("outcome") == "matched_existing" else "added",
                              entity_id=where.get("entity_id"), matched_name=r.get("matched_name"))
    return [results[i] for i in sorted(results)]


# One-click Verify (GHUS, 23 Nov 2026): the sector is filled, never asked. Words that
# name a sector in a card's sector or a map's request, per sector code.
_SECTOR_WORDS = {
    "AGRI": ("agricultur", "agronom", "farm", "crop", "soil", "food system", "agtech"),
    "WATER": ("water", "irrigation", "hydrolog"),
    "ENERGY": ("energy", "battery", "batteries", "solar", "hydrogen", "power grid"),
    "MINING": ("mining", "mineral", "rare earth", "phosphogypsum"),
    "CHEM": ("chemical", "chemistry", "catalys"),
    "HEALTH": ("health care", "healthcare", "medical", "biomedical", "clinical"),
    "SUSTAIN": ("sustainab", "climate", "circular economy"),
    "AI": ("artificial intelligence", " ai ", "machine learning"),
}


def _named_sector(text, sectors: list[dict], *, first: bool = False) -> str:
    """The sector a text names (its label, or a word that means it), else ''.
    first=True (a card's own list): the one written first. Otherwise (a request):
    only when exactly one sector is named; two named are never guessed between."""
    low = f" {str(text or '').casefold()} "
    at = {}
    for item in sectors:
        hits = [low.find(w) for w in (item["label"].casefold(), *_SECTOR_WORDS.get(item["code"], ()))]
        hits = [i for i in hits if i >= 0]
        if hits:
            at[item["label"]] = min(hits)
    if first and at:
        return min(at, key=at.get)
    return next(iter(at)) if len(at) == 1 else ""


def auto_sector(entity: dict, map_entities: dict, request: str, sectors: list[dict]) -> str:
    """A verified card's sector, with no question (23 Nov 2026), in this order:
    the card's own sector; the map's most common sector; the sector the map's
    request names. '' when none is clear: the save then says a sector is needed."""
    own = _named_sector(entity.get("sector"), sectors, first=True)
    if own:
        return own
    counts: dict[str, int] = {}
    for cards in (map_entities or {}).values():
        for card in cards or []:
            named = _named_sector(card.get("sector"), sectors, first=True)
            if named:
                counts[named] = counts.get(named, 0) + 1
    if counts:
        best = max(counts.values())
        top = [label for label, n in counts.items() if n == best]
        if len(top) == 1:
            return top[0]
    return _named_sector(request, sectors)
