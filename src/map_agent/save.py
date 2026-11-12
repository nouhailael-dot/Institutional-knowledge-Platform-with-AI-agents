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


def _place(location) -> tuple[str, str, str]:
    """(city, state, country) from free text like "Westminster, Colorado, United States"."""
    parts = [p.strip() for p in str(location or "").split(",") if p.strip()]
    states = {name.casefold(): name for name in reference.taxonomy.STATE_NAMES.values()}
    states.update({code.casefold(): code for code in reference.taxonomy.STATE_NAMES})
    for i, part in enumerate(parts):
        word = re.sub(r"\s+\d{5}(-\d{4})?$", "", part)   # "TX 77002" -> "TX"
        if word.casefold() in states:
            return (parts[i - 1] if i else ""), states[word.casefold()], "United States"
    return "", "", ""


def event_type(raw) -> str:
    """One of the approved event types when the map's own words name it."""
    text = _clean(raw).casefold()
    return next((t for t in reference.EVENT_TYPES if t in text), "")


# Card fields that are bookkeeping, not facts about the record.
_NOT_FACTS = frozenset({"sources", "profile_version", "record_status", "field_evidence",
                        "unsupported_fields", "verification_history", "ghus_notes", "hub_status",
                        "id", "entity_id", "_why", "selected", "excluded", "reason"})
# Card fields to_record reads, per kind: everything else goes to map_facts.
_READ = {
    "actor": {"name", "other_names", "website", "actor_type", "category_type", "category_note",
              "description", "location_city", "state", "country", "funding_summary",
              "um6p_ocp_detail"},
    "event": {"name", "event_type", "organizer", "next_date", "end_date", "event_format",
              "location", "thematic_focus", "description", "website", "recurring_pattern",
              "expected_attendance"},
    "person": {"full_name", "title", "organization_name", "profile_url", "linkedin_url",
               "expertise"},
}


def map_facts(kind: str, entity: dict) -> dict:
    """Every non-empty card field the Data Feed record does not carry (4 Nov 2026):
    stored as sourced facts at admission, so nothing the card showed is lost."""
    return {key: value for key, value in entity.items()
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
            "funding_signal": _clean(entity.get("funding_summary")),
            "um6p_ocp_connection": _clean(entity.get("um6p_ocp_detail")),
        }.items() if v}
    if kind == "event":
        city, state, country = _place(entity.get("location"))
        return {k: v for k, v in {
            "name": _clean(entity.get("name")),
            "event_type": event_type(entity.get("event_type")),
            "organizer": _clean(entity.get("organizer")),
            "start_date": _us_day(entity.get("next_date")),
            "end_date": _us_day(entity.get("end_date")),
            "event_format": _FORMATS.get(_clean(entity.get("event_format")).casefold(), ""),
            "city": city, "state_code": state, "country": country,
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
                        "preview_id": preview["preview_id"], "row_number": row["row_number"]})
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
                result.update(outcome=DIRECTORY, reason="")
    return [results[i] for i in sorted(results)]
