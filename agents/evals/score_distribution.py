"""Compare staged actor ER scores to the frozen model's validation reference.

This is a read-only guardrail before allowing actor auto-absorb. It scores staged
actor records against canonical actors through agents.common.resolve_route, which
uses the existing frozen EntityResolver blocking and combiner scoring path.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from agents.common.resolve_route import load_actor_resolver_class, route_actor


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_staged_actor_records(
    session, *, limit: int, run_id: Optional[str] = None
) -> list[dict[str, object]]:
    where = ["entity_type = 'actor'", "sector_match = 'in_sector'"]
    params: dict[str, object] = {"limit": int(limit)}
    if run_id:
        where.append("run_id = CAST(:run_id AS uuid)")
        params["run_id"] = run_id
    rows = (
        session.execute(
            text(
                "SELECT staged_record_id::text AS staged_record_id, natural_key, normalized_payload "
                "FROM staged_record WHERE "
                + " AND ".join(where)
                + " ORDER BY updated_at DESC, staged_record_id DESC LIMIT :limit"
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def score_records(
    session, *, root: Path, limit: int, run_id: Optional[str] = None
) -> dict[str, object]:
    records = load_staged_actor_records(session, limit=limit, run_id=run_id)
    if not records:
        raise RuntimeError("no staged in-sector actor records found to score")
    resolver = load_actor_resolver_class()(session, project_root=root)
    scored: list[dict[str, object]] = []
    for row in records:
        decision = route_actor(dict(row["normalized_payload"] or {}), resolver)
        scored.append(
            {
                "staged_record_id": row["staged_record_id"],
                "natural_key": row["natural_key"],
                "score": decision.score,
                "zone": decision.zone,
                "target_entity_id": decision.target_entity_id,
                "candidate_count": len(decision.candidate_ids),
                "matched_name": decision.metadata.get("matched_name"),
            }
        )
    return summarize(
        scored,
        root=root,
        model_name=str(getattr(resolver, "model_name", "combiner")),
        high=float(resolver.HIGH),
    )


def summarize(
    scored: list[dict[str, object]], *, root: Path, model_name: str, high: float
) -> dict[str, object]:
    scores = [float(row["score"]) for row in scored]
    validation = json.loads(
        (root / "config" / "er_production.json").read_text(encoding="utf-8")
    ).get("validated_on", {})
    return {
        "model": model_name,
        "sample_size": len(scores),
        "mean": statistics.fmean(scores),
        "median": statistics.median(scores),
        "share_above_high": sum(score >= high for score in scores) / len(scores),
        "high_threshold_source": "config/er_production.json via EntityResolver",
        "oof_reference": validation,
        "oof_score_artifact": _oof_artifact_status(root, model_name),
        "rows": scored,
    }


def to_markdown(summary: dict[str, object]) -> str:
    reference = dict(summary.get("oof_reference") or {})
    artifact = dict(summary.get("oof_score_artifact") or {})
    return "\n".join(
        [
            "# Actor ER Score Distribution",
            "",
            f"Model: `{summary['model']}`",
            f"Sample size: {summary['sample_size']}",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Mean score | {float(summary['mean']):.6f} |",
            f"| Median score | {float(summary['median']):.6f} |",
            f"| Share above HIGH | {float(summary['share_above_high']):.6f} |",
            "",
            "## Out-of-Fold Reference",
            "",
            f"Source: `{summary['high_threshold_source']}`",
            f"Pairs: {reference.get('pairs', 'unknown')}",
            f"Positives: {reference.get('positives', 'unknown')}",
            f"OOF precision: {reference.get('oof_precision', 'unknown')}",
            f"OOF coverage / share above HIGH: {reference.get('oof_coverage', 'unknown')}",
            f"OOF false merges: {reference.get('oof_false_merges', 'unknown')}",
            "",
            "## Score Artifact",
            "",
            artifact.get("message", "No score artifact status available."),
            "",
            "Thresholds are reported only; this script does not adjust them.",
        ]
    )


def _oof_artifact_status(root: Path, model_name: str) -> dict[str, str]:
    pair_scores = root / "docs" / "ml" / "results" / "er_eval" / "pair_scores.csv"
    if not pair_scores.exists():
        return {"message": "No saved pair-score artifact found."}
    header = pair_scores.read_text(encoding="utf-8").splitlines()[0].split(",")
    expected = f"score_{model_name}"
    if expected not in header:
        return {
            "message": (
                f"`{pair_scores}` exists, but it has no `{expected}` column, so this run "
                "uses the production config's OOF metrics instead of claiming a score-level comparison."
            )
        }
    return {"message": f"`{pair_scores}` contains `{expected}` for score-level comparison."}


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--run-id")
    parser.add_argument("--out")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    from src.db.session import SessionLocal

    root = project_root()
    with SessionLocal() as session:
        summary = score_records(session, root=root, limit=args.limit, run_id=args.run_id)
    markdown = to_markdown(summary)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
