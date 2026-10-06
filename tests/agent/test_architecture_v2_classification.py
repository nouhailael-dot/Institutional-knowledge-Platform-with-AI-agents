from __future__ import annotations

import re
from collections import deque
from pathlib import Path

import pytest

from agents.common.actor_classification import (
    ActorClassification,
    ActorClassificationError,
    ClassificationEvidence,
    NonActorRecord,
    classification_from_payload,
    classify_actor_category_type,
    classify_type_for_existing_category,
    load_category_catalog,
    validate_actor_classification,
)
from agents.discovery.normalize import normalize_actor_record
from scripts.run_actor_type_enrichement import main as legacy_actor_type_main
from src.enrichment.reclassify_others_actors import OtherReclassifier

ROOT = Path(__file__).resolve().parents[2]


class SequenceToolClient:
    def __init__(self, responses: list[dict[str, object]]):
        self.responses = deque(responses)
        self.calls: list[dict[str, object]] = []

    def extract_with_tool(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected classification call")
        return self.responses.popleft()


def _category(
    code: str,
    *,
    medical_school: bool = False,
    national_designation: str | None = None,
    development_stage: str | None = None,
    startup_origin: str | None = None,
    utility_ownership: str = "not_applicable",
    doubt: bool = False,
    note: str | None = None,
) -> dict[str, object]:
    return {
        "actor_category": code,
        "main_job_evidence": "The organization describes its main job explicitly.",
        "medical_school": medical_school,
        "national_designation": national_designation,
        "development_stage": development_stage,
        "startup_origin": startup_origin,
        "utility_ownership": utility_ownership,
        "doubt": doubt,
        "category_note": note,
    }


def _type(code: str, *, doubt: bool = False, note: str | None = None):
    return {"category_type": code, "doubt": doubt, "category_note": note}


def _client(category: dict[str, object], category_type: dict[str, object]):
    return SequenceToolClient(
        [{"record_kind": "actor", "evidence": "Organization self-description."}, category, category_type]
    )


def test_reference_catalog_has_exact_architecture_v2_shape():
    catalog = load_category_catalog()
    assert len(catalog.categories) == 12
    assert sum(len(category.types) for category in catalog.categories) == 65
    assert all(sum(item.code == "other" for item in category.types) == 1 for category in catalog.categories)
    assert "aggregate" not in catalog.by_code
    assert all("aggregate" not in catalog.type_codes(code) for code in catalog.by_code)


def test_legacy_direct_classification_writers_fail_loudly(tmp_path):
    with pytest.raises(RuntimeError, match="legacy actor_type enrichment is retired"):
        legacy_actor_type_main()
    with pytest.raises(RuntimeError, match="legacy direct reclassification is retired"):
        OtherReclassifier(tmp_path, session=None).run()


def test_runtime_catalog_exactly_matches_seeded_category_type_pairs():
    catalog = load_category_catalog()
    expected = {
        (category.code, category_type.code)
        for category in catalog.categories
        for category_type in category.types
    }
    sql = (ROOT / "agents/sql/190_v2_reference_data.sql").read_text(encoding="utf-8")
    seeded = set(
        re.findall(
            r"\('([a-z_]+)','([a-z_]+)','[^']*',(?:\d+)\)",
            sql.split("INSERT INTO actor_category_type_definition", 1)[1].split(
                "ON CONFLICT (category_code,type_code)", 1
            )[0],
        )
    )
    assert seeded == expected


def test_classifier_calls_kind_then_category_then_hard_rules_then_restricted_type():
    observed: list[str] = []
    client = _client(_category("research_center"), _type("independent_institute"))
    result = classify_actor_category_type(
        client,
        name="Example Institute",
        self_description="We are an independent research institute.",
        step_observer=observed.append,
    )
    assert observed == ["record_kind", "category", "hard_rules", "category_type"]
    assert [call["tool_name"] for call in client.calls] == [
        "classify_record_kind",
        "classify_actor_category",
        "classify_actor_category_type",
    ]
    type_enum = client.calls[2]["input_schema"]["properties"]["category_type"]["enum"]
    assert type_enum == [
        "independent_institute", "university_affiliated_center", "research_lab_group", "other"
    ]
    assert result.actor_category == "research_center"
    assert result.category_type == "independent_institute"


@pytest.mark.parametrize("record_kind", ["person", "event"])
def test_person_and_event_stop_before_actor_category(record_kind):
    client = SequenceToolClient(
        [{"record_kind": record_kind, "evidence": f"The page describes a {record_kind}."}]
    )
    with pytest.raises(NonActorRecord, match="not an actor category"):
        classify_actor_category_type(
            client, name="Not an actor", self_description="A time-bound or personal record."
        )
    assert len(client.calls) == 1


def test_medical_school_is_always_university_college_school():
    client = _client(
        _category("hospital_clinical", medical_school=True),
        _type("hospital"),
    )
    result = classify_actor_category_type(
        client,
        name="Example School of Medicine",
        self_description="The university's degree-granting medical school.",
    )
    assert (result.actor_category, result.category_type) == (
        "university_academic", "college_school"
    )
    allowed = client.calls[2]["input_schema"]["properties"]["category_type"]["enum"]
    assert "hospital" not in allowed


def test_national_lab_requires_designation_and_funding_alone_is_not_enough():
    client = _client(
        _category("national_laboratory", national_designation=None),
        _type("independent_institute"),
    )
    result = classify_actor_category_type(
        client,
        name="Federally Funded Research Center",
        self_description="Receives federal grants for research.",
    )
    assert result.actor_category == "research_center"
    assert result.category_needs_review is True
    assert "designation" in result.category_note.lower()


def test_designated_ffrdc_can_be_national_laboratory():
    client = _client(
        _category("national_laboratory", national_designation="Formally designated FFRDC."),
        _type("ffrdc"),
    )
    result = classify_actor_category_type(
        client,
        name="Example FFRDC",
        self_description="A formally designated federally funded research and development center.",
    )
    assert (result.actor_category, result.category_type) == ("national_laboratory", "ffrdc")


def test_formal_federal_designation_overrides_model_category():
    client = _client(
        _category(
            "research_center",
            national_designation="Federal research facility with a national mission.",
        ),
        _type("federal_research_facility"),
    )
    result = classify_actor_category_type(
        client,
        name="Federal Research Facility",
        self_description="A federal research facility with a national mission.",
    )
    assert (result.actor_category, result.category_type) == (
        "national_laboratory", "federal_research_facility"
    )


def test_startup_uses_stage_not_age_and_origin_is_the_type():
    client = _client(
        _category(
            "startup",
            development_stage="Pilot-stage commercialization is stated.",
            startup_origin="university_spinout",
        ),
        _type("university_spinout"),
    )
    result = classify_actor_category_type(
        client,
        name="Old Pilot Venture",
        self_description="A university spinout currently piloting its first commercial system.",
    )
    assert result.actor_category == "startup"
    assert result.category_type == "university_spinout"


def test_published_startup_stage_overrides_model_company_category():
    client = _client(
        _category(
            "company",
            development_stage="Pilot-stage commercialization is stated.",
            startup_origin="independent_startup",
        ),
        _type("large_multinational"),
    )
    result = classify_actor_category_type(
        client,
        name="Pilot Venture",
        self_description="An independent startup piloting its first commercial system.",
    )
    assert (result.actor_category, result.category_type) == (
        "startup", "independent_startup"
    )


def test_startup_without_stage_evidence_falls_back_to_company_review():
    client = _client(_category("startup"), _type("small_mid_size"))
    result = classify_actor_category_type(
        client,
        name="Example Incorporated",
        self_description="A commercial organization founded recently.",
    )
    assert result.actor_category == "company"
    assert result.category_needs_review is True
    assert "Development stage" in result.category_note


@pytest.mark.parametrize(
    ("designation", "stage"),
    [("UNKNOWN", "Established commercial company"), ("N/A", "not applicable"), ("none", "None.")],
)
def test_placeholder_evidence_never_triggers_hard_rules(designation, stage):
    client = _client(
        _category("company", national_designation=designation, development_stage=stage),
        _type("large_multinational"),
    )
    result = classify_actor_category_type(
        client,
        name="BASF (Regional Operations)",
        self_description="Regional operations of a multinational chemical company.",
    )
    assert (result.actor_category, result.category_type) == ("company", "large_multinational")
    assert result.evidence.national_designation is None
    assert result.evidence.development_stage is None
    assert result.category_needs_review is False


@pytest.mark.parametrize(
    ("ownership", "model_category", "model_type", "expected"),
    [
        ("public", "company", "large_multinational", ("government", "public_utility")),
        ("investor_owned", "government", "public_utility", ("company", "small_mid_size")),
    ],
)
def test_utility_ownership_hard_rule(ownership, model_category, model_type, expected):
    client = _client(
        _category(model_category, utility_ownership=ownership),
        _type(expected[1]),
    )
    result = classify_actor_category_type(
        client,
        name="Example Utility",
        self_description="The official page states its ownership structure and utility role.",
    )
    assert (result.actor_category, result.category_type) == expected


def test_cross_category_type_and_other_without_note_are_rejected():
    evidence = ClassificationEvidence(main_job="Official self-description.")
    with pytest.raises(ActorClassificationError, match="does not belong"):
        validate_actor_classification(
            ActorClassification("company", "public_utility", None, False, evidence)
        )
    with pytest.raises(ActorClassificationError, match="requires category_note"):
        validate_actor_classification(
            ActorClassification("company", "other", None, True, evidence)
        )


def test_doubt_note_must_be_one_line_and_payload_has_exactly_one_pair():
    with pytest.raises(ActorClassificationError, match="one line"):
        classification_from_payload(
            {
                "actor_category": "company",
                "category_type": "other",
                "category_note": "line one\nline two",
                "category_needs_review": True,
                "classification_evidence": {"main_job": "Official description."},
            }
        )
    result = classification_from_payload(
        {
            "actor_category": "company",
            "category_type": "other",
            "category_note": "No listed company type fits.",
            "category_needs_review": True,
            "classification_evidence": {"main_job": "Official description."},
        }
    )
    assert result is not None
    assert isinstance(result.actor_category, str)
    assert isinstance(result.category_type, str)


def test_normalization_preserves_structured_classification_evidence_and_boolean():
    normalized = normalize_actor_record(
        {
            "name": "Example",
            "actor_category": "company",
            "category_type": "small_mid_size",
            "category_needs_review": False,
            "classification_evidence": {
                "main_job": "  Makes equipment.  ",
                "utility_ownership": "not_applicable",
            },
        }
    )
    assert normalized["category_needs_review"] is False
    assert normalized["classification_evidence"] == {
        "main_job": "Makes equipment.",
        "utility_ownership": "not_applicable",
    }


def test_classifier_prompt_forbids_sector_funder_fame_age_and_unsupported_inference():
    client = _client(_category("company"), _type("small_mid_size"))
    classify_actor_category_type(
        client,
        name="Example",
        self_description="We manufacture equipment.",
    )
    category_prompt = client.calls[1]["system"]
    assert all(word in category_prompt for word in ("sector", "funder", "fame", "age"))
    assert "official self-description" in category_prompt


def test_existing_actor_enrichment_keeps_migrated_category_fixed():
    client = SequenceToolClient([
        {
            "category_type": "corporate_rd_center",
            "doubt": False,
            "category_note": None,
        }
    ])
    result = classify_type_for_existing_category(
        client,
        name="Existing GHUS Company",
        self_description="The company operates a corporate research and development center.",
        actor_category="company",
    )
    assert result.actor_category == "company"
    assert result.category_type == "corporate_rd_center"
    assert [call["tool_name"] for call in client.calls] == [
        "classify_existing_actor_category_type"
    ]
    allowed = client.calls[0]["input_schema"]["properties"]["category_type"]["enum"]
    assert "corporate_rd_center" in allowed
    assert "public_utility" not in allowed
    assert "reclassify" in client.calls[0]["system"]


def test_existing_actor_other_type_requires_honest_note():
    client = SequenceToolClient([
        {"category_type": "other", "doubt": False, "category_note": None}
    ])
    with pytest.raises(ActorClassificationError, match="requires category_note"):
        classify_type_for_existing_category(
            client,
            name="Existing GHUS Company",
            self_description="The official description does not fit a defined company type.",
            actor_category="company",
        )


def test_deferred_schema_enforces_pair_completeness_other_note_and_category_doubt():
    cutover = (ROOT / "migrations/proposed/deferred/380_v2_actor_classification_cutover.sql").read_text()
    review = (ROOT / "migrations/proposed/deferred/370_v2_category_doubt_review_kind.sql").read_text()
    assert "FOREIGN KEY (actor_category, category_type)" in cutover
    assert "ck_actor_category_complete" in cutover
    assert "ck_actor_other_type_note" in cutover
    assert "category_doubt" in review
    assert "review_kind = 'classification'" in review
    assert "payload->>'issue' = 'category_doubt'" in review


def test_validated_additive_package_is_not_part_of_phase5_manifest_entry():
    source = (ROOT / "migrations/proposed/manifest.json").read_text()
    assert '"id": "019"' in source
    assert "agents/sql/370_v2_actor_classification.sql" in source
    assert "additive_apply_2026-09-28" not in source
