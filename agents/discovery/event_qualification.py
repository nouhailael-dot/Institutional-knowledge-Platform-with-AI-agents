"""Deterministic event qualification and participant record projection."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import date

from agents.discovery.normalize import normalize_key_text, parse_date_to_iso

EVENT_PARTICIPANT_ACTOR_FIELDS = (
    "name",
    "participant_role",
    "actor_type",
    "website",
)
EVENT_PARTICIPANT_PERSON_FIELDS = (
    "name",
    "affiliation",
    "role",
    "public_profile_url",
)


@dataclass(frozen=True)
class EventQualification:
    accepted: bool
    attendable: bool
    minable: bool
    store_event: bool
    mined_not_stored: bool
    paths: tuple[str, ...]
    reason: str
    run_date: str
    window_end: str

    def payload(self) -> dict[str, object]:
        values = asdict(self)
        values["paths"] = list(self.paths)
        return {f"qualification_{key}": value for key, value in values.items()}


def qualify_event(
    record: dict[str, object],
    *,
    run_date: date,
    config: dict[str, object],
    rubric: dict[str, object] | None = None,
) -> EventQualification:
    window_months = int(config.get("forward_window_months", 12) or 12)
    if window_months <= 0:
        raise ValueError("event qualification forward_window_months must be positive")
    window_end = _add_months(run_date, window_months)
    start_date = _event_date(record)
    if start_date is None:
        return _rejected("missing start date", run_date, window_end)
    if rubric is None and start_date > window_end:
        return _rejected(
            f"event date {start_date.isoformat()} is after window end {window_end.isoformat()}",
            run_date,
            window_end,
        )
    if not list(record.get("sector_codes") or []):
        return _rejected("event has no seeded-sector match", run_date, window_end)

    if rubric is None:
        date_within_window = run_date <= start_date <= window_end
        registration_open = _registration_is_open(record, config)
        institutional_value = _has_institutional_value(record, config)
        minable = _has_named_participants(record)
    else:
        date_within_window = _rubric_present(rubric, "date_within_window")
        registration_open = _rubric_present(rubric, "open_external_registration")
        institutional_value = _rubric_present(rubric, "institutional_scale")
        minable = _rubric_present(rubric, "named_speakers") or (
            _named_event_organisation_count(record) >= 3
        )
    attendable = date_within_window and registration_open and institutional_value
    if start_date < run_date:
        if not minable:
            return _rejected(
                f"event date {start_date.isoformat()} is before run date {run_date.isoformat()}; "
                "fewer than three named participants and no named speakers",
                run_date,
                window_end,
            )
        return EventQualification(
            accepted=True,
            attendable=False,
            minable=True,
            store_event=False,
            mined_not_stored=True,
            paths=("minable",),
            reason=(
                "mined, not stored: "
                f"event date {start_date.isoformat()} is before run date {run_date.isoformat()}"
            ),
            run_date=run_date.isoformat(),
            window_end=window_end.isoformat(),
        )
    paths = tuple(
        path
        for path, qualifies in (("attendable", attendable), ("minable", minable))
        if qualifies
    )
    if paths:
        return EventQualification(
            accepted=True,
            attendable=attendable,
            minable=minable,
            store_event=True,
            mined_not_stored=False,
            paths=paths,
            reason=f"qualified as {' and '.join(paths)}",
            run_date=run_date.isoformat(),
            window_end=window_end.isoformat(),
        )

    failed: list[str] = []
    if not registration_open:
        failed.append("registration is not open to external organisations")
    if not institutional_value:
        failed.append("scale or topic does not justify institutional attendance")
    failed.append("fewer than three named participants and no named speakers")
    return _rejected("; ".join(failed), run_date, window_end)


def event_date_within_window(
    record: dict[str, object],
    *,
    run_date: date,
    config: dict[str, object],
) -> bool:
    window_months = int(config.get("forward_window_months", 12) or 12)
    if window_months <= 0:
        raise ValueError("event qualification forward_window_months must be positive")
    start_date = _event_date(record)
    return bool(start_date and run_date <= start_date <= _add_months(run_date, window_months))


def structured_page_date_rejection(
    content: str,
    *,
    run_date: date,
    config: dict[str, object],
) -> str | None:
    """Reject a single-date page pre-LLM unless a past page is visibly minable."""
    minable = _structured_page_is_minable(content)
    raw_dates = [
        *re.findall(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", content, re.IGNORECASE),
        *re.findall(r'[\"\']startDate[\"\']\s*:\s*[\"\']([^\"\']+)', content, re.IGNORECASE),
    ]
    parsed_dates = sorted(
        {
            parsed
            for value in raw_dates
            if (parsed := _parse_structured_date(value)) is not None
        }
    )
    if len(parsed_dates) != 1:
        return None
    start_date = parsed_dates[0]
    window_months = int(config.get("forward_window_months", 12) or 12)
    window_end = _add_months(run_date, window_months)
    if start_date < run_date and not minable:
        return f"event date {start_date.isoformat()} is before run date {run_date.isoformat()}"
    if start_date > window_end:
        return f"event date {start_date.isoformat()} is after window end {window_end.isoformat()}"
    return None


def participant_actor_records(event: dict[str, object]) -> list[dict[str, object]]:
    raw_value = event.get("participant_actors") or []
    if not isinstance(raw_value, list):
        raise TypeError("event participant_actors must be a list")
    raw_participants = list(raw_value)
    for person in list(event.get("participant_people") or []):
        if not isinstance(person, dict) or not str(person.get("affiliation") or "").strip():
            continue
        raw_participants.append(
            {
                "name": person.get("affiliation"),
                "participant_role": "speaker affiliation",
                "actor_type": None,
                "website": None,
            }
        )
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_participants:
        if not isinstance(raw, dict):
            continue
        projected = {field: raw.get(field) for field in EVENT_PARTICIPANT_ACTOR_FIELDS}
        name = str(projected.get("name") or "").strip()
        key = normalize_key_text(name)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        role = str(projected.pop("participant_role", None) or "participant").strip()
        records.append(
            {
                **projected,
                "name": name,
                "actor_type_raw": f"event {role}",
                "primary_lifecycle_role": role.title(),
                "current_activities": _event_context(event, role),
                "sector_codes": list(event.get("sector_codes") or []),
                "source_url": event.get("source_url"),
                "extracted_at": event.get("extracted_at"),
                "prompt_version": event.get("prompt_version"),
            }
        )
    return records


def participant_person_records(
    event: dict[str, object],
    *,
    people_enabled: bool,
) -> list[dict[str, object]]:
    raw_participants = event.get("participant_people") or []
    if not isinstance(raw_participants, list):
        raise TypeError("event participant_people must be a list")
    if raw_participants and not people_enabled:
        raise RuntimeError(
            "event person extraction is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_participants:
        if not isinstance(raw, dict):
            continue
        projected = {field: raw.get(field) for field in EVENT_PARTICIPANT_PERSON_FIELDS}
        name = str(projected.get("name") or "").strip()
        affiliation = str(projected.get("affiliation") or "").strip()
        key = (normalize_key_text(name), normalize_key_text(affiliation))
        if not name or not key[0] or key in seen:
            continue
        seen.add(key)
        records.append(
            {
                **projected,
                "name": name,
                "source_url": event.get("source_url"),
                "extracted_at": event.get("extracted_at"),
                "prompt_version": event.get("prompt_version"),
            }
        )
    return records


def actor_person_relation_record(
    person: dict[str, object],
    *,
    event: dict[str, object],
) -> dict[str, object] | None:
    name = str(person.get("name") or "").strip()
    affiliation = str(person.get("affiliation") or "").strip()
    if not name or not affiliation:
        return None
    role = str(person.get("role") or "participant").strip()
    return {
        "person_name": name,
        "actor_name": affiliation,
        "role": role,
        "event_name": event.get("name") or event.get("title"),
        "natural_key": "|".join(
            [normalize_key_text(name), normalize_key_text(affiliation), normalize_key_text(role)]
        ),
        "sector_codes": list(event.get("sector_codes") or []),
        "source_url": event.get("source_url"),
        "extracted_at": event.get("extracted_at"),
        "prompt_version": event.get("prompt_version"),
    }


def _event_date(record: dict[str, object]) -> date | None:
    value = record.get("start_date") or record.get("next_date")
    if value is None:
        return None
    parsed = parse_date_to_iso(value)
    return date.fromisoformat(parsed) if parsed else None


def _parse_structured_date(value: str) -> date | None:
    try:
        parsed = parse_date_to_iso(value)
    except ValueError:
        return None
    return date.fromisoformat(parsed) if parsed else None


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = value.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def _registration_is_open(
    record: dict[str, object],
    config: dict[str, object],
) -> bool:
    explicit = record.get("registration_open")
    if isinstance(explicit, bool):
        return explicit
    text = " ".join(
        str(record.get(field) or "")
        for field in ("access_type", "description", "event_type")
    ).casefold()
    closed_terms = _terms(
        config,
        "closed_registration_terms",
        ["invite-only", "invitation only", "members only", "private event", "closed"],
    )
    if any(term in text for term in closed_terms):
        return False
    open_terms = _terms(
        config,
        "open_registration_terms",
        ["public", "open registration", "register", "registration", "tickets", "rsvp"],
    )
    return any(term in text for term in open_terms)


def _has_institutional_value(
    record: dict[str, object],
    config: dict[str, object],
) -> bool:
    explicit = record.get("institutional_attendance")
    if isinstance(explicit, bool):
        return explicit
    title = re.sub(
        r"^climate\s+week\s+nyc\s*:\s*",
        "",
        str(record.get("title") or record.get("name") or ""),
        flags=re.IGNORECASE,
    )
    title_and_location = f"{title} {record.get('location') or ''}".casefold()
    excluded_terms = _terms(
        config,
        "neighbourhood_exclusion_terms",
        ["library", "storytime", "for children", "for teens", "for kids"],
    )
    if any(term in title_and_location for term in excluded_terms):
        return False

    minimum_attendance = int(config.get("minimum_expected_attendance", 100) or 100)
    attendance = _first_integer(record.get("expected_attendance"))
    if attendance is not None and attendance >= minimum_attendance:
        return True
    text = " ".join(
        str(record.get(field) or "")
        for field in ("title", "event_type", "description")
    ).casefold()
    institutional_terms = _terms(
        config,
        "institutional_value_terms",
        [
            "conference",
            "congress",
            "convening",
            "dialogue",
            "expo",
            "festival",
            "forum",
            "leadership",
            "roundtable",
            "summit",
            "symposium",
        ],
    )
    audience_terms = _terms(
        config,
        "institutional_audience_terms",
        ["business leaders", "industry leaders", "institutions", "investors", "policymakers"],
    )
    return any(term in text for term in [*institutional_terms, *audience_terms])


def _rubric_present(rubric: dict[str, object], name: str) -> bool:
    item = rubric.get(name)
    return isinstance(item, dict) and item.get("present") is True


def _named_event_organisation_count(record: dict[str, object]) -> int:
    names: set[str] = set()
    raw_participants = record.get("participant_actors") or []
    if isinstance(raw_participants, list):
        for item in raw_participants:
            if not isinstance(item, dict):
                continue
            role = str(item.get("participant_role") or "").strip().casefold()
            if role not in {"sponsor", "exhibitor", "convener"}:
                continue
            key = normalize_key_text(str(item.get("name") or ""))
            if key:
                names.add(key)
    sponsoring_orgs = str(record.get("sponsoring_orgs") or "").strip()
    if sponsoring_orgs:
        for name in re.split(
            r"\s*(?:[,;\n]|\band\b|\bin collaboration with\b|\bin partnership with\b)\s*",
            sponsoring_orgs,
            flags=re.IGNORECASE,
        ):
            key = normalize_key_text(name)
            if key:
                names.add(key)
    return len(names)


def _has_named_participants(record: dict[str, object]) -> bool:
    names: set[str] = set()
    for key in ("participant_actors", "participant_people"):
        values = record.get(key) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            key_text = normalize_key_text(name)
            if key_text:
                names.add(key_text)
    named_speakers = record.get("participant_people") or []
    if isinstance(named_speakers, list) and any(
        isinstance(item, dict) and str(item.get("name") or "").strip()
        for item in named_speakers
    ):
        return True
    sponsoring_orgs = str(record.get("sponsoring_orgs") or "").strip()
    if sponsoring_orgs:
        key_text = normalize_key_text(sponsoring_orgs)
        if key_text:
            names.add(key_text)
    return len(names) >= 3


def _structured_page_is_minable(content: str) -> bool:
    names: set[str] = set()
    speaker_names: set[str] = set()
    text_fragments = [content]
    for raw in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(html.unescape(raw).strip())
        except json.JSONDecodeError:
            continue
        _collect_structured_participants(payload, names, speaker_names)
        text_fragments.extend(_structured_strings(payload))

    for fragment in text_fragments:
        decoded = html.unescape(fragment).replace("\\/", "/")
        for match in re.finditer(
            r"<h[1-6][^>]*>\s*(speakers?|sponsors?|exhibitors?|participants?|"
            r"organizers?|organisers?|conveners?|hosts?)\s*</h[1-6]>(.*?)"
            r"(?=<h[1-6][^>]*>|$)",
            decoded,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            role = match.group(1).casefold()
            section_names = [
                _visible_text(value)
                for value in re.findall(
                    r"<(?:li|p)[^>]*>(.*?)</(?:li|p)>",
                    match.group(2),
                    flags=re.IGNORECASE | re.DOTALL,
                )
            ]
            for name in section_names:
                _add_participant_name(name, names)
                if role.startswith("speaker"):
                    _add_participant_name(name, speaker_names)

        for match in re.finditer(
            r"<([a-z0-9]+)[^>]*(?:class|itemprop)=[\"'][^\"']*"
            r"(speaker|performer|sponsor|exhibitor|participant|organizer|organiser|convener|host)"
            r"[^\"']*[\"'][^>]*>(.*?)</\1>",
            decoded,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            name = _visible_text(match.group(3))
            _add_participant_name(name, names)
            if match.group(2).casefold() in {"speaker", "performer"}:
                _add_participant_name(name, speaker_names)

    return bool(speaker_names) or len(names) >= 3


def _collect_structured_participants(
    value: object,
    names: set[str],
    speaker_names: set[str],
) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_structured_participants(item, names, speaker_names)
        return
    if not isinstance(value, dict):
        return
    for raw_key, raw_value in value.items():
        key = str(raw_key).casefold()
        if key in {
            "speaker",
            "speakers",
            "performer",
            "performers",
            "attendee",
            "attendees",
            "participant",
            "participants",
            "sponsor",
            "sponsors",
            "organizer",
            "organizers",
        }:
            for name in _structured_names(raw_value):
                _add_participant_name(name, names)
                if key in {"speaker", "speakers", "performer", "performers"}:
                    _add_participant_name(name, speaker_names)
        _collect_structured_participants(raw_value, names, speaker_names)


def _structured_names(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in values:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        elif isinstance(item, str):
            name = item.strip()
        else:
            name = ""
        if name:
            names.append(name)
    return names


def _structured_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _structured_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _structured_strings(item)]
    return []


def _visible_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _add_participant_name(value: str, names: set[str]) -> None:
    name = re.split(r"\s+[\u2013\u2014-]\s+", value, maxsplit=1)[0].strip(" ,;:")
    key = normalize_key_text(name)
    if key:
        names.add(key)


def _event_context(event: dict[str, object], role: str) -> str:
    title = str(event.get("name") or event.get("title") or "event").strip()
    return f"Published as {role} for {title}."


def _first_integer(value: object) -> int | None:
    match = re.search(r"\d[\d,]*", str(value or ""))
    return int(match.group(0).replace(",", "")) if match else None


def _terms(
    config: dict[str, object],
    key: str,
    default: list[str],
) -> list[str]:
    values = config.get(key, default)
    return [str(value).strip().casefold() for value in list(values or []) if str(value).strip()]


def _rejected(reason: str, run_date: date, window_end: date) -> EventQualification:
    return EventQualification(
        accepted=False,
        attendable=False,
        minable=False,
        store_event=False,
        mined_not_stored=False,
        paths=(),
        reason=reason,
        run_date=run_date.isoformat(),
        window_end=window_end.isoformat(),
    )
