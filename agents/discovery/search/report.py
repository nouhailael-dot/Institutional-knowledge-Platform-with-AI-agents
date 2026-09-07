"""Markdown reporting for open-web discovery candidates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from agents.discovery.search.models import CandidateRecord


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
                "| Score | Verdict | Domain | Title | URL | Reason | Query |",
                "| ---: | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                "| {score} | {verdict} | {domain} | {title} | {url} | {reason} | {query} |".format(
                    score="n/a" if row.fit_score is None else f"{row.fit_score:.3f}",
                    verdict=_escape(row.triage_verdict),
                    domain=_escape(row.domain),
                    title=_escape(row.title or ""),
                    url=_escape(row.url),
                    reason=_escape(row.triage_reason or ""),
                    query=_escape(row.query),
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
