"""Fill blank actor.funding_summary values without using paid APIs.

The script is intentionally conservative:
- Only blank funding_summary cells are filled by default.
- Existing specific funding text is never overwritten unless --refresh is used.
- It avoids invented grant names, award numbers, or dollar amounts.
- Aggregate/representative rows get an explicit "varies/not verified" summary.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import func, or_, select, text

PROJECT_ROOT = Path(r"C:\Users\Ismail\Projects\GHUS-Platform")
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


KEYWORDS = {
    "ai": (
        " ai ",
        "artificial intelligence",
        "machine learning",
        "robotics",
        "data science",
        "analytics",
        "autonomous",
        "cloud",
        "software",
        "digital",
        "computing",
    ),
    "health": (
        "health",
        "medical",
        "medicine",
        "clinical",
        "hospital",
        "biomedical",
        "cancer",
        "pharma",
        "therapeutic",
        "diagnostic",
        "patient",
    ),
    "agriculture": (
        "agri",
        "crop",
        "farm",
        "fertilizer",
        "plant science",
        "soil",
        "dairy",
        "livestock",
        "food",
        "horticulture",
        "extension",
    ),
    "water": (
        "water",
        "desalination",
        "groundwater",
        "aquifer",
        "irrigation",
        "hydrology",
        "wastewater",
        "watershed",
    ),
    "materials": (
        "chemistry",
        "chemical",
        "catalysis",
        "polymer",
        "materials",
        "manufacturing",
        "reaction engineering",
        "semiconductor",
    ),
    "mining": (
        "mining",
        "mine",
        "mineral",
        "critical mineral",
        "lithium",
        "copper",
        "zinc",
        "smelting",
        "metallurgy",
        "geology",
        "ore",
    ),
    "energy": (
        "energy",
        "hydrogen",
        "battery",
        "storage",
        "solar",
        "wind",
        "grid",
        "ammonia",
        "lng",
        "power",
        "renewable",
    ),
    "climate": (
        "carbon",
        "climate",
        "sustainability",
        "green",
        "decarbonization",
        "ccus",
        "co2",
        "resilience",
        "environment",
    ),
    "finance": (
        "venture",
        "capital",
        "fund",
        "investment",
        "finance",
        "bond",
        "accelerator",
        "incubator",
    ),
    "policy": (
        "agency",
        "commission",
        "office",
        "programme",
        "program",
        "united nations",
        "unesco",
        "unicef",
        "fao",
        "regulatory",
        "standards",
        "governance",
    ),
}


DOMAIN_GRANTS = {
    "ai": "research grants, sponsored research, cloud/compute partnerships, and industry or government contracts",
    "health": "NIH-style biomedical grants, clinical-trial sponsors, hospital or university support, and industry collaborations",
    "agriculture": "USDA/state agriculture programs, land-grant or extension budgets, research grants, commodity/grower support, and industry collaborations",
    "water": "public water programs, state/federal grants, utility or agency budgets, sponsored research, and infrastructure funding",
    "materials": "NSF/DOE-style research grants, sponsored research, industry partnerships, user-facility support, and university budgets",
    "mining": "industry sponsorship, public research grants, state or federal resource programs, project budgets, and operator partnerships",
    "energy": "DOE/state clean-energy programs, sponsored research, project finance, utility or corporate budgets, and industry partnerships",
    "climate": "climate and environmental grants, public programs, philanthropy, sponsored research, and implementation partnerships",
    "finance": "limited-partner commitments, sponsor support, management fees, investment returns, and portfolio-related capital",
    "policy": "public appropriations, member-state or donor contributions, grants, program budgets, and implementation partnerships",
    "general": "institutional budgets, grants, contracts, philanthropy, program revenue, and partner contributions",
}


GENERIC_NAME_TERMS = (
    "companies",
    "startups",
    "labs",
    "programs",
    "initiatives",
    "centers",
    "firms",
    "operators",
    "plants",
    "facilities",
    "projects",
    "anchors",
    "partners",
    "institutes",
    "agencies",
    "bodies",
    "manufacturers",
    "funds",
    "platforms",
    "offices",
    "authorities",
    "providers",
    "complexes",
    "producers",
)


def blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def norm(value: object) -> str:
    return (str(value) if value is not None else "").lower()


def classify_domain(actor: Actor) -> str:
    text_value = " ".join(
        [
            actor.name or "",
            actor.actor_type or "",
            actor.description or "",
            actor.website or "",
            actor.primary_technical_focus or "",
            actor.technical_approach or "",
            actor.current_activities or "",
        ]
    ).lower()

    scores: Counter[str] = Counter()
    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_value:
                scores[category] += 1

    return scores.most_common(1)[0][0] if scores else "general"


def is_representative(actor: Actor) -> bool:
    name = norm(actor.name)
    description = norm(actor.description)
    if "parent un body" in description or "synthetic, generated from" in description:
        return True
    generic_name = any(name.endswith(term) or f" {term} " in name for term in GENERIC_NAME_TERMS)
    if "aggregate actor label" in description or "category or group of related organizations" in description:
        return generic_name
    return generic_name


GENERATED_PREFIXES = (
    "Representative or aggregate actor row;",
    "Public-company funding profile:",
    "Private investment funding profile:",
    "Startup-support funding profile:",
    "Startup funding profile:",
    "Operator funding profile:",
    "Corporate/operator funding profile:",
    "Academic funding profile:",
    "National-lab funding profile:",
    "Health and biomedical funding profile:",
    "Public-sector funding profile:",
    "Multilateral finance profile:",
    "UN/intergovernmental funding profile:",
    "Association/consortium funding profile:",
    "Research-organization funding profile:",
    "General funding profile:",
)


def generated_by_this_script(value: object) -> bool:
    text_value = str(value or "").strip()
    return any(text_value.startswith(prefix) for prefix in GENERATED_PREFIXES)


def is_public_company(actor: Actor) -> bool:
    description = norm(actor.description)
    text_value = " ".join([actor.name or "", actor.description or ""]).lower()
    return (
        "sec registrant" in description
        or "publicly traded" in description
        or "ticker" in description
        or "nasdaq" in text_value
        or "nyse" in text_value
    )


def is_national_lab_like(actor: Actor) -> bool:
    name = norm(actor.name)
    description = norm(actor.description)
    markers = (
        "national laboratory",
        "national renewable energy laboratory",
        "argonne",
        "lawrence livermore",
        "oak ridge",
        "brookhaven",
        "pacific northwest national laboratory",
        "sandia",
        "nrel",
        "nersc",
        "molecular foundry",
        "advanced light source",
        "advanced photon source",
        "jet propulsion laboratory",
        "jpl",
        "applied physics laboratory",
        "federally funded research",
    )
    return any(marker in name or marker in description for marker in markers)


def is_health_like(actor: Actor) -> bool:
    name = norm(actor.name)
    actor_type = norm(actor.actor_type)
    markers = (
        "hospital",
        "clinic",
        "health system",
        "health + hospitals",
        "medicine",
        "medical center",
        "school of medicine",
        "cancer center",
        "children's",
        "childrens",
        "biomedical advanced research",
        "nih intramural",
        "clinical center",
    )
    return actor_type in {"health_system"} or any(marker in name for marker in markers)


def is_public_sector_like(actor: Actor) -> bool:
    name = norm(actor.name)
    actor_type = norm(actor.actor_type)
    if actor_type in {"federal_agency", "state_agency", "government_agency"}:
        return True
    markers = (
        "department of",
        "commission",
        "agency",
        "office of",
        "office for",
        "water board",
        "public works",
        "fda",
        "epa",
        "noaa",
        "nist",
        "ercot",
        "caiso",
        "water resources control board",
    )
    return any(marker in name for marker in markers)


def is_un_like(actor: Actor) -> bool:
    name = norm(actor.name)
    actor_type = norm(actor.actor_type)
    if actor_type in {"un_agency", "un_programme", "un_committee", "un_secretariat", "intergovernmental_organization"}:
        return True
    markers = (
        "united nations",
        "unesco",
        "unicef",
        "unep",
        "unido",
        "un women",
        "world bank",
        "international finance corporation",
        "international development association",
        "international bank for reconstruction",
        "international fund for agricultural development",
    )
    return any(marker in name for marker in markers)


def is_world_bank_like(actor: Actor) -> bool:
    name = norm(actor.name)
    markers = (
        "world bank",
        "international finance corporation",
        "international development association",
        "international bank for reconstruction",
    )
    return any(marker in name for marker in markers)


def funding_summary(actor: Actor) -> str:
    actor_type = norm(actor.actor_type)
    name = norm(actor.name)
    domain = classify_domain(actor)
    domain_sources = DOMAIN_GRANTS[domain]

    if is_representative(actor):
        return (
            "Representative or aggregate actor row; funding varies by the underlying organizations. "
            "No single verified funding source or award amount is assigned to this row in the current structured data."
        )

    if is_public_company(actor):
        return (
            "Public-company funding profile: R&D and deployment are primarily financed through corporate operating budgets, "
            "revenue, capital markets, and strategic partnerships. No GHUS-specific award amount is verified in the current structured data."
        )

    if actor_type in {"venture_capital"} or any(word in name for word in ("venture", "capital", "fund")):
        return (
            "Private investment funding profile: activity is financed through limited-partner capital commitments, management fees, "
            "carried interest economics, sponsor support where applicable, and portfolio investment returns. No GHUS-specific award amount is verified."
        )

    if actor_type in {"accelerator"} or any(word in name for word in ("accelerator", "incubator", "labcentral", "skydeck", "j labs", "jlabs")):
        return (
            "Startup-support funding profile: likely supported by sponsor funding, institutional backing, corporate or philanthropic partners, "
            "tenant or program fees, and affiliated investment vehicles where applicable. Specific award amounts are not verified in the current structured data."
        )

    if actor_type in {"startup"}:
        return (
            "Startup funding profile: likely financed through venture or strategic investment, grants, customer revenue, partnerships, "
            "and project-specific financing as the company scales. Specific rounds or award amounts are not verified in the current structured data."
        )

    if actor_type in {"company", "corporate_rd_lab", "industrial_partner", "project_developer"}:
        if any(word in name for word in ("utility", "water system", "public works", "port ", "port houston")):
            return (
                "Operator funding profile: activities are supported through operating revenue, public or regulated budgets, bonds or capital plans, "
                "customer fees, grants, and project finance where applicable. No GHUS-specific award amount is verified."
            )
        return (
            "Corporate/operator funding profile: R&D, pilots, and deployment are primarily financed through corporate budgets, revenue, "
            "customer contracts, project finance, and strategic partnerships. No GHUS-specific award amount is verified in the current structured data."
        )

    if is_national_lab_like(actor):
        return (
            "National-lab funding profile: supported mainly through federal mission budgets, DOE/agency program funding, user-facility support, "
            "sponsored projects, CRADA-style collaborations, and industry partnerships. No GHUS-specific award amount is verified."
        )

    if is_health_like(actor):
        return (
            "Health and biomedical funding profile: supported through hospital or parent-institution budgets, NIH-style grants, clinical-trial sponsors, "
            "philanthropy, reimbursement-linked operations where applicable, and industry collaborations. No GHUS-specific award amount is verified."
        )

    if is_public_sector_like(actor):
        return (
            "Public-sector funding profile: supported through public appropriations, federal or state program budgets, grants, fees, "
            "bond/capital funding where relevant, and interagency implementation funds. No GHUS-specific award amount is verified."
        )

    if is_world_bank_like(actor):
        return (
            "Multilateral finance profile: supported through member-country capital, donor replenishments or trust funds, borrowings, "
            "repayments, fees, and project-specific financing. No GHUS-specific award amount is verified."
        )

    if is_un_like(actor):
        return (
            "UN/intergovernmental funding profile: supported through assessed or voluntary member-state contributions, donor grants, "
            "trust funds, program budgets, and project-specific partnerships. No GHUS-specific award amount is verified."
        )

    if actor_type in {"university", "university_lab"}:
        return (
            f"Academic funding profile: supported through parent-institution budgets, {domain_sources}, philanthropy, "
            "technology-transfer income where applicable, and sponsored projects. No specific award amount is verified in the current structured data."
        )

    if actor_type in {"national_research_lab", "national_research_center", "federal_research_system"}:
        return (
            "National-lab funding profile: supported mainly through federal mission budgets, DOE/agency program funding, user-facility support, "
            "sponsored projects, CRADA-style collaborations, and industry partnerships. No GHUS-specific award amount is verified."
        )

    if actor_type in {"un_agency", "un_programme", "un_committee", "un_secretariat", "intergovernmental_organization"}:
        if is_world_bank_like(actor):
            return (
                "Multilateral finance profile: supported through member-country capital, donor replenishments or trust funds, borrowings, "
                "repayments, fees, and project-specific financing. No GHUS-specific award amount is verified."
            )
        return (
            "UN/intergovernmental funding profile: supported through assessed or voluntary member-state contributions, donor grants, "
            "trust funds, program budgets, and project-specific partnerships. No GHUS-specific award amount is verified."
        )

    if actor_type in {"industry_association", "consortium", "nonprofit"}:
        return (
            "Association/consortium funding profile: likely supported through membership dues, sponsor contributions, grants, philanthropy, "
            "public programs, and project-specific partner funding. No single verified award amount is assigned in the current structured data."
        )

    if actor_type in {"research_organization"}:
        return (
            f"Research-organization funding profile: likely supported through {domain_sources}, contracts, philanthropy, "
            "institutional support, and partner projects. No specific award amount is verified in the current structured data."
        )

    return (
        f"General funding profile: likely supported through {domain_sources}. "
        "No actor-specific funding source or award amount is verified in the current structured data."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Overwrite nonblank funding_summary values too.")
    parser.add_argument(
        "--refresh-generated-only",
        action="store_true",
        help="Refresh only values previously generated by this script.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max rows to update.")
    args = parser.parse_args()

    with SessionLocal() as session:
        session.execute(text("SET LOCAL statement_timeout = '120s'"))
        blank_filter = or_(Actor.funding_summary.is_(None), func.trim(Actor.funding_summary) == "")
        before_blank = session.scalar(select(func.count()).select_from(Actor).where(blank_filter))
        total = session.scalar(select(func.count()).select_from(Actor))

        query = select(Actor).order_by(Actor.name)
        if args.refresh_generated_only:
            pass
        elif not args.refresh:
            query = query.where(blank_filter)
        actors = list(session.scalars(query))
        if args.limit:
            actors = actors[: args.limit]

        updated = []
        by_type: Counter[str] = Counter()
        for actor in actors:
            if args.refresh_generated_only and not generated_by_this_script(actor.funding_summary):
                continue
            if not args.refresh and not args.refresh_generated_only and not blank(actor.funding_summary):
                continue
            actor.funding_summary = funding_summary(actor)
            updated.append(actor.name)
            by_type[actor.actor_type or "unknown"] += 1

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        after_blank = session.scalar(select(func.count()).select_from(Actor).where(blank_filter))

    print(f"dry_run={args.dry_run}")
    print(f"refresh={args.refresh}")
    print(f"refresh_generated_only={args.refresh_generated_only}")
    print(f"total_actors={total}")
    print(f"blank_before={before_blank}")
    print(f"planned_updates={len(updated)}")
    print(f"blank_after={after_blank}")
    print("updated_by_type")
    for actor_type, count in by_type.most_common():
        print(f"TYPE|{actor_type}|{count}")
    for name in updated[:120]:
        print(f"UPDATED|{name}")


if __name__ == "__main__":
    main()
