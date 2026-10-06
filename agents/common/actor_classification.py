"""Architecture V2 actor category/type classification.

Model calls occur here during extraction, never during deterministic routing or
canonical promotion. Promotion accepts only the validated scalar result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "actor_categories.yaml"
RECORD_KINDS = ("actor", "person", "event")
CATEGORY_DOUBT_BRIDGE_KIND = "classification"
CATEGORY_DOUBT_ISSUE = "category_doubt"


class ActorClassificationError(ValueError):
    """A classification is incomplete or violates Architecture V2."""


class NonActorRecord(ActorClassificationError):
    def __init__(self, record_kind: str, evidence: str):
        super().__init__(f"{record_kind} is not an actor category")
        self.record_kind = record_kind
        self.evidence = evidence


@dataclass(frozen=True)
class CategoryType:
    code: str
    label: str


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    definition: str
    types: tuple[CategoryType, ...]


@dataclass(frozen=True)
class CategoryCatalog:
    categories: tuple[Category, ...]

    @property
    def by_code(self) -> dict[str, Category]:
        return {category.code: category for category in self.categories}

    def type_codes(self, category_code: str) -> tuple[str, ...]:
        try:
            category = self.by_code[category_code]
        except KeyError as exc:
            raise ActorClassificationError(f"unknown actor category {category_code!r}") from exc
        return tuple(item.code for item in category.types)

    def validates(self, category_code: str, type_code: str) -> bool:
        return type_code in self.type_codes(category_code)


@dataclass(frozen=True)
class ClassificationEvidence:
    main_job: str
    medical_school: bool = False
    national_designation: str | None = None
    development_stage: str | None = None
    startup_origin: str | None = None
    utility_ownership: str = "not_applicable"


@dataclass(frozen=True)
class ActorClassification:
    actor_category: str
    category_type: str
    category_note: str | None
    category_needs_review: bool
    evidence: ClassificationEvidence

    def as_payload(self) -> dict[str, object]:
        return {
            "actor_category": self.actor_category,
            "category_type": self.category_type,
            "category_note": self.category_note,
            "category_needs_review": self.category_needs_review,
            "classification_evidence": {
                "main_job": self.evidence.main_job,
                "medical_school": self.evidence.medical_school,
                "national_designation": self.evidence.national_designation,
                "development_stage": self.evidence.development_stage,
                "startup_origin": self.evidence.startup_origin,
                "utility_ownership": self.evidence.utility_ownership,
            },
        }


def load_category_catalog(path: Path = CATALOG_PATH) -> CategoryCatalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    categories = []
    seen_codes: set[str] = set()
    for entry in raw.get("categories", []):
        code = _single_line(entry.get("code"), "category code")
        if code in seen_codes:
            raise ActorClassificationError(f"duplicate actor category {code!r}")
        seen_codes.add(code)
        types = tuple(
            CategoryType(
                code=_single_line(item[0], "type code"),
                label=_single_line(item[1], "type label"),
            )
            for item in entry.get("types", [])
        )
        if len({item.code for item in types}) != len(types):
            raise ActorClassificationError(f"duplicate type in category {code!r}")
        if sum(item.code == "other" for item in types) != 1:
            raise ActorClassificationError(f"category {code!r} must have exactly one other type")
        categories.append(
            Category(
                code=code,
                label=_single_line(entry.get("label"), "category label"),
                definition=_single_line(entry.get("definition"), "category definition"),
                types=types,
            )
        )
    if len(categories) != 12:
        raise ActorClassificationError(f"expected 12 actor categories, got {len(categories)}")
    catalog = CategoryCatalog(tuple(categories))
    if sum(len(category.types) for category in catalog.categories) != 65:
        raise ActorClassificationError("Architecture V2 requires exactly 65 category types")
    return catalog


def classify_actor_category_type(
    llm_client,
    *,
    name: str,
    self_description: str,
    catalog: CategoryCatalog | None = None,
    max_tokens: int = 700,
    step_observer: Callable[[str], None] | None = None,
) -> ActorClassification:
    """Run the required kind -> category -> hard rules -> type sequence."""

    catalog = catalog or load_category_catalog()
    observe = step_observer or (lambda _step: None)
    subject = {
        "organization_name": _single_line(name, "organization name"),
        "official_self_description": str(self_description or "").strip(),
    }

    observe("record_kind")
    kind = llm_client.extract_with_tool(
        system=(
            "Decide whether the subject is an organization actor, a person, or a time-bound "
            "event. Use only the supplied name and official self-description."
        ),
        user=str(subject),
        tool_name="classify_record_kind",
        tool_description="Classify record kind before any actor category is considered.",
        input_schema=_record_kind_schema(),
        max_tokens=max_tokens,
    )
    record_kind = str((kind or {}).get("record_kind") or "").strip()
    if record_kind not in RECORD_KINDS:
        raise ActorClassificationError(f"invalid record kind {record_kind!r}")
    if record_kind != "actor":
        raise NonActorRecord(record_kind, str((kind or {}).get("evidence") or ""))

    observe("category")
    category_raw = llm_client.extract_with_tool(
        system=(
            "Choose what the organization IS from the supplied Architecture V2 categories. "
            "Use its main job and official self-description only. Never use sector, funder, "
            "fame, organization age, or how GHUS might use it. Return evidence from the "
            "self-description. Do not choose a category type yet."
        ),
        user=str({**subject, "categories": [
            {"code": item.code, "definition": item.definition} for item in catalog.categories
        ]}),
        tool_name="classify_actor_category",
        tool_description="Choose one actor category and evidence before category type.",
        input_schema=_category_schema(tuple(c.code for c in catalog.categories)),
        max_tokens=max_tokens,
    ) or {}
    category_code = str(category_raw.get("actor_category") or "").strip()
    if category_code not in catalog.by_code:
        raise ActorClassificationError(f"invalid actor category {category_code!r}")
    evidence = ClassificationEvidence(
        main_job=_single_line(category_raw.get("main_job_evidence"), "main-job evidence"),
        medical_school=bool(category_raw.get("medical_school", False)),
        national_designation=_evidence_line(category_raw.get("national_designation")),
        development_stage=_evidence_line(category_raw.get("development_stage")),
        startup_origin=_evidence_line(category_raw.get("startup_origin")),
        utility_ownership=str(category_raw.get("utility_ownership") or "not_applicable").strip(),
    )
    note = _optional_line(category_raw.get("category_note"))
    doubt = bool(category_raw.get("doubt", False))

    observe("hard_rules")
    category_code, forced_type, rule_note, rule_doubt = _apply_hard_rules(
        category_code, evidence
    )
    note = _join_notes(note, rule_note)
    doubt = doubt or rule_doubt

    observe("category_type")
    allowed_types = catalog.type_codes(category_code)
    type_raw = llm_client.extract_with_tool(
        system=(
            "Choose exactly one category type from the supplied list. The actor category is "
            "already fixed. Do not choose a type from another category. Use only the official "
            "self-description and supplied evidence. If none fits, choose other and explain why."
        ),
        user=str({
            **subject,
            "actor_category": category_code,
            "main_job_evidence": evidence.main_job,
            "allowed_types": list(allowed_types),
        }),
        tool_name="classify_actor_category_type",
        tool_description="Choose one type restricted to the already-selected category.",
        input_schema=_type_schema(allowed_types),
        max_tokens=max_tokens,
    ) or {}
    type_code = forced_type or str(type_raw.get("category_type") or "").strip()
    type_note = _optional_line(type_raw.get("category_note"))
    note = _join_notes(note, type_note)
    doubt = doubt or bool(type_raw.get("doubt", False)) or type_code == "other"
    return validate_actor_classification(
        ActorClassification(category_code, type_code, note, doubt, evidence), catalog=catalog
    )


def classify_type_for_existing_category(
    llm_client,
    *,
    name: str,
    self_description: str,
    actor_category: str,
    catalog: CategoryCatalog | None = None,
    max_tokens: int = 500,
) -> ActorClassification:
    """Enrich only the type of an already-migrated canonical actor.

    Phase 12 treats the deterministically migrated category as authoritative.
    This path therefore never asks the model to choose or casually change that
    category. A genuine category concern must use the separate reclassification
    review path.
    """

    catalog = catalog or load_category_catalog()
    category = _single_line(actor_category, "actor category")
    allowed_types = catalog.type_codes(category)
    subject = {
        "organization_name": _single_line(name, "organization name"),
        "official_self_description": str(self_description or "").strip(),
        "actor_category": category,
        "allowed_types": list(allowed_types),
    }
    raw = llm_client.extract_with_tool(
        system=(
            "The actor category was migrated from the canonical GHUS database and is fixed. "
            "Choose exactly one category type from the supplied category-specific list using "
            "only authoritative or official self-description evidence. Do not reclassify the "
            "actor category. Do not use sector, funder, fame, organization age, or unsupported "
            "inference. If no defined type fits, choose other and give a one-line note."
        ),
        user=str(subject),
        tool_name="classify_existing_actor_category_type",
        tool_description="Enrich one type without changing the migrated actor category.",
        input_schema=_type_schema(allowed_types),
        max_tokens=max_tokens,
    ) or {}
    category_type = str(raw.get("category_type") or "").strip()
    note = _optional_line(raw.get("category_note"))
    doubt = bool(raw.get("doubt", False)) or category_type == "other"
    return validate_actor_classification(
        ActorClassification(
            actor_category=category,
            category_type=category_type,
            category_note=note,
            category_needs_review=doubt,
            evidence=ClassificationEvidence(
                main_job=_single_line(
                    raw.get("main_job_evidence")
                    or self_description,
                    "main-job evidence",
                )
            ),
        ),
        catalog=catalog,
    )


def classification_from_payload(
    payload: Mapping[str, object], *, catalog: CategoryCatalog | None = None
) -> ActorClassification | None:
    """Validate extracted classification; return None only for legacy bridge inputs."""

    category = str(payload.get("actor_category") or "").strip()
    category_type = str(payload.get("category_type") or "").strip()
    if not category and not category_type:
        return None
    raw_evidence = payload.get("classification_evidence")
    evidence_map = raw_evidence if isinstance(raw_evidence, Mapping) else {}
    evidence = ClassificationEvidence(
        main_job=_single_line(evidence_map.get("main_job"), "main-job evidence"),
        medical_school=bool(evidence_map.get("medical_school", False)),
        national_designation=_optional_line(evidence_map.get("national_designation")),
        development_stage=_optional_line(evidence_map.get("development_stage")),
        startup_origin=_optional_line(evidence_map.get("startup_origin")),
        utility_ownership=str(evidence_map.get("utility_ownership") or "not_applicable").strip(),
    )
    result = ActorClassification(
        actor_category=category,
        category_type=category_type,
        category_note=_optional_line(payload.get("category_note")),
        category_needs_review=bool(payload.get("category_needs_review", False)),
        evidence=evidence,
    )
    result = _validate_hard_rule_result(result)
    return validate_actor_classification(result, catalog=catalog)


def validate_actor_classification(
    result: ActorClassification, *, catalog: CategoryCatalog | None = None
) -> ActorClassification:
    catalog = catalog or load_category_catalog()
    category = _single_line(result.actor_category, "actor category")
    category_type = _single_line(result.category_type, "category type")
    if not catalog.validates(category, category_type):
        raise ActorClassificationError(
            f"category type {category_type!r} does not belong to {category!r}"
        )
    note = _optional_line(result.category_note)
    if (category_type == "other" or result.category_needs_review) and not note:
        raise ActorClassificationError("other or doubtful classification requires category_note")
    if not _single_line(result.evidence.main_job, "main-job evidence"):
        raise ActorClassificationError("main-job evidence is required")
    return replace(result, actor_category=category, category_type=category_type, category_note=note)


def _validate_hard_rule_result(result: ActorClassification) -> ActorClassification:
    evidence = result.evidence
    if evidence.medical_school and (
        result.actor_category != "university_academic" or result.category_type != "college_school"
    ):
        raise ActorClassificationError("medical schools must be university_academic/college_school")
    if result.actor_category == "national_laboratory" and not evidence.national_designation:
        raise ActorClassificationError("national laboratory requires formal designation evidence")
    if evidence.national_designation and result.actor_category != "national_laboratory":
        raise ActorClassificationError(
            "formal national-laboratory or federal-facility designation requires "
            "national_laboratory"
        )
    if result.actor_category == "startup" and not evidence.development_stage:
        raise ActorClassificationError("startup requires development-stage evidence")
    if evidence.development_stage and result.actor_category != "startup":
        raise ActorClassificationError(
            "published organization development-stage evidence requires startup"
        )
    if result.actor_category == "startup":
        allowed_origins = {"university_spinout", "corporate_spinout", "independent_startup"}
        if evidence.startup_origin not in allowed_origins and result.category_type != "other":
            raise ActorClassificationError(
                "startup origin evidence is required for a specific startup type"
            )
        if evidence.startup_origin in allowed_origins and (
            result.category_type != evidence.startup_origin
        ):
            raise ActorClassificationError("startup origin evidence must determine category type")
    if evidence.utility_ownership == "public" and (
        result.actor_category != "government" or result.category_type != "public_utility"
    ):
        raise ActorClassificationError("public utilities must be government/public_utility")
    if evidence.utility_ownership == "investor_owned" and result.actor_category != "company":
        raise ActorClassificationError("investor-owned utilities must be company actors")
    return result


def _apply_hard_rules(
    category_code: str, evidence: ClassificationEvidence
) -> tuple[str, str | None, str | None, bool]:
    if evidence.medical_school:
        return "university_academic", "college_school", None, False
    if evidence.national_designation:
        return "national_laboratory", None, None, False
    if category_code == "national_laboratory" and not evidence.national_designation:
        return (
            "research_center",
            None,
            "National-laboratory designation was not evidenced; closest category used.",
            True,
        )
    if category_code == "startup" and not evidence.development_stage:
        return (
            "company",
            None,
            "Development stage was not evidenced; company used pending review.",
            True,
        )
    if category_code == "startup" or evidence.development_stage:
        allowed_origins = {"university_spinout", "corporate_spinout", "independent_startup"}
        if evidence.startup_origin in allowed_origins:
            return "startup", evidence.startup_origin, None, False
        return (
            "startup",
            "other",
            "Startup origin was not evidenced; other used pending review.",
            True,
        )
    if evidence.utility_ownership == "public":
        return "government", "public_utility", None, False
    if evidence.utility_ownership == "investor_owned":
        return "company", None, None, False
    if evidence.utility_ownership not in {"not_applicable", "unknown", "public", "investor_owned"}:
        raise ActorClassificationError("invalid utility ownership evidence")
    return category_code, None, None, False


def _record_kind_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "record_kind": {"type": "string", "enum": list(RECORD_KINDS)},
            "evidence": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["record_kind", "evidence"],
    }


def _category_schema(category_codes: tuple[str, ...]) -> dict[str, object]:
    nullable = {"type": ["string", "null"], "maxLength": 500}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "actor_category": {"type": "string", "enum": list(category_codes)},
            "main_job_evidence": {"type": "string", "minLength": 1, "maxLength": 500},
            "medical_school": {"type": "boolean"},
            "national_designation": {
                **nullable,
                "description": (
                    "The formal national-laboratory, FFRDC or federal-facility designation "
                    "quoted from the evidence. null when none is stated."
                ),
            },
            "development_stage": {
                **nullable,
                "description": (
                    "The published early development stage (for example seed or Series A) "
                    "of a startup. null for established organizations or when not stated."
                ),
            },
            "startup_origin": {
                "type": ["string", "null"],
                "enum": ["university_spinout", "corporate_spinout", "independent_startup", None],
                "description": "Startup origin when the evidence states it; otherwise null.",
            },
            "utility_ownership": {
                "type": "string",
                "enum": ["not_applicable", "unknown", "public", "investor_owned"],
            },
            "doubt": {"type": "boolean"},
            "category_note": nullable,
        },
        "required": [
            "actor_category", "main_job_evidence", "medical_school",
            "national_designation", "development_stage", "startup_origin",
            "utility_ownership", "doubt", "category_note",
        ],
    }


def _type_schema(type_codes: tuple[str, ...]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "category_type": {"type": "string", "enum": list(type_codes)},
            "doubt": {"type": "boolean"},
            "category_note": {"type": ["string", "null"], "maxLength": 500},
        },
        "required": ["category_type", "doubt", "category_note"],
    }


def _single_line(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ActorClassificationError(f"{label} is required")
    if "\n" in text or "\r" in text:
        raise ActorClassificationError(f"{label} must be one line")
    return text


# Placeholder answers a model gives for "not applicable" evidence fields. They
# are not evidence and must never trigger a hard rule.
_NON_EVIDENCE = frozenset({
    "unknown", "none", "null", "n/a", "na", "not applicable", "not_applicable",
    "not stated", "not evidenced", "not specified", "not available", "no", "false",
    "established", "established company", "established organization",
    "established commercial company", "mature", "not a startup",
})


def _evidence_line(value: object) -> str | None:
    text = _optional_line(value)
    if text is None or text.casefold().strip(" .") in _NON_EVIDENCE:
        return None
    return text


def _optional_line(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _single_line(value, "category note/evidence")


def _join_notes(*values: str | None) -> str | None:
    items = [value for value in values if value]
    return " ".join(dict.fromkeys(items)) or None
