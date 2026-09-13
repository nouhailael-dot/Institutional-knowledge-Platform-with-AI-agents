"""Markdown reporting for open-web discovery candidates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from agents.discovery.search.models import CandidateRecord
from agents.discovery.search.triage import ACTOR_USE_CASES


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
        rows = sorted(
            grouped[entity_type],
            key=lambda row: (-1.0 if row.fit_score is None else -row.fit_score, row.domain, row.title or ""),
        )
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
            actor_rows = [row for row in rows if row.engagement_signals is not None]
            if actor_rows:
                use_case_counts = {
                    name: sum(bool((row.use_case_fit or {}).get(name)) for row in actor_rows)
                    for name, _label in ACTOR_USE_CASES
                }
                lines.extend(
                    [
                        "",
                        "#### Actor evidence",
                        "",
                        "Use-case evidence counts: "
                        + "; ".join(
                            f"{label}: {use_case_counts[name]}"
                            for name, label in ACTOR_USE_CASES
                        ),
                        "",
                        (
                            "| Domain | Sector relevance | Engagement route | Strategic value | "
                            "Distinctiveness | Existing actors | Hubs | Sectors | Route signals | "
                            "Use-case fit | Condition evidence |"
                        ),
                        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
                    ]
                )
                for row in actor_rows:
                    lines.append(
                        "| {domain} | {sector} | {engagement} | {strategic} | "
                        "{distinctiveness} | {count} | {hubs} | {sectors} | {signals} | "
                        "{use_cases} | {conditions} |".format(
                            domain=_escape(row.domain),
                            sector=_format_score(row.sector_relevance),
                            engagement=_format_score(row.engagement_route),
                            strategic=_format_score(row.strategic_ecosystem_value),
                            distinctiveness=_format_score(row.distinctiveness),
                            count=(
                                "n/a"
                                if row.existing_actor_count is None
                                else str(row.existing_actor_count)
                            ),
                            hubs=_escape(", ".join(row.hub_matches)),
                            sectors=_escape(", ".join(row.sector_codes)),
                            signals=_escape(
                                _evidence_signal_summary(row.engagement_signals or {})
                            ),
                            use_cases=_escape(
                                _evidence_signal_summary(row.use_case_fit or {})
                            ),
                            conditions=_escape(
                                _evidence_signal_summary(row.condition_evidence or {})
                            ),
                        )
                    )
        elif entity_type == "person":
            person_rows = [row for row in rows if row.relevance_signals is not None]
            if person_rows:
                lines.extend(
                    [
                        "",
                        "#### Relevance evidence",
                        "",
                        "| Domain | Relevance | Hubs | Sectors | Signals |",
                        "| --- | ---: | --- | --- | --- |",
                    ]
                )
                for row in person_rows:
                    lines.append(
                        "| {domain} | {score} | {hubs} | {sectors} | {signals} |".format(
                            domain=_escape(row.domain),
                            score=_format_score(row.fit_score),
                            hubs=_escape(", ".join(row.hub_matches)),
                            sectors=_escape(", ".join(row.sector_codes)),
                            signals=_escape(_evidence_signal_summary(row.relevance_signals or {})),
                        )
                    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
