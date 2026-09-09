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
        if entity_type == "actor":
            actor_rows = [row for row in rows if row.partner_signals is not None]
            if actor_rows:
                lines.extend(
                    [
                        "",
                        "#### Partner evidence",
                        "",
                        "| Domain | Partner | Distinctiveness | Existing actors | Hubs | Sectors | Signals |",
                        "| --- | ---: | ---: | ---: | --- | --- | --- |",
                    ]
                )
                for row in actor_rows:
                    lines.append(
                        "| {domain} | {partner} | {distinctiveness} | {count} | {hubs} | "
                        "{sectors} | {signals} |".format(
                            domain=_escape(row.domain),
                            partner=_format_score(row.partner_findability),
                            distinctiveness=_format_score(row.distinctiveness),
                            count=(
                                "n/a"
                                if row.existing_actor_count is None
                                else str(row.existing_actor_count)
                            ),
                            hubs=_escape(", ".join(row.hub_matches)),
                            sectors=_escape(", ".join(row.sector_codes)),
                            signals=_escape(_partner_signal_summary(row.partner_signals or {})),
                        )
                    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _format_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _partner_signal_summary(signals: dict[str, str | None]) -> str:
    return "; ".join(
        f"{name}: {evidence}"
        for name, evidence in signals.items()
        if evidence
    ) or "none"
