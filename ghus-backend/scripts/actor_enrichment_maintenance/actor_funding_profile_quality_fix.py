"""Correct obvious funding-profile type mismatches without using AI credits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # ghus-backend/
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from actor_quality_claude_refine import audit_actor  # noqa: E402
from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


SUMMARIES = {
    "company": (
        "Corporate/operator funding profile: R&D, pilots, and deployment are primarily financed through corporate budgets, "
        "revenue, customer contracts, project finance, and strategic partnerships. No GHUS-specific award amount is verified."
    ),
    "academic": (
        "Academic funding profile: likely supported through university budgets, federal or state research grants, sponsored "
        "research, philanthropy, and industry collaborations. No GHUS-specific award amount is verified."
    ),
    "health": (
        "Health and biomedical funding profile: supported through institutional budgets, NIH-style grants, clinical-trial "
        "sponsors, philanthropy, reimbursement-linked operations where applicable, and industry collaborations."
    ),
    "public": (
        "Public-sector funding profile: supported through public appropriations, agency program budgets, grants, contracts, "
        "fees, and interagency implementation funds. No GHUS-specific award amount is verified."
    ),
    "un": (
        "UN/intergovernmental funding profile: supported through assessed or voluntary government contributions, donor grants, "
        "trust funds, program budgets, and project-specific partnerships. No GHUS-specific award amount is verified."
    ),
    "multilateral": (
        "Multilateral finance profile: supported through member-government contributions, donor replenishments, concessional "
        "finance, trust funds, and project-specific co-financing. No GHUS-specific award amount is verified."
    ),
    "consortium": (
        "Association/consortium funding profile: likely supported through member dues, sponsor contributions, grants, "
        "philanthropy, public programs, and project-specific partner funding. No single award amount is verified."
    ),
    "research_org": (
        "Research-organization funding profile: likely supported through federal mission contracts, sponsored research, "
        "institutional support, grants, philanthropy, and partner-funded projects. No GHUS-specific amount is verified."
    ),
}


MANUAL_PROFILES = {
    "ArcelorMittal USA": "company",
    "Biomedical Advanced Research and Development Authority (BARDA)": "public",
    "Cleveland Clinic": "health",
    "Colorado School of Mines Mining Engineering Department": "academic",
    "Commission for Social Development": "un",
    "Commission on Population and Development": "un",
    "Commission on Science and Technology for Development": "un",
    "Commission on the Status of Women": "un",
    "Department of Economic and Social Affairs": "un",
    "DOE Nuclear Energy University Program (NEUP)": "public",
    "Food and Agriculture Organization": "un",
    "Great Lakes Commission": "un",
    "Helix Park (life sciences commercialization district)": "consortium",
    "Houston Methodist Hospital": "health",
    "Instituto de Pesquisas Energ�ticas e Nucleares (IPEN/CNEN) � Environmental Radiometry Lab": "research_org",
    "International Fund for Agricultural Development": "multilateral",
    "International Joint Commission": "un",
    "International Telecommunication Union": "un",
    "Iowa State University": "academic",
    "Johns Hopkins Applied Physics Laboratory (health security interface)": "research_org",
    "Johns Hopkins University & Johns Hopkins Medicine": "health",
    "MIT Climate & Sustainability Consortium": "consortium",
    "Mount Sinai Health System": "health",
    "National Institute of Standards and Technology (NIST � biosystems & standards)": "public",
    "NewYork-Presbyterian Hospital": "health",
    "NIH Intramural Research Program": "public",
    "NOAA Great Lakes Environmental Research Laboratory": "public",
    "NOAA Physical Sciences Laboratory": "public",
    "Northwestern Medicine": "health",
    "Office for Digital and Emerging Technologies": "un",
    "Office of the Special Adviser on Africa": "un",
    "Rainbow Rare Earths � Uberaba Project": "company",
    "Software Engineering Institute (SEI)": "research_org",
    "Stanford Medicine": "health",
    "UC Agriculture & Natural Resources (UC ANR)": "academic",
    "UN Women": "un",
    "UNGA Second Committee (Economic and Financial)": "un",
    "UNIDO": "un",
    "United Nations Academic Impact (UNAI) An initiative led by the UN Department of Global Communications": "un",
    "United Nations Children's Fund": "un",
    "University of Chicago Medicine": "health",
    "University of Tennessee": "academic",
    "Weill Cornell Medicine": "health",
    "World Food Programme": "un",
    "World Health Organization": "un",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changes: list[str] = []
    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        for actor in actors:
            codes = {issue.code for issue in audit_actor(actor)}
            if "funding_profile_type_mismatch" not in codes:
                continue
            profile = MANUAL_PROFILES.get(actor.name)
            if not profile:
                continue
            new_summary = SUMMARIES[profile]
            if (actor.funding_summary or "").strip() == new_summary:
                continue
            changes.append(f"{actor.name}|{profile}")
            if args.apply:
                actor.funding_summary = new_summary

        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode={'apply' if args.apply else 'dry_run'}")
    print(f"changed_rows={len(changes)}")
    for item in changes:
        print("CHANGED|" + item)


if __name__ == "__main__":
    main()
