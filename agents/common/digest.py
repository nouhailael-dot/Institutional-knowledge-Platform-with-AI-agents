"""Short weekly discovery digest generation."""

from __future__ import annotations

from pathlib import Path


def build_digest(
    *,
    run_id: str,
    source: str,
    entity_type: str,
    status: str,
    stats: dict[str, object],
) -> str:
    llm = dict(stats.get("llm", {}) or {})
    cost = dict(stats.get("cost", {}) or {})
    cost_usd = stats.get("cost_usd", cost.get("spent_usd", 0.0))
    lines = [
        "# Weekly Discovery Digest",
        "",
        f"**Status:** {status}",
        f"**Run:** `{run_id}`",
        f"**Source:** `{source}`",
        f"**Entity:** `{entity_type}`",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Records fetched | {_count(stats, 'documents_fetched')} |",
        f"| Skipped unchanged | {_count(stats, 'skipped_unchanged')} |",
        f"| Extracted | {_count(stats, 'records_extracted')} |",
        f"| In-sector staged | {_count(stats, 'records_in_sector')} |",
        f"| Out-of-sector staged | {_count(stats, 'records_out_of_sector')} |",
        f"| Absorbed | {_count(stats, 'absorbed')} |",
        f"| Queued for review | {_count(stats, 'queued_for_review')} |",
        f"| Created | {_count(stats, 'created')} |",
        f"| Failures | {_count(stats, 'failures')} |",
        "",
        "| Cost | Value |",
        "|---|---:|",
        f"| LLM calls | {int(llm.get('calls', 0) or 0)} |",
        f"| Input tokens | {int(llm.get('input_tokens', 0) or 0):,} |",
        f"| Output tokens | {int(llm.get('output_tokens', 0) or 0):,} |",
        f"| USD | ${float(cost_usd or 0.0):.6f} |",
    ]
    if stats.get("audit_csv"):
        lines.extend(["", f"Audit CSV: `{stats['audit_csv']}`"])
    if stats.get("attention_required"):
        lines.extend(["", "**Attention Required:** yes"])
        if stats.get("skipped_reason"):
            lines.append(f"Reason: {stats['skipped_reason']}")
    return "\n".join(lines) + "\n"


def write_digest(path: Path, *, run_id: str, source: str, entity_type: str, status: str, stats: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_digest(run_id=run_id, source=source, entity_type=entity_type, status=status, stats=stats),
        encoding="utf-8",
        newline="\n",
    )


def _count(stats: dict[str, object], key: str) -> int:
    return int(stats.get(key, 0) or 0)
