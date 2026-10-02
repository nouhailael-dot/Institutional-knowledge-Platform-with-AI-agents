"""Run Architecture V2 new-hub detection; dry-run is the default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from agents.common.hub_detection import HubDetectionConfig
from agents.hubs.detect import execute_hub_detection
from src.db.session import SessionLocal

ROOT = Path(__file__).resolve().parents[1]


def _config() -> HubDetectionConfig:
    raw = yaml.safe_load((ROOT / "config" / "architecture_v2.yaml").read_text(encoding="utf-8"))
    values = raw["hubs"]["detection"]
    return HubDetectionConfig(
        trigger_statuses=tuple(values["hub_trigger_statuses"]),
        minimum_families=int(values["hub_min_actors"]),
        minimum_categories=int(values["hub_min_categories"]),
        core_radius_miles=float(values["hub_core_radius_miles"]),
        radius_miles=float(values["hub_radius_miles"]),
        method_version=str(values["proposal_method_version"]),
        fingerprint_version=str(values["family_fingerprint_version"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="persist proposals after all gates pass")
    parser.add_argument(
        "--apply-existing-assignments",
        action="store_true",
        help="route same-topic existing-hub memberships through the approved canonical writer",
    )
    args = parser.parse_args()
    if args.apply_existing_assignments and not args.live:
        parser.error("--apply-existing-assignments requires --live")
    if args.live and os.getenv("HUB_DETECTION_WRITES_ENABLED", "").casefold() != "true":
        parser.error("live mode requires HUB_DETECTION_WRITES_ENABLED=true")
    with SessionLocal() as session:
        execution = execute_hub_detection(
            session,
            _config(),
            live=args.live,
            apply_existing_assignments=args.apply_existing_assignments,
        )
    summary = {
        "dry_run": execution.dry_run,
        "run_id": execution.run_id,
        "eligible_actor_count": len(execution.result.eligible_actor_ids),
        "proposal_count": len(execution.result.proposals),
        "suppression_count": len(execution.result.suppressions),
        "prerequisite_exclusion_count": len(execution.result.prerequisite_exclusions),
        "unresolved_hierarchy_count": len(execution.result.unresolved_hierarchy),
        "verified_plus_imported_comparison_proposal_count": len(
            execution.verified_plus_imported_comparison.proposals
        ),
        "proposals": [proposal.payload() for proposal in execution.result.proposals],
        "suppressions": [
            {
                "reason": item.reason,
                "topic_id": item.topic_id,
                "center_city": item.center_city,
                "actor_ids": list(item.actor_ids),
                "family_fingerprint": item.family_fingerprint,
                "existing_hub_id": item.existing_hub_id,
            }
            for item in execution.result.suppressions
        ],
        "prerequisite_exclusions": execution.result.prerequisite_exclusions,
        "unresolved_hierarchy": execution.result.unresolved_hierarchy,
        "verified_plus_imported_comparison_proposals": [
            proposal.payload()
            for proposal in execution.verified_plus_imported_comparison.proposals
        ],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
