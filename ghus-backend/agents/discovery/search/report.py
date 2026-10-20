"""Markdown reporting for open-web discovery candidates."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from agents.discovery.extractors.actor import ACTOR_RECORD_FIELDS
from agents.discovery.extractors.event import EVENT_FIELDS
from agents.discovery.extractors.person import PERSON_FIELDS
from agents.discovery.search.models import CandidateRecord

EVENT_REPORT_FIELDS = (
    "name",
    "start_date",
    "end_date",
    "location",
    "city",
    "state",
    "country",
    "website",
    "description",
    "sponsoring_orgs",
    "sector_codes",
)



# Architecture V2 classification and the topic the actor was found for.
V2_ACTOR_EXPORT_FIELDS = (
    "actor_category", "category_type", "category_needs_review", "topic_id",
    "match_strength", "match_reason",
)

def write_candidate_report(
    path: Path,
    *,
    run_id: str,
    status: str,
    status_reason: str,
    stats: dict[str, object],
    queries: dict[str, list[str]],
    candidates: list[CandidateRecord],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[CandidateRecord]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.entity_type].append(candidate)

    lines = [
        f"# Open-Web Discovery Report: {run_id}",
        "",
        f"Status: **{status}**",
    ]
    if status_reason:
        lines.extend(["", f"Reason: {status_reason}"])
    lines.extend(
        [
            "",
            "## Stats",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
    )
    for key in sorted(stats):
        value = stats[key]
        if isinstance(value, (dict, list)):
            continue
        lines.append(f"| {_escape(key)} | {_escape(str(value))} |")

    lines.extend(["", "## Queries", ""])
    for entity_type, entity_queries in queries.items():
        lines.append(f"### {entity_type}")
        if not entity_queries:
            lines.append("- none")
        for query in entity_queries:
            lines.append(f"- `{query}`")
        lines.append("")

    lines.append("## Candidates")
    for entity_type in sorted(grouped):
        rows = sorted(grouped[entity_type], key=_candidate_sort_key)
        lines.extend(
            [
                "",
                f"### {entity_type}",
                "",
                "| Score | Verdict | Domain | Title | URL | Reason | Duplicate Of | Query |",
                "| ---: | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                "| {score} | {verdict} | {domain} | {title} | {url} | {reason} | "
                "{duplicate_of} | {query} |".format(
                    score="n/a" if row.fit_score is None else f"{row.fit_score:.3f}",
                    verdict=_escape(row.triage_verdict),
                    domain=_escape(row.domain),
                    title=_escape(row.title or ""),
                    url=_escape(row.url),
                    reason=_escape(row.triage_reason or ""),
                    duplicate_of=_escape(row.duplicate_of or ""),
                    query=_escape(row.query),
                )
            )
        if entity_type == "actor":
            actor_rows = [row for row in rows if row.page_fetched]
            if actor_rows:
                record_headers = [field.replace("_", " ").title() for field in ACTOR_RECORD_FIELDS]
                lines.extend(
                    [
                        "",
                        "#### Fetched actor record previews",
                        "",
                        "| "
                        + " | ".join(
                            [
                                *record_headers,
                                "Sectors",
                                "Hubs",
                                "Rubric Score",
                                "Rerank Position",
                                "Band",
                                "Rubric Evidence",
                            ]
                        )
                        + " |",
                        "| "
                        + " | ".join(["---"] * (len(ACTOR_RECORD_FIELDS) + 6))
                        + " |",
                    ]
                )
                for row in actor_rows:
                    record = row.record_preview or {}
                    lines.append(
                        "| "
                        + " | ".join(
                            _escape(_display(record.get(field)))
                            for field in ACTOR_RECORD_FIELDS
                        )
                        + " | "
                        + " | ".join(
                            [
                                _escape(", ".join(row.sector_codes)),
                                _escape(", ".join(row.hub_matches)),
                                _format_score(row.fit_score),
                                str(row.rerank_position or ""),
                                _escape(row.score_band or ""),
                                _escape(_rubric_summary(row.rubric or {})),
                            ]
                        )
                        + " |"
                    )
        elif entity_type == "event":
            event_rows = [row for row in rows if row.page_fetched]
            if event_rows:
                lines.extend(
                    [
                        "",
                        "#### Fetched event record previews",
                        "",
                        "| "
                        + " | ".join(
                            [
                                "Source URL",
                                "Verdict",
                                "Reason",
                                *[field.replace("_", " ").title() for field in EVENT_REPORT_FIELDS],
                                "Rubric Score",
                                "Qualification Paths",
                                "Rerank Position",
                                "Band",
                                "Rubric Evidence",
                            ]
                        )
                        + " |",
                        "| "
                        + " | ".join(["---"] * (len(EVENT_REPORT_FIELDS) + 8))
                        + " |",
                    ]
                )
                for row in event_rows:
                    record = row.record_preview or {}
                    lines.append(
                        "| "
                        + " | ".join(
                            [
                                _escape(row.url),
                                _escape(row.triage_verdict),
                                _escape(row.triage_reason or ""),
                                *[
                                    _escape(_display(_event_record_value(record, field)))
                                    for field in EVENT_REPORT_FIELDS
                                ],
                            ]
                        )
                        + " | "
                        + " | ".join(
                            [
                                _format_score(row.fit_score),
                                _escape(", ".join(row.qualification_paths)),
                                str(row.rerank_position or ""),
                                _escape(row.score_band or ""),
                                _escape(_rubric_summary(row.rubric or {})),
                            ]
                        )
                        + " |"
                    )
        elif entity_type == "person":
            person_rows = [row for row in rows if row.page_fetched]
            if person_rows:
                lines.extend(
                    [
                        "",
                        "#### Fetched person record previews",
                        "",
                        "| "
                        + " | ".join(
                            [
                                *[field.replace("_", " ").title() for field in PERSON_FIELDS],
                                "Rubric Score",
                                "Band",
                                "Identity Outcome",
                                "Rerank Position",
                                "Rubric Evidence",
                            ]
                        )
                        + " |",
                        "| " + " | ".join(["---"] * (len(PERSON_FIELDS) + 5)) + " |",
                    ]
                )
                for row in person_rows:
                    record = row.record_preview or {}
                    lines.append(
                        "| "
                        + " | ".join(
                            _escape(_display(record.get(field))) for field in PERSON_FIELDS
                        )
                        + " | "
                        + " | ".join(
                            [
                                _format_score(row.fit_score),
                                _escape(row.score_band or ""),
                                _escape(row.identity_outcome or ""),
                                str(row.rerank_position or ""),
                                _escape(_rubric_summary(row.rubric or {})),
                            ]
                        )
                        + " |"
                    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_candidate_spreadsheet(path: Path, candidates: list[CandidateRecord]) -> None:
    """Write fetched record previews as a flat reviewer-ready CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    event_rows = [
        candidate
        for candidate in candidates
        if candidate.entity_type == "event" and candidate.page_fetched
    ]
    if event_rows:
        _write_event_spreadsheet(path, event_rows)
        return
    person_rows = [
        candidate
        for candidate in candidates
        if candidate.entity_type == "person" and candidate.page_fetched
    ]
    if person_rows:
        _write_person_spreadsheet(path, person_rows)
        return
    fields = [
        "candidate_id",
        "url",
        "triage_verdict",
        "triage_reason",
        *V2_ACTOR_EXPORT_FIELDS,
        *ACTOR_RECORD_FIELDS,
        "sector_codes",
        "hub_matches",
        "rubric_score",
        "rerank_position",
        "rerank_rationale",
        "band",
        "rubric_evidence",
    ]
    rows = [
        candidate
        for candidate in candidates
        if candidate.entity_type == "actor" and candidate.page_fetched
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in rows:
            record = candidate.record_preview or {}
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "url": candidate.url,
                    "triage_verdict": candidate.triage_verdict,
                    "triage_reason": candidate.triage_reason,
                    **{field: _display(record.get(field)) for field in V2_ACTOR_EXPORT_FIELDS},
                    **{field: _display(record.get(field)) for field in ACTOR_RECORD_FIELDS},
                    "sector_codes": "; ".join(candidate.sector_codes),
                    "hub_matches": "; ".join(candidate.hub_matches),
                    "rubric_score": candidate.fit_score,
                    "rerank_position": candidate.rerank_position,
                    "rerank_rationale": candidate.rerank_reason,
                    "band": candidate.score_band,
                    "rubric_evidence": json.dumps(
                        candidate.rubric or {}, ensure_ascii=False, sort_keys=True
                    ),
                }
            )


def _write_event_spreadsheet(path: Path, rows: list[CandidateRecord]) -> None:
    fields = [
        "candidate_id",
        "url",
        "triage_verdict",
        "triage_reason",
        *EVENT_REPORT_FIELDS,
        "rubric_score",
        "qualification_paths",
        "band",
        "rerank_position",
        "rerank_rationale",
        "rubric_evidence",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in rows:
            record = candidate.record_preview or {}
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "url": candidate.url,
                    "triage_verdict": candidate.triage_verdict,
                    "triage_reason": candidate.triage_reason,
                    **{
                        field: _display(_event_record_value(record, field))
                        for field in EVENT_REPORT_FIELDS
                    },
                    "rubric_score": candidate.fit_score,
                    "qualification_paths": "; ".join(candidate.qualification_paths),
                    "band": candidate.score_band,
                    "rerank_position": candidate.rerank_position,
                    "rerank_rationale": candidate.rerank_reason,
                    "rubric_evidence": json.dumps(
                        candidate.rubric or {}, ensure_ascii=False, sort_keys=True
                    ),
                }
            )


def _write_person_spreadsheet(path: Path, rows: list[CandidateRecord]) -> None:
    fields = [
        "candidate_id",
        "url",
        *PERSON_FIELDS,
        "rubric_score",
        "band",
        "identity_outcome",
        "rerank_position",
        "rerank_rationale",
        "rubric_evidence",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in rows:
            record = candidate.record_preview or {}
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "url": candidate.url,
                    **{field: _display(record.get(field)) for field in PERSON_FIELDS},
                    "rubric_score": candidate.fit_score,
                    "band": candidate.score_band,
                    "identity_outcome": candidate.identity_outcome,
                    "rerank_position": candidate.rerank_position,
                    "rerank_rationale": candidate.rerank_reason,
                    "rubric_evidence": json.dumps(
                        candidate.rubric or {}, ensure_ascii=False, sort_keys=True
                    ),
                }
            )


def write_rejection_report(
    path: Path,
    *,
    run_id: str,
    status: str,
    status_reason: str,
    candidates: list[CandidateRecord],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rejected = [row for row in candidates if row.triage_verdict == "rejected"]
    grouped: dict[str, list[CandidateRecord]] = defaultdict(list)
    for candidate in rejected:
        grouped[candidate.triage_reason or "unspecified rejection"].append(candidate)

    lines = [
        f"# Open-Web Rejections: {run_id}",
        "",
        f"Status: **{status}**",
        "",
        f"Rejected candidates: **{len(rejected)}**",
    ]
    if status_reason:
        lines.extend(["", f"Run reason: {status_reason}"])
    if not grouped:
        lines.extend(["", "No rejected candidates."])
    for reason in sorted(grouped, key=str.casefold):
        rows = sorted(grouped[reason], key=lambda row: (row.domain, row.title or "", row.url))
        lines.extend(
            [
                "",
                f"## {_escape(reason)} ({len(rows)})",
                "",
                "| Score | Entity | Domain | Title | URL | Query |",
                "| ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                "| {score} | {entity} | {domain} | {title} | {url} | {query} |".format(
                    score="n/a" if row.fit_score is None else f"{row.fit_score:.3f}",
                    entity=_escape(row.entity_type),
                    domain=_escape(row.domain),
                    title=_escape(row.title or ""),
                    url=_escape(row.url),
                    query=_escape(row.query),
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _format_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _evidence_signal_summary(signals: dict[str, str | None]) -> str:
    return "; ".join(
        f"{name}: {evidence}"
        for name, evidence in signals.items()
        if evidence
    ) or "none"


def _rubric_summary(rubric: dict[str, object]) -> str:
    parts: list[str] = []
    for name, value in rubric.items():
        if name == "use_cases" and isinstance(value, dict):
            for use_case, item in value.items():
                if isinstance(item, dict) and item.get("present") is True:
                    parts.append(f"{use_case}: {item.get('evidence')}")
        elif name in {"sector_codes", "hub_matches"} and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    label = item.get("code") or item.get("name")
                    parts.append(f"{name}.{label}: {item.get('evidence')}")
        elif isinstance(value, dict) and value.get("present") is True:
            parts.append(f"{name}: {value.get('evidence')}")
    return "; ".join(parts) or "none"


def _display(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _event_record_value(record: dict[str, object], field: str) -> object:
    if field == "name":
        return record.get("title")
    if field == "sector_codes":
        return record.get("sector_codes") or []
    if field not in EVENT_FIELDS:
        return None
    return record.get(field)


def _candidate_sort_key(row: CandidateRecord) -> tuple[object, ...]:
    if row.entity_type in {"actor", "event"} and row.rerank_position is not None:
        return (0, row.rerank_position, row.domain, row.title or "")
    return (
        1,
        -1.0 if row.fit_score is None else -row.fit_score,
        row.domain,
        row.title or "",
    )
