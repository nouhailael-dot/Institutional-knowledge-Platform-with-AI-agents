"""Static contracts for the corrected Phase 12 migration policy."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFERRED = ROOT / "migrations/proposed/deferred"


def test_corrected_manifest_supersedes_old_required_type_cutover():
    manifest = json.loads(
        (ROOT / "migrations/proposed/functional_v2_isolated_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["checkpoints"]["phase12_policy_backfill"]["steps"][0]["id"] == "480"
    assert manifest["checkpoints"]["phase12_policy_validate"]["steps"][0]["id"] == "490"
    assert manifest["checkpoints"]["category_resolution_contract"]["steps"][0]["id"] == "495"
    assert manifest["checkpoints"]["final_cutover"]["steps"][0]["id"] == "500"
    assert {item["id"] for item in manifest["superseded_policy_proposals"]} == {
        "450",
        "460",
    }


def test_category_type_is_nullable_but_non_null_pairs_are_enforced():
    validate = (DEFERRED / "490_v2_phase12_policy_validate.sql").read_text(
        encoding="utf-8"
    )
    cutover = (DEFERRED / "500_v2_final_contract_cutover.sql").read_text(
        encoding="utf-8"
    )
    assert "FOREIGN KEY(actor_category,category_type)" in validate
    assert "category_type IS NULL OR category_type <> 'other'" in validate
    assert "category_type SET NOT NULL" not in validate
    assert "category_type SET NOT NULL" not in cutover


def test_category_completeness_waits_for_review_resolution():
    validate = (DEFERRED / "490_v2_phase12_policy_validate.sql").read_text(
        encoding="utf-8"
    )
    complete = (DEFERRED / "495_v2_actor_category_complete.sql").read_text(
        encoding="utf-8"
    )
    assert "ADD CONSTRAINT ck_actor_category_complete" not in validate
    assert "VALIDATE CONSTRAINT ck_actor_category_complete" in complete


def test_cutover_fails_closed_on_data_loss_audit():
    cutover = (DEFERRED / "500_v2_final_contract_cutover.sql").read_text(
        encoding="utf-8"
    )
    assert "pre_cutover_data_loss_audit" in cutover
    assert "RAISE EXCEPTION" in cutover
    assert cutover.index("pre_cutover_data_loss_audit") < cutover.index("DROP TABLE")


def test_mapping_matrix_covers_every_base_table_column_from_report_copy():
    matrix = json.loads(
        (ROOT / "docs/evidence/legacy_to_v2_mapping_matrix_2026-10-06.json").read_text(
            encoding="utf-8"
        )
    )
    assert matrix["table_count"] == 66
    assert matrix["column_count"] == 723
    assert len(matrix["mapping_rows"]) == 723
    assert all(row["transformation_rule"] for row in matrix["mapping_rows"])
    assert all(row["provenance_treatment"] for row in matrix["mapping_rows"])


def test_loss_audit_is_present_and_still_blocks_cutover():
    audit = json.loads(
        (ROOT / "docs/evidence/pre_cutover_data_loss_audit_2026-10-06.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["audit_name"] == "pre_cutover_data_loss_audit"
    assert audit["passed"] is False
    assert audit["cutover_attestation_written"] is False
