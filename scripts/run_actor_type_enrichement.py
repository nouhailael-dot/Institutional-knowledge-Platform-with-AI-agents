from agents.enrichment.decisions import persist_canonical_record

"""
Run actor-type enrichment over actors the rule extractor left as 'other'.

Conventions carried over from the four ETL translators:
- Creates one ai_inference Source row per applied run; every changed actor
  points back to it (provenance is non-negotiable).
- Writes a per-row verdict to an audit CSV in data/interim/.
- One transaction: commits on success, rolls back on dry-run.
- Loud failure: a row that errors is logged and skipped; the run exits non-zero
  if any row failed.
- Idempotent: only touches actors still typed 'other' or NULL, so re-running
  never reprocesses ones already promoted.

Usage (from the repo root, venv active):
    python scripts/run_actor_type_enrichment.py --limit 15        # dry-run a sample
    python scripts/run_actor_type_enrichment.py                   # dry-run all
    python scripts/run_actor_type_enrichment.py --apply           # write changes
"""

import argparse
import csv
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root on path

from sqlalchemy import func, select  # noqa: E402
from src.enrichment.claude_client import HAIKU  # noqa: E402

from src.db.models import Actor, Source  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402
from src.enrichment.extractors.actor_type import classify_actor  # noqa: E402

OTHER = "other"
APPLY_THRESHOLD = 0.70  # only write a type the model is at least this sure of
INTERIM = pathlib.Path("data/interim")


def derive_candidate_types(session) -> list[str]:
    """Canonical vocab = the non-'other' actor_type values already in the DB."""
    rows = session.execute(
        select(Actor.actor_type)
        .where(Actor.actor_type.isnot(None), Actor.actor_type != OTHER)
        .group_by(Actor.actor_type)
        .order_by(func.count().desc())
    ).all()
    return [r[0] for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N actors (use a small N to preview)")
    ap.add_argument("--apply", action="store_true",
                    help="write changes; without this flag the run is a dry-run")
    ap.add_argument("--model", default=HAIKU, help="Anthropic model id")
    args = ap.parse_args()

    INTERIM.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = INTERIM / f"actor_type_enrichment_{stamp}.csv"

    session = SessionLocal()
    try:
        candidates = derive_candidate_types(session)
        if not candidates:
            print("No canonical actor types in the DB yet — ingest/seed first.")
            sys.exit(1)
        print(f"Candidate types ({len(candidates)}): {', '.join(candidates)}")

        query = select(Actor).where(
            (Actor.actor_type == OTHER) | (Actor.actor_type.is_(None))
        )
        if args.limit:
            query = query.limit(args.limit)
        actors = session.execute(query).scalars().all()
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] actors to classify: {len(actors)}\n")

        source = None
        if args.apply:
            source = Source(
                source_type="ai_inference",
                description=f"Phase 4 actor-type classification ({args.model})",
                trust_tier="low",
            )
            persist_canonical_record(session, source)
            session.flush()  # get source_id without committing

        applied = would_apply = low_or_other = failed = 0
        with audit_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["actor_id", "name", "old_type", "predicted_type",
                             "confidence", "applied", "reasoning"])
            for i, actor in enumerate(actors, 1):
                old_type = actor.actor_type if actor.actor_type is not None else "(null)"
                try:
                    result = classify_actor(actor.name, actor.description,
                                            candidates, model=args.model)
                except Exception as err:  # one bad row must not kill the run
                    failed += 1
                    writer.writerow([actor.actor_id, actor.name, old_type,
                                     "", "", "ERROR", str(err)[:200]])
                    print(f"[{i}/{len(actors)}] FAIL  {actor.name}: {err}")
                    continue

                pred, conf = result["actor_type"], result["confidence"]
                qualifies = pred != OTHER and conf >= APPLY_THRESHOLD
                would_apply += qualifies
                do_write = args.apply and qualifies
                if do_write:
                    actor.actor_type = pred
                    actor.verification_status = "needs_review"
                    actor.confidence = round(conf, 2)
                    actor.source_id = source.source_id
                    applied += 1
                else:
                    low_or_other += 1

                writer.writerow([actor.actor_id, actor.name, old_type, pred,
                                 f"{conf:.2f}", "yes" if do_write else "no",
                                 result["reasoning"]])
                flag = " APPLIED" if do_write else (" (low/other)" if not qualifies else "")
                print(f"[{i}/{len(actors)}] {actor.name} -> {pred} ({conf:.2f}){flag}")

        if args.apply:
            session.commit()
            print(f"\nCommitted. applied={applied}  held_back={low_or_other}  failed={failed}")
        else:
            session.rollback()
            print(f"\nDry-run only — nothing written. would_apply={would_apply}  "
                  f"held_back={low_or_other}  failed={failed}")
        print(f"Audit log: {audit_path}")

        if failed:
            sys.exit(2)  # loud failure, per ETL conventions
    finally:
        session.close()


if __name__ == "__main__":
    main()