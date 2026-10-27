"""Check each Data Feed row and turn it into the payload the backend stages.

Every problem is a sentence a person can act on, with the row number, e.g.
"Row 12: Actor Category is University / Academic Institution, but Category
Type 'SME' belongs to Company / Corporate Actor." Errors stop a row; warnings
do not. Nothing is guessed: an empty cell stays empty, a value outside a list
is an error, never the "closest" value.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from src.datafeed import contract, parse
from src.datafeed.contract import EXAMPLE_PREFIX, LIST_SEPARATOR, Field
from src.datafeed.reference import US, lookup, region_for
from src.review import taxonomy

_URL_SPACE = re.compile(r"\s")
# The backend Light Pull rule (agents/collection/light_pull.py _sentence_count).
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
NOT_APPLICABLE = taxonomy.NOT_APPLICABLE


class RowResult(dict):
    """{row_number, values, payload, errors, warnings, missing}"""


def _url(value: str) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname \
            or _URL_SPACE.search(value):
        raise ValueError("is not a web address: it must start with http:// or https://")
    return value


def _date(value: str) -> str | None:
    """A calendar day typed MM/DD/YYYY (the US form the templates ask for), or
    the ISO form an Excel date cell becomes; stored as ISO either way."""
    if not value:
        return None
    us = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    try:
        if us:
            day = date(int(us.group(3)), int(us.group(1)), int(us.group(2)))
        else:
            day = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError("is not a date: use MM/DD/YYYY") from exc
    if not us and len(value) > 10 and value[10:].strip() not in ("", "T00:00:00", "00:00:00"):
        raise ValueError("must be a date only (MM/DD/YYYY)")
    if not 1900 <= day.year <= 2100:
        raise ValueError("is outside the years 1900-2100")
    return day.isoformat()


def sentence_count(value: str) -> int:
    text_ = " ".join(value.split())
    return len([p for p in _SENTENCE_BREAK.split(text_) if p.strip()]) if text_ else 0


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(LIST_SEPARATOR) if part.strip()]


def _country(value: str) -> str:
    return US if value.upper() in taxonomy.US_COUNTRY_NAMES else value


# Optional fields whose absence the preview lists as "missing optional information".
RECOMMENDED = {
    "actor": frozenset({"website", "description", "category_type", "city", "state_code",
                        "country"}),
    "person": frozenset({"role", "bio", "linkedin_url", "bio_url", "expertise"}),
    "event": frozenset({"website", "end_date", "organizer", "description", "city"}),
}


class RowChecker:
    """Checks the rows of one record type against the contract and the vocabularies."""

    def __init__(self, record_type: str, vocab: dict[str, Any]):
        self.record_type = record_type
        self.vocab = vocab
        self.fields = contract.fields(record_type)
        self.header_fields = contract.by_header(record_type)

    # ---------------------------------------------------------------- cells
    def _cells(self, values: dict[str, str]) -> dict[str, str]:
        """{field key: text} from {header as written: text}."""
        out: dict[str, str] = {}
        for header, value in values.items():
            field = self.header_fields.get(contract.header_key(header))
            if field is not None:
                out[field.key] = " ".join(str(value or "").split()) if field.kind != "long_text" \
                    else str(value or "").strip()
        return out

    def _enum(self, field: Field, raw: str, errors: list[str], label: str) -> dict | None:
        if not raw:
            return None
        item = lookup(self.vocab.get(field.vocab) or [], raw)
        if item is None and field.strict:
            allowed = ", ".join(i["label"] for i in (self.vocab.get(field.vocab) or [])[:12])
            errors.append(f"{label} '{raw}' is not an allowed value"
                          + (f" (allowed: {allowed}{', ...' if len(self.vocab.get(field.vocab) or []) > 12 else ''})."
                             if allowed else "."))
        return item

    # ---------------------------------------------------------------- one row
    def check(self, row_number: int, values: dict[str, str]) -> RowResult:
        errors: list[str] = []
        warnings: list[str] = []
        cells = self._cells(values)
        for field in self.fields:
            value = cells.get(field.key, "")
            if value and parse.formula_like(value):
                errors.append(f"{field.header} starts like a formula ('{value[:12]}...'). "
                              "Type the value itself.")
                cells[field.key] = ""
                continue
            if field.max_length and len(value) > field.max_length:
                errors.append(f"{field.header} is longer than {field.max_length} characters.")
            if field.required and not value:
                errors.append(f"{field.header} is required.")
        if cells.get("name", "").upper().startswith(EXAMPLE_PREFIX):
            errors.append("This is an example row from the template. Delete it.")
        payload: dict[str, Any] = {}
        for field in self.fields:
            if field.kind == "url":
                try:
                    payload[field.key] = _url(cells.get(field.key, ""))
                except ValueError as exc:
                    errors.append(f"{field.header} {exc}.")
            elif field.kind == "date":
                try:
                    payload[field.key] = _date(cells.get(field.key, ""))
                except ValueError as exc:
                    errors.append(f"{field.header} '{cells.get(field.key)}' {exc}.")
        getattr(self, f"_{self.record_type}")(cells, payload, errors, warnings)
        payload = {k: v for k, v in payload.items() if v not in (None, "", [], {})}
        missing = [f.header for f in self.fields
                   if not f.required and not f.category and f.key in RECOMMENDED[self.record_type]
                   and not cells.get(f.key) and not payload.get(f.key)]
        prefix = f"Row {row_number}: "
        return RowResult(row_number=row_number, values=values, cells=cells, payload=payload,
                         errors=[prefix + e for e in errors],
                         warnings=[prefix + w for w in warnings], missing=missing)


    # ---------------------------------------------------------------- shared
    def _place(self, cells, payload, errors, warnings, *, label_state="State"):
        country = _country(cells.get("country", ""))
        state_raw = cells.get("state_code", "")
        state = ""
        if state_raw:
            code = taxonomy.state_code(state_raw)
            if not code:
                errors.append(f"{label_state} '{state_raw}' is not a US state.")
            elif country and country != US:
                errors.append(f"{label_state} '{state_raw}' is a US state, but the country is "
                              f"{country}.")
            else:
                state = code
                if not country:
                    country = US
                    warnings.append("Country was empty; a US state means United States.")
        if country and country != US:
            warnings.append(f"Country '{country}' is outside the US: its region is Not "
                            "Applicable (Non-US).")
        return state, country

    def _topic(self, cells, errors, fallback_code: str | None = None) -> dict | None:
        raw = cells.get("topic", "")
        topics = self.vocab.get("topics") or []
        if raw:
            item = lookup(topics, raw)
            if item is None:
                errors.append(f"Topic '{raw}' is not one of the database's topics"
                              + ("." if topics else " (the topic list could not be read)."))
            return item
        if fallback_code:
            return next((t for t in topics if t["code"] == fallback_code), None)
        return None

    def _sectors(self, field_key, cells, errors) -> list[str]:
        codes = []
        for part in _split(cells.get(field_key, "")):
            item = lookup(self.vocab.get("sectors") or [], part)
            if item is None:
                errors.append(f"Sector '{part}' is not one of the GHUS sectors.")
            elif item["code"] not in codes:
                codes.append(item["code"])
        return codes

    # ---------------------------------------------------------------- actors
    def _actor(self, cells, payload, errors, warnings):
        payload["name"] = cells.get("name")
        payload["alternate_names"] = _split(cells.get("alternate_names", ""))
        payload["description"] = cells.get("description")
        description = cells.get("description", "")
        if description and sentence_count(description) > 3:
            errors.append("Description must be 1-3 sentences (a full stop followed by a "
                          "space starts a new one).")
        category_field = self.header_fields[contract.header_key("Actor Category")]
        category = self._enum(category_field, cells.get("actor_category", ""), errors,
                              "Actor Category")
        type_raw = cells.get("category_type", "")
        type_code = None
        if category:
            payload["actor_category"] = category["code"]
            types = self.vocab["category_types"][category["code"]]
            item = lookup(types, type_raw) if type_raw else None
            if type_raw and item is None:
                owners = [c for c in self.vocab["actor_categories"]
                          if lookup(self.vocab["category_types"][c["code"]], type_raw)]
                if owners:
                    errors.append(f"Actor Category is {category['label']}, but Category Type "
                                  f"'{type_raw}' belongs to {owners[0]['label']}.")
                else:
                    errors.append(f"Category Type '{type_raw}' is not a type in the GHUS list.")
            elif item:
                type_code = item["code"]
                payload["category_type"] = type_code
        note = cells.get("category_note", "")
        if type_code == NOT_APPLICABLE and not note:
            errors.append("Category Type 'Not Applicable' needs a one-line Category note.")
        if category and not type_raw:
            warnings.append("No Category Type: it stays Pending Classification. A new record "
                            "needs one, so the reviewer chooses it in Review before adding it.")
        stage = cells.get("development_stage", "")
        if category and category["code"] == "startup":
            if not stage:
                errors.append("A startup needs its published development stage "
                              "(Startup: development stage).")
        elif stage:
            errors.append("'Startup: development stage' is only for Startup / Emerging "
                          "Technology Company.")
        if stage:
            payload["development_stage"] = stage
        if category and category["code"] == "national_laboratory"                 and not cells.get("formal_national_designation"):
            errors.append("A national laboratory needs its formal designation "
                          "(National lab: formal designation).")
        payload["category_note"] = note or None
        if note and not type_code:
            payload["category_needs_review"] = True
        sector = self._enum(self.header_fields[contract.header_key("Sector")],
                            cells.get("primary_sector", ""), errors, "Sector")
        extra = self._sectors("additional_sectors", cells, errors)
        if sector:
            payload["primary_sector"] = sector["code"]
            payload["sector_codes"] = [sector["code"], *[c for c in extra if c != sector["code"]]]
        topic = self._topic(cells, errors, sector["code"] if sector else None)
        if topic:
            payload["topic_id"] = topic["topic_id"]
            payload["topic_code"] = topic["code"]
        elif sector and not cells.get("topic"):
            warnings.append(f"Sector {sector['label']} has no topic of its own: Light Pull "
                            "facts are recorded only once a topic is chosen in Review.")
        state, country = self._place(cells, payload, errors, warnings)
        city = cells.get("city")
        payload.update(city=city, location_city=city, state=state or None,
                       state_code=state or None, country=country or None)
        region_raw = cells.get("region", "")
        derived = region_for(state, country) if state else ""
        if region_raw:
            item = lookup(self.vocab.get("regions") or [], region_raw)
            if item is None:
                errors.append(f"Region '{region_raw}' is not one of the seven GHUS regions.")
            elif not state:
                errors.append("Region is set from the State; give the State instead.")
            elif item["code"] != derived:
                errors.append(f"Region '{region_raw}' does not match the State {state} "
                              f"(it belongs to {self._label('regions', derived)}). Leave Region "
                              "empty: it is set automatically.")
        if not (payload.get("website") or payload.get("source_url")):
            errors.append("Give a Website or a Source URL, so the record can be checked.")
        parent = cells.get("parent_name", "")
        relationship = cells.get("parent_relationship", "")
        if parent and not relationship:
            errors.append("Relationship to parent is required when a Parent organization is "
                          "given (Unit of, or Operated by).")
        if relationship:
            item = self._enum(self.header_fields[contract.header_key("Relationship to parent")],
                              relationship, errors, "Relationship to parent")
            if item and not parent:
                errors.append("Relationship to parent is given without a Parent organization.")
            if item:
                payload["parent_relationship"] = item["code"]
        if parent:
            payload["parent_name"] = parent
        boxes: dict[str, Any] = {}
        activity, activity_date = cells.get("recent_activity"), payload.pop(
            "recent_activity_date", None)
        if activity and not activity_date:
            errors.append("Recent activity needs its date (Recent activity date).")
        elif activity_date and not activity:
            errors.append("Recent activity date is given without the activity.")
        elif activity:
            boxes["recent_activity"] = {"description": activity, "date": activity_date}
        for field in self.fields:
            if field.key in ("recent_activity", "recent_activity_date"):
                continue
            if field.target.startswith("actor_fact") and cells.get(field.key):
                categories = contract.box_categories(field)
                if categories and category and category["code"] not in categories:
                    errors.append(f"'{field.header}' is only for "
                                  f"{' or '.join(self._label('actor_categories', c) for c in categories)},"
                                  f" not {category['label']}.")
                    continue
                boxes[field.key] = cells[field.key]
        if boxes:
            payload["light_pull_values"] = boxes

    # ---------------------------------------------------------------- people
    def _person(self, cells, payload, errors, warnings):
        payload.update(name=cells.get("name"), role=cells.get("role"),
                       affiliation=cells.get("affiliation"),
                       affiliation_raw=cells.get("affiliation"),
                       department=cells.get("department"), bio=cells.get("bio"))
        bio = cells.get("bio", "")
        if bio and len(bio.split()) > 120:
            errors.append("Short professional bio is longer than about 120 words.")
        expertise = _split(cells.get("expertise", ""))
        payload["expertise"] = expertise
        payload["research_area"] = "; ".join(expertise) or None
        linkedin = payload.get("linkedin_url") or ""
        if linkedin and "linkedin.com/" not in linkedin.casefold():
            errors.append("Public LinkedIn URL is not a linkedin.com address.")
        if not (payload.get("source_url") or payload.get("bio_url") or linkedin):
            errors.append("Give a Source URL, an Official biography URL or a Public LinkedIn "
                          "URL, so the record can be checked.")
        if not (bio or linkedin):
            warnings.append("Profile incomplete: a complete profile has a short bio or a "
                            "public LinkedIn URL.")
        state, country = self._place(cells, payload, errors, warnings)
        place = ", ".join(p for p in (cells.get("city"), state or None,
                                      country if country and country != US else None) if p)
        payload["work_location"] = place or None
        payload["sector_codes"] = self._sectors("sectors", cells, errors)
        topic = self._topic(cells, errors)
        if topic:
            payload["topic_id"], payload["topic_code"] = topic["topic_id"], topic["code"]

    # ---------------------------------------------------------------- events
    def _event(self, cells, payload, errors, warnings):
        payload.update(name=cells.get("name"), title=cells.get("name"),
                       description=cells.get("description"),
                       thematic_focus=cells.get("themes"),
                       sponsoring_orgs=cells.get("organizer"),
                       expected_attendance=cells.get("expected_attendance"))
        for key, label, target in (("event_type", "Event type", "event_type"),
                                   ("event_format", "Format", "event_format"),
                                   ("recurring_pattern", "Frequency", "recurring_pattern")):
            field = self.header_fields[contract.header_key(label)]
            item = self._enum(field, cells.get(key, ""), errors, label)
            if item:
                payload[target] = item["code"]
        start, end = payload.get("start_date"), payload.get("end_date")
        if start and end and end < start:
            errors.append(f"End date {end} is before the Start date {start}.")
        if start and end and (date.fromisoformat(end) - date.fromisoformat(start)).days > 366:
            warnings.append("The event lasts more than a year; check the dates.")
        if not start:
            payload.pop("start_date", None)
        state, country = self._place(cells, payload, errors, warnings)
        payload.update(city=cells.get("city"), state=state or None, country=country or None,
                       venue=cells.get("venue"))
        if payload.get("event_format") == "online":
            payload["location"] = "Online"
        else:
            payload["location"] = ", ".join(p for p in (
                cells.get("venue"), cells.get("city"), state or None,
                country if country and country != US else None) if p) or None
        if not (payload.get("website") or payload.get("source_url")):
            errors.append("Give an Official event URL or a Source URL, so the record can be "
                          "checked.")
        if not cells.get("organizer"):
            warnings.append("No organizer: the event is recorded with no confirmed host.")
        payload["sector_codes"] = self._sectors("sectors", cells, errors)
        topic = self._topic(cells, errors)
        if topic:
            payload["topic_id"], payload["topic_code"] = topic["topic_id"], topic["code"]

    def _label(self, vocab: str, code: str) -> str:
        return next((i["label"] for i in self.vocab.get(vocab) or [] if i["code"] == code), code)


def file_duplicates(record_type: str, results: list[RowResult]) -> None:
    """Mark the second and later copies of the same record inside one file."""
    from src.datafeed.matching import identity_keys

    first: dict[str, int] = {}
    for result in results:
        if result["errors"]:
            continue
        for key in identity_keys(record_type, result["payload"]):
            if key in first:
                result["errors"].append(f"Row {result['row_number']}: same record as row "
                                        f"{first[key]} ({key.split('|', 1)[0]}).")
                break
        else:
            for key in identity_keys(record_type, result["payload"]):
                first.setdefault(key, result["row_number"])
