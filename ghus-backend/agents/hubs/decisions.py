"""Append-only GHUS decision boundary for Phase 7 hub proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text

DECISIONS = frozenset({"approve", "rename", "reject", "set_radius"})


@dataclass(frozen=True)
class HubProposalDecisionPlan:
    proposed_hub_id: str
    decision: str
    decided_by: str
    final_name: str | None
    final_radius_miles: float | None
    notes: str | None
    resulting_status: str


def apply_hub_proposal_decision(
    session,
    *,
    proposed_hub_id: str,
    decision: str,
    decided_by: str,
    final_name: str | None = None,
    final_radius_miles: float | None = None,
    notes: str | None = None,
    live: bool = False,
) -> HubProposalDecisionPlan:
    """Validate and optionally append a decision; never create a canonical hub."""
    decision = decision.strip().casefold()
    reviewer = decided_by.strip()
    if decision not in DECISIONS:
        raise ValueError(f"unsupported hub proposal decision: {decision}")
    if not reviewer:
        raise ValueError("decided_by is required")
    if decision == "rename" and not (final_name or "").strip():
        raise ValueError("rename requires final_name")
    if decision == "set_radius" and not (
        final_radius_miles is not None and 0 < final_radius_miles <= 200
    ):
        raise ValueError("set_radius requires a radius in (0, 200]")
    row = session.execute(
        text(
            "SELECT proposal_kind,status FROM proposed_hub "
            "WHERE proposed_hub_id=CAST(:id AS uuid) FOR SHARE"
        ),
        {"id": proposed_hub_id},
    ).mappings().one_or_none()
    if row is None:
        raise ValueError("unknown proposed_hub_id")
    if row["proposal_kind"] != "deterministic_cluster":
        raise ValueError("Phase 7 decisions require a deterministic_cluster proposal")
    if row["status"] not in {"pending", "open"}:
        raise ValueError("hub proposal is already terminal")
    canonical_contract = row["status"] == "open"
    if canonical_contract:
        resulting_status = {
            "approve": "approved",
            "rename": "renamed",
            "reject": "rejected",
        }.get(decision, "open")
    else:
        resulting_status = {"approve": "accepted", "reject": "rejected"}.get(
            decision, "pending"
        )
    plan = HubProposalDecisionPlan(
        proposed_hub_id,
        decision,
        reviewer,
        final_name.strip() if final_name else None,
        final_radius_miles,
        notes.strip() if notes else None,
        resulting_status,
    )
    if not live:
        return plan
    session.execute(
        text(
            "INSERT INTO proposed_hub_decision (proposed_hub_decision_id,proposed_hub_id,decision,"
            "final_name,final_radius_miles,decided_by,notes) VALUES (CAST(:decision_id AS uuid),"
            "CAST(:proposal_id AS uuid),:decision,:final_name,:final_radius,:decided_by,:notes)"
        ),
        {
            "decision_id": str(uuid.uuid4()),
            "proposal_id": proposed_hub_id,
            "decision": decision,
            "final_name": plan.final_name,
            "final_radius": final_radius_miles,
            "decided_by": reviewer,
            "notes": plan.notes,
        },
    )
    if resulting_status not in {"pending", "open"}:
        session.execute(
            text(
                "UPDATE proposed_hub SET status=:status,reviewed_by=:reviewer,reviewed_at=now() "
                "WHERE proposed_hub_id=CAST(:id AS uuid) AND status=:current_status"
            ),
            {
                "id": proposed_hub_id,
                "status": resulting_status,
                "reviewer": reviewer,
                "current_status": row["status"],
            },
        )
    return plan
