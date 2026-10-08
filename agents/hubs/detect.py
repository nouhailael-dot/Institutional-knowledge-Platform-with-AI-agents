"""Snapshot-based execution boundary for Architecture V2 hub detection."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace

from sqlalchemy import text

from agents.common.hub_detection import (
    DetectionActor,
    HubDetectionConfig,
    HubDetectionResult,
    TrustedHub,
    detect_new_hubs,
)
from agents.common.hub_families import FamilyEdge
from agents.common.provenance import insert_source
from agents.discovery.promote import persist_hub_assignment_plan


@dataclass(frozen=True)
class DetectionSnapshot:
    actors: tuple[DetectionActor, ...]
    edges: tuple[FamilyEdge, ...]
    existing_hubs: tuple[TrustedHub, ...]
    prior_fingerprints: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DetectionExecution:
    dry_run: bool
    result: HubDetectionResult
    verified_plus_imported_comparison: HubDetectionResult
    run_id: str | None = None


def compute_detection_snapshot(
    snapshot: DetectionSnapshot, config: HubDetectionConfig
) -> tuple[HubDetectionResult, HubDetectionResult]:
    """Compute both required views from one immutable database snapshot."""
    result = detect_new_hubs(
        snapshot.actors,
        snapshot.edges,
        snapshot.existing_hubs,
        snapshot.prior_fingerprints,
        config,
    )
    comparison = detect_new_hubs(
        snapshot.actors,
        snapshot.edges,
        snapshot.existing_hubs,
        snapshot.prior_fingerprints,
        replace(config, trigger_statuses=("verified", "imported")),
    )
    return result, comparison


def _relation_exists(session, name: str) -> bool:
    return bool(
        session.execute(text(f"SELECT to_regclass('public.{name}') IS NOT NULL")).scalar()
    )


def load_detection_snapshot(session) -> DetectionSnapshot:
    """Load everything detection needs, in one read.

    Actors are still loaded per topic row, because the topic is recorded on
    every proposal as secondary evidence. What each actor's SECTORS are is
    attached alongside, and sector is what the clustering partitions on (GHUS
    decision, 2026-10-08).

    The sector tables arrive with migration 520. Until it is applied this loader
    returns actors with no sectors, and detection in sector mode then proposes
    nothing at all. That is the honest outcome: no sector data means no
    sector-based answer. It does not quietly fall back to the topic rule, which
    would re-apply the behaviour the decision replaced without anyone asking.
    """

    has_actor_sector = _relation_exists(session, "actor_sector")
    has_hub_sector = _relation_exists(session, "hub_sector")

    actor_rows = session.execute(
        text(
            "SELECT DISTINCT ON (a.actor_id,t.topic_id) a.actor_id,a.name,t.topic_id,"
            "t.name AS topic_name,COALESCE(to_jsonb(a)->>'status',to_jsonb(a)->>'record_status') "
            "AS record_status,a.actor_category,a.category_type,"
            "(a.merged_into_actor_id IS NOT NULL) AS merged,"
            "COALESCE(al.city,to_jsonb(a)->>'city',to_jsonb(a)->>'location_city') AS city,"
            "COALESCE(al.state_code,a.state_code,to_jsonb(a)->>'state') AS state_code,"
            "COALESCE(al.latitude,a.latitude) AS latitude,"
            "COALESCE(al.longitude,a.longitude) AS longitude "
            "FROM actor a JOIN actor_topic at ON at.actor_id=a.actor_id "
            "JOIN topic t ON t.topic_id=at.topic_id "
            "LEFT JOIN LATERAL (SELECT city,state_code,latitude,longitude FROM actor_location "
            "WHERE actor_id=a.actor_id ORDER BY is_primary DESC,created_at,actor_location_id "
            "LIMIT 1) al ON TRUE ORDER BY a.actor_id,t.topic_id"
        )
    ).mappings().all()

    sectors_by_actor: dict[str, set[str]] = {}
    if has_actor_sector:
        for row in session.execute(
            text(
                "SELECT asec.actor_id,s.code FROM actor_sector asec "
                "JOIN sector s ON s.sector_id=asec.sector_id "
                "WHERE s.active ORDER BY asec.actor_id,s.code"
            )
        ).mappings().all():
            sectors_by_actor.setdefault(str(row["actor_id"]), set()).add(str(row["code"]))

    assigned_rows = session.execute(
        text(
            "SELECT actor_id,topic_id FROM hub_actor WHERE topic_id IS NOT NULL "
            "AND assignment_outcome='assigned' ORDER BY actor_id,topic_id"
        )
    ).mappings().all()
    assigned: dict[str, set[str]] = {}
    for row in assigned_rows:
        assigned.setdefault(str(row["actor_id"]), set()).add(str(row["topic_id"]))

    # Which sectors an actor already sits in, so detection does not propose a
    # hub it already belongs to. Read through each hub's own primary sector.
    assigned_sectors: dict[str, set[str]] = {}
    if has_hub_sector:
        for row in session.execute(
            text(
                "SELECT ha.actor_id,s.code FROM hub_actor ha "
                "JOIN hub_sector hs ON hs.hub_id=ha.hub_id AND hs.is_primary "
                "JOIN sector s ON s.sector_id=hs.sector_id "
                "WHERE ha.assignment_outcome='assigned' ORDER BY ha.actor_id,s.code"
            )
        ).mappings().all():
            assigned_sectors.setdefault(str(row["actor_id"]), set()).add(str(row["code"]))

    actors = tuple(
        DetectionActor(
            actor_id=str(row["actor_id"]),
            name=str(row["name"]),
            topic_id=str(row["topic_id"]),
            topic_name=str(row["topic_name"]),
            city=row["city"],
            state_code=row["state_code"],
            latitude=float(row["latitude"]) if row["latitude"] is not None else None,
            longitude=float(row["longitude"]) if row["longitude"] is not None else None,
            record_status=str(row["record_status"]),
            actor_category=row["actor_category"],
            category_type=row["category_type"],
            assigned_topic_ids=frozenset(assigned.get(str(row["actor_id"]), ())),
            merged=bool(row["merged"]),
            sector_codes=frozenset(sectors_by_actor.get(str(row["actor_id"]), ())),
            assigned_sector_codes=frozenset(assigned_sectors.get(str(row["actor_id"]), ())),
        )
        for row in actor_rows
    )
    edge_rows = session.execute(
        text(
            "SELECT subject_id AS child_actor_id,object_id AS parent_actor_id,"
            "relationship_type FROM entity_edge WHERE subject_type='actor' "
            "AND object_type='actor' AND relationship_type IN ('unit_of','operated_by') "
            "ORDER BY subject_id,object_id,relationship_type"
        )
    ).mappings().all()
    edges = tuple(
        FamilyEdge(str(row["child_actor_id"]), str(row["parent_actor_id"]), row["relationship_type"])
        for row in edge_rows
    )

    hub_sector_select = (
        ",(SELECT s.code FROM hub_sector hs JOIN sector s ON s.sector_id=hs.sector_id "
        "WHERE hs.hub_id=h.hub_id AND hs.is_primary LIMIT 1) AS sector_code "
        if has_hub_sector else ",NULL AS sector_code "
    )
    hub_rows = session.execute(
        text(
            "SELECT h.hub_id,h.name,h.topic_id,h.center_latitude,h.center_longitude,"
            "h.radius_miles" + hub_sector_select + "FROM hub h ORDER BY h.hub_id"
        )
    ).mappings().all()
    hubs = tuple(
        TrustedHub(
            str(row["hub_id"]),
            str(row["name"]),
            str(row["topic_id"]) if row["topic_id"] else None,
            float(row["center_latitude"]) if row["center_latitude"] is not None else None,
            float(row["center_longitude"]) if row["center_longitude"] is not None else None,
            float(row["radius_miles"]) if row["radius_miles"] is not None else None,
            str(row["sector_code"]) if row["sector_code"] else None,
        )
        for row in hub_rows
    )

    # A rejected cluster is remembered against the dimension it was found on.
    # proposed_hub.dimension_key arrives with migration 530; without it, fall
    # back to the topic the proposal recorded, which is all there is to use.
    has_dimension_key = bool(
        session.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='proposed_hub' AND column_name='dimension_key'"
            )
        ).scalar()
    )
    key_column = (
        "COALESCE(dimension_key, topic_id::text)" if has_dimension_key else "topic_id::text"
    )
    fingerprints = tuple(
        (str(row["dimension_key"]), str(row["membership_fingerprint"]))
        for row in session.execute(
            text(
                f"SELECT {key_column} AS dimension_key,membership_fingerprint "
                "FROM proposed_hub "
                "WHERE proposal_kind='deterministic_cluster' AND topic_id IS NOT NULL "
                "AND membership_fingerprint IS NOT NULL ORDER BY 1,2"
            )
        ).mappings().all()
    )
    return DetectionSnapshot(actors, edges, hubs, fingerprints)


def execute_hub_detection(
    session,
    config: HubDetectionConfig,
    *,
    live: bool = False,
    apply_existing_assignments: bool = False,
) -> DetectionExecution:
    """Execute from one snapshot; live mode only persists proposals and delegated assignments."""
    transaction = session.begin() if live else None
    try:
        snapshot = load_detection_snapshot(session)
        result, comparison = compute_detection_snapshot(snapshot, config)
        if not live:
            return DetectionExecution(True, result, comparison)
        initial_status = _validate_persistence_compatibility(session, config)
        run_id = str(uuid.uuid4())
        session.execute(
            text(
                "INSERT INTO hub_detection_run (hub_detection_run_id,dry_run,trigger_statuses,"
                "method_version,config_snapshot,status,eligible_actor_count) VALUES "
                "(CAST(:id AS uuid),FALSE,CAST(:statuses AS jsonb),:method,CAST(:config AS jsonb),"
                "'running',:eligible)"
            ),
            {
                "id": run_id,
                "statuses": json.dumps(config.trigger_statuses),
                "method": config.method_version,
                "config": json.dumps(asdict(config), sort_keys=True),
                "eligible": len(result.eligible_actor_ids),
            },
        )
        for proposal in result.proposals:
            _persist_proposal(session, run_id, proposal, config, initial_status)
        if apply_existing_assignments:
            source_id = insert_source(
                session,
                source_url=f"urn:ghus:hub-detection:{run_id}",
                fetched_at=None,
                description="Architecture V2 hub-detection assignment routing",
                source_type="system",
                trust_tier="derived",
            )
            for suppression in result.suppressions:
                for actor_id, plan in suppression.assignment_plans:
                    persist_hub_assignment_plan(
                        session,
                        actor_id=actor_id,
                        topic_id=suppression.topic_id,
                        source_id=source_id,
                        plan=plan,
                    )
        session.execute(
            text(
                "UPDATE hub_detection_run SET status='completed',proposal_count=:proposals,"
                "suppression_count=:suppressions,completed_at=now() "
                "WHERE hub_detection_run_id=CAST(:id AS uuid)"
            ),
            {
                "id": run_id,
                "proposals": len(result.proposals),
                "suppressions": len(result.suppressions),
            },
        )
        transaction.commit()
        return DetectionExecution(False, result, comparison, run_id)
    except Exception:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        raise


def _validate_persistence_compatibility(session, config: HubDetectionConfig) -> str:
    required = {
        "proposed_hub": {
            "detection_run_id",
            "independence_statement",
            "detection_method_version",
            "fingerprint_version",
            "proposal_evidence",
            "trigger_statuses",
            "minimum_families_required",
            "minimum_categories_required",
        },
        "proposed_hub_member": {"category_type", "distance_miles_raw", "matched_category"},
    }
    rows = session.execute(
        text(
            "SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name = ANY(:tables)"
        ),
        {"tables": sorted(required)},
    ).all()
    actual: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual.setdefault(str(table_name), set()).add(str(column_name))
    missing = {
        table: sorted(columns - actual.get(table, set()))
        for table, columns in required.items()
        if columns - actual.get(table, set())
    }
    run_table = session.execute(
        text("SELECT to_regclass(current_schema() || '.hub_detection_run') IS NOT NULL")
    ).scalar_one()
    if missing or not run_table:
        details = {"missing_columns": missing, "missing_hub_detection_run": not run_table}
        raise RuntimeError(f"Phase 7 persistence schema is incompatible: {details}")
    definitions = {
        str(row[0]): str(row[1])
        for row in session.execute(
            text(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='proposed_hub'::regclass "
                "AND conname IN ('ck_proposed_hub_counts','ck_proposed_hub_core',"
                "'ck_proposed_hub_radius','ck_proposed_hub_kind',"
                "'proposed_hub_status_check')"
            )
        ).all()
    }
    count_definition = definitions.get("ck_proposed_hub_counts", "")
    frozen = bool(count_definition) and "minimum_families_required" not in count_definition
    incompatible = []
    if frozen and config.minimum_families < 10:
        incompatible.append("minimum_families below frozen value 10")
    if frozen and config.minimum_categories < 5:
        incompatible.append("minimum_categories below frozen value 5")
    if (
        "core_radius_miles <= radius_miles" not in definitions.get("ck_proposed_hub_core", "")
        and config.core_radius_miles != 50
    ):
        incompatible.append("core_radius_miles differs from frozen value 50")
    if config.radius_miles > 200:
        incompatible.append("radius_miles exceeds frozen maximum 200")
    kind_definition = definitions.get("ck_proposed_hub_kind", "")
    if kind_definition and "deterministic_cluster" not in kind_definition:
        incompatible.append("deterministic_cluster proposal kind is unavailable")
    if incompatible:
        raise RuntimeError(
            "Phase 7 runtime configuration is incompatible with the proposal schema: "
            + "; ".join(incompatible)
        )
    status_definition = definitions.get("proposed_hub_status_check", "")
    return "open" if "'open'" in status_definition else "pending"


def _persist_proposal(session, run_id, proposal, config, initial_status: str) -> None:
    proposal_id = str(uuid.uuid4())
    evidence = {
        "family_category_pairs": [list(pair) for pair in proposal.family_category_pairs],
        "matched_category_count": proposal.matched_category_count,
        "comparison_statuses_are_report_only": True,
    }
    if initial_status == "open":
        evidence["status_contract"] = "canonical_v2"
    session.execute(
        text(
            "INSERT INTO proposed_hub (proposed_hub_id,name,primary_city,state,country,rationale,"
            "source_table,source_row_id,proposed_by,status,proposal_kind,topic_id,center_latitude,"
            "center_longitude,radius_miles,core_radius_miles,independent_family_count,category_count,"
            "membership_fingerprint,detection_run_id,independence_statement,detection_method_version,"
            "fingerprint_version,proposal_evidence,trigger_statuses,minimum_families_required,"
            "minimum_categories_required) VALUES (CAST(:id AS uuid),:name,:city,:state,'US',"
            ":rationale,'hub_detection_run',CAST(:run_id AS uuid),'architecture_v2',:status,"
            "'deterministic_cluster',CAST(:topic_id AS uuid),:latitude,:longitude,:radius,:core,"
            ":families,:categories,:fingerprint,CAST(:run_id AS uuid),:statement,:method,:fp_version,"
            "CAST(:evidence AS jsonb),CAST(:statuses AS jsonb),:min_families,:min_categories)"
        ),
        {
            "id": proposal_id,
            "run_id": run_id,
            "name": proposal.suggested_name,
            "status": initial_status,
            "city": proposal.center_city,
            "state": proposal.center_state_code,
            "rationale": proposal.independence_statement,
            "topic_id": proposal.topic_id,
            "latitude": proposal.center_latitude,
            "longitude": proposal.center_longitude,
            "radius": proposal.radius_miles,
            "core": proposal.core_radius_miles,
            "families": proposal.independent_family_count,
            "categories": proposal.matched_category_count,
            "fingerprint": proposal.membership_fingerprint,
            "statement": proposal.independence_statement,
            "method": proposal.method_version,
            "fp_version": proposal.fingerprint_version,
            "evidence": json.dumps(evidence, sort_keys=True),
            "statuses": json.dumps(config.trigger_statuses),
            "min_families": config.minimum_families,
            "min_categories": config.minimum_categories,
        },
    )
    matched_by_family = dict(proposal.family_category_pairs)
    for member in proposal.members:
        session.execute(
            text(
                "INSERT INTO proposed_hub_member (proposed_hub_id,actor_id,family_root_actor_id,"
                "distance_miles,actor_category,category_type,distance_miles_raw,matched_category) "
                "VALUES (CAST(:proposal_id AS uuid),CAST(:actor_id AS uuid),CAST(:family_id AS uuid),"
                ":distance,:category,:category_type,:distance_raw,:matched_category)"
            ),
            {
                "proposal_id": proposal_id,
                "actor_id": member.actor_id,
                "family_id": member.family_id,
                "distance": round(member.distance_miles_raw, 2),
                "category": member.actor_category,
                "category_type": member.category_type,
                "distance_raw": member.distance_miles_raw,
                "matched_category": matched_by_family.get(member.family_id),
            },
        )
