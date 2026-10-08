"""Phase 5 -> Intern Guide category/type mapping report (WS1 task 3).

Emits docs/evidence/taxonomy_intern_guide_mapping.csv: one row per Phase 5
category/type pair, with the Guide pair it maps to, whether the mapping is
unambiguous, and a one-line reason.

Two rules govern this file, and both come from the brief:

  * Only an `exact` row may ever be applied automatically. Every `review` row,
    and every row that would change the actor CATEGORY, becomes a
    category_doubt review item carrying the proposed value. Nothing is
    reinterpreted silently.
  * Deterministic: the same catalogs produce a byte-identical CSV. Rows are
    emitted in catalog order, not dictionary order, and no timestamp is written
    into the file.

Record counts come from a local ghus_v2_*_test database when one is reachable
through the standard PG environment variables plus PGPASSFILE. Without one the
count column reads UNVERIFIED rather than 0, so a missing count can never be
mistaken for "no records affected".

Usage (local test databases only):
    python -m scripts.taxonomy_intern_guide_mapping
    python -m scripts.taxonomy_intern_guide_mapping --check
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
from pathlib import Path

from agents.common.actor_classification import NOT_APPLICABLE, load_category_catalog

ROOT = Path(__file__).resolve().parents[1]
PHASE5_SEED = ROOT / "agents" / "sql" / "190_v2_reference_data.sql"
OUTPUT = ROOT / "docs" / "evidence" / "taxonomy_intern_guide_mapping.csv"

EXACT = "exact"
REVIEW = "review"
UNVERIFIED = "UNVERIFIED"

COLUMNS = (
    "old_category",
    "old_type",
    "record_count",
    "new_category",
    "new_type",
    "rule",
    "reason",
)

# Phase 5 pair -> (new category, new type or None, rule, reason).
#
# A new_type of None means the Guide cannot name the replacement from the stored
# value alone: a human has to read the record. Those rows carry the candidate in
# the reason so the review item can propose it.
MAPPING: dict[tuple[str, str], tuple[str, str | None, str, str]] = {
    # 1 · University / Academic Institution
    ("university_academic", "university_system"): (
        "university_academic", "university_system", EXACT,
        "Same meaning; the Guide relabels it Main Institution.",
    ),
    ("university_academic", "college_school"): (
        "university_academic", "college_school", EXACT,
        "Same meaning; relabelled College / School.",
    ),
    ("university_academic", "academic_department"): (
        "university_academic", "academic_department", EXACT,
        "Same meaning; relabelled Department.",
    ),
    ("university_academic", "branch_campus"): (
        "university_academic", None, REVIEW,
        "The Guide has no branch-campus type. A reviewer decides between Main "
        "Institution for a campus that is its own institution and Not Applicable.",
    ),
    ("university_academic", "community_technical_college"): (
        "university_academic", None, REVIEW,
        "The Guide has no community or technical college type. A reviewer decides "
        "between Main Institution and Not Applicable.",
    ),
    ("university_academic", "other"): (
        "university_academic", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 2 · Research Center / Institute / Laboratory
    ("research_center", "independent_institute"): (
        "research_center", "independent_institute", EXACT,
        "Same meaning; relabelled Independent.",
    ),
    ("research_center", "university_affiliated_center"): (
        "university_academic", "research_lab_center", REVIEW,
        "CATEGORY CHANGE (decision D2). The Guide puts a university research "
        "lab in Category 1. Never applied automatically.",
    ),
    ("research_center", "research_lab_group"): (
        "research_center", None, REVIEW,
        "A reviewer decides whether the group is independent (Category 2) or a "
        "university unit (Category 1, Research Lab / Center).",
    ),
    ("research_center", "other"): (
        "research_center", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 3 · National Laboratory
    ("national_laboratory", "doe_national_lab"): (
        "national_laboratory", None, REVIEW,
        "The Guide types a national lab by its OPERATOR. The operator is not in "
        "the stored value, so a reviewer reads the management contract.",
    ),
    ("national_laboratory", "ffrdc"): (
        "national_laboratory", None, REVIEW,
        "The Guide types a national lab by its operator. A reviewer reads the "
        "FFRDC entry to choose University-Operated, Corporate-Operated, "
        "Consortium-Operated or Government-Direct.",
    ),
    ("national_laboratory", "federal_research_facility"): (
        "national_laboratory", None, REVIEW,
        "Designation check first. With a formal FFRDC or charter this is "
        "Government-Direct; without one the Guide moves it to Category 2, "
        "Government-Affiliated, which is a category change.",
    ),
    ("national_laboratory", "other"): (
        "national_laboratory", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 4 · Applied Research Facility / Testbed / Field Site
    ("applied_facility", "experimental_farm_station"): (
        "applied_facility", None, REVIEW,
        "The Guide types an applied facility by its operator, and a "
        "university-run station belongs in Category 1 instead.",
    ),
    ("applied_facility", "pilot_demonstration_plant"): (
        "applied_facility", None, REVIEW,
        "The Guide types an applied facility by its operator, and a "
        "university-run plant belongs in Category 1 instead.",
    ),
    ("applied_facility", "testbed"): (
        "applied_facility", None, REVIEW,
        "The Guide types an applied facility by its operator, and a "
        "university-run testbed belongs in Category 1 instead.",
    ),
    ("applied_facility", "field_site_living_lab"): (
        "applied_facility", None, REVIEW,
        "The Guide types an applied facility by its operator, and a "
        "university-run field site belongs in Category 1 instead.",
    ),
    ("applied_facility", "other"): (
        "applied_facility", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 5 · Hospital / Clinical System / Medical Center
    ("hospital_clinical", "academic_medical_center"): (
        "hospital_clinical", "academic_medical_center", EXACT,
        "Same meaning; relabelled University-Affiliated.",
    ),
    ("hospital_clinical", "health_system"): (
        "hospital_clinical", None, REVIEW,
        "The Guide splits a health system into Nonprofit and For-Profit. "
        "Ownership is not in the stored value.",
    ),
    ("hospital_clinical", "hospital"): (
        "hospital_clinical", None, REVIEW,
        "The Guide types a hospital by ownership: standalone, nonprofit system, "
        "for-profit system, public or university-affiliated.",
    ),
    ("hospital_clinical", "specialty_clinic_center"): (
        "hospital_clinical", None, REVIEW,
        "The Guide has no specialty-clinic type. A reviewer picks the ownership "
        "type that fits, or Not Applicable.",
    ),
    ("hospital_clinical", "other"): (
        "hospital_clinical", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 6 · Company / Corporate Actor
    ("company", "large_multinational"): (
        "company", None, REVIEW,
        "The Guide splits large companies into Public Company and Private "
        "Company. Listing status is not in the stored value.",
    ),
    ("company", "small_mid_size"): (
        "company", "small_mid_size", EXACT,
        "Same meaning; relabelled SME.",
    ),
    ("company", "business_unit_subsidiary"): (
        "company", "business_unit_subsidiary", EXACT,
        "Same meaning; relabelled Subsidiary / Business Unit.",
    ),
    ("company", "corporate_rd_center"): (
        "company", None, REVIEW,
        "The Guide has no corporate R&D centre type. A corporate research centre "
        "is usually Category 2, Corporate-Operated, which is a category change.",
    ),
    ("company", "other"): (
        "company", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 7 · Startup / Emerging Technology Company
    ("startup", "university_spinout"): (
        "startup", "university_spinout", EXACT, "Identical meaning and code.",
    ),
    ("startup", "corporate_spinout"): (
        "startup", "corporate_spinout", EXACT, "Identical meaning and code.",
    ),
    ("startup", "independent_startup"): (
        "startup", "independent_startup", EXACT,
        "Same meaning; relabelled Independent.",
    ),
    ("startup", "other"): (
        "startup", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 8 · Innovation & Entrepreneurship (E&I) Platform
    ("innovation_platform", "incubator"): (
        "innovation_platform", "incubator", EXACT, "Identical meaning and code.",
    ),
    ("innovation_platform", "accelerator"): (
        "innovation_platform", "accelerator", EXACT, "Identical meaning and code.",
    ),
    ("innovation_platform", "venture_studio"): (
        "innovation_platform", "venture_studio", EXACT,
        "Same meaning; label re-cased to Venture Studio.",
    ),
    ("innovation_platform", "innovation_center_shared_lab"): (
        "innovation_platform", None, REVIEW,
        "The Guide has no innovation-centre type. A reviewer applies the Category "
        "8 versus Category 12 test: operates space itself, or convenes members.",
    ),
    ("innovation_platform", "tech_transfer_office"): (
        "university_academic", "tech_transfer_office", REVIEW,
        "CATEGORY CHANGE. The Guide puts a tech transfer office in Category 1. "
        "Never applied automatically.",
    ),
    ("innovation_platform", "other"): (
        "innovation_platform", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 9 · Investor / Funding Platform
    ("investor", "venture_capital"): (
        "investor", "venture_capital", EXACT,
        "Same meaning; relabelled Venture Capital Firm.",
    ),
    ("investor", "corporate_venture"): (
        "investor", "corporate_venture", EXACT,
        "Same meaning; relabelled Corporate Venture Arm.",
    ),
    ("investor", "angel_group"): (
        "investor", "angel_group", EXACT,
        "Same meaning, widened by the Guide to Family Office / Angel Network.",
    ),
    ("investor", "impact_climate_fund"): (
        "investor", None, REVIEW,
        "The Guide has no impact or climate fund type. A reviewer picks the "
        "capital source that fits, or Not Applicable.",
    ),
    ("investor", "private_equity_growth"): (
        "investor", None, REVIEW,
        "The Guide has no private equity or growth fund type. A reviewer picks "
        "the capital source that fits, or Not Applicable.",
    ),
    ("investor", "public_investment_fund"): (
        "investor", "public_investment_fund", EXACT,
        "Same meaning; relabelled Government Fund.",
    ),
    ("investor", "other"): (
        "investor", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 10 · Government Agency / Public Authority
    ("government", "federal_agency"): (
        "government", "federal_agency", EXACT, "Same meaning; relabelled Federal.",
    ),
    ("government", "state_agency"): (
        "government", "state_agency", EXACT, "Same meaning; relabelled State.",
    ),
    ("government", "local_municipal"): (
        "government", "local_municipal", EXACT,
        "Same meaning; relabelled Local / Municipal.",
    ),
    ("government", "regional_authority"): (
        "government", None, REVIEW,
        "The Guide has no regional or special-purpose authority type. A reviewer "
        "picks the jurisdiction level, or Not Applicable.",
    ),
    ("government", "public_utility"): (
        "government", "public_utility", EXACT, "Identical meaning and code.",
    ),
    ("government", "other"): (
        "government", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 11 · Foundation / Nonprofit
    ("foundation_nonprofit", "private_foundation"): (
        "foundation_nonprofit", "private_foundation", EXACT, "Identical meaning and code.",
    ),
    ("foundation_nonprofit", "corporate_foundation"): (
        "foundation_nonprofit", "corporate_foundation", EXACT, "Identical meaning and code.",
    ),
    ("foundation_nonprofit", "community_foundation"): (
        "foundation_nonprofit", "community_foundation", EXACT, "Identical meaning and code.",
    ),
    ("foundation_nonprofit", "operating_nonprofit"): (
        "foundation_nonprofit", "operating_nonprofit", EXACT, "Identical meaning and code.",
    ),
    ("foundation_nonprofit", "think_tank"): (
        "foundation_nonprofit", None, REVIEW,
        "The Guide has no think-tank type. A reviewer decides between Operating "
        "Nonprofit and Category 2, Research Center, which is a category change.",
    ),
    ("foundation_nonprofit", "other"): (
        "foundation_nonprofit", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
    # 12 · Association / Consortium / Network
    ("association_network", "trade_association"): (
        "association_network", "trade_association", EXACT,
        "Same meaning; relabelled Trade Association.",
    ),
    ("association_network", "research_consortium"): (
        "association_network", "research_consortium", EXACT, "Identical meaning and code.",
    ),
    ("association_network", "professional_society"): (
        "association_network", None, REVIEW,
        "Professional Network is close but not identical: a society may also be a "
        "trade association or a standards body. A reviewer decides.",
    ),
    ("association_network", "standards_body"): (
        "association_network", None, REVIEW,
        "The Guide has no standards-body type. A reviewer decides between Trade "
        "Association, Innovation Consortium and Not Applicable.",
    ),
    ("association_network", "alliance_coalition"): (
        "association_network", None, REVIEW,
        "The Guide has no alliance or coalition type. A reviewer decides which "
        "membership type the body actually is.",
    ),
    ("association_network", "multi_location_network"): (
        "association_network", "multi_location_network", EXACT,
        "Same meaning; relabelled Statewide / Multi-Location Network.",
    ),
    ("association_network", "other"): (
        "association_network", NOT_APPLICABLE, EXACT,
        "Phase 5 Other maps to Not Applicable and raises a category_doubt item.",
    ),
}


def phase5_pairs() -> list[tuple[str, str]]:
    """The Phase 5 catalog, read from its own seed in catalog order."""

    sql = PHASE5_SEED.read_text(encoding="utf-8")
    body = sql.split("INSERT INTO actor_category_type_definition", 1)[1].split(
        "ON CONFLICT (category_code,type_code)", 1
    )[0]
    pairs = re.findall(r"\('([a-z_]+)','([a-z_]+)','[^']*',(?:\d+)\)", body)
    if len(pairs) != 65:
        raise SystemExit(f"expected the 65 Phase 5 pairs in {PHASE5_SEED.name}, found {len(pairs)}")
    return pairs


def record_counts() -> dict[tuple[str, str], int] | None:
    """Count actors per stored pair, or None when no test database is reachable.

    Refuses a password-bearing URL and refuses PGPASSWORD, per the brief. Only
    the standard PG environment variables plus PGPASSFILE are used, and nothing
    about the connection is ever printed.
    """

    if os.environ.get("PGPASSWORD"):
        raise SystemExit("PGPASSWORD must be unset; store the password only in PGPASSFILE")
    required = ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSFILE")
    if any(not os.environ.get(name, "").strip() for name in required):
        return None
    database = os.environ["PGDATABASE"].strip()
    if not database.endswith("_test"):
        raise SystemExit("refusing to read a database whose name does not end in _test")
    try:
        import psycopg
    except ImportError:
        return None
    try:
        with psycopg.connect(
            host=os.environ["PGHOST"].strip(),
            port=int(os.environ["PGPORT"]),
            user=os.environ["PGUSER"].strip(),
            dbname=database,
            sslmode=os.environ.get("PGSSLMODE", "prefer").strip() or "prefer",
        ) as conn, conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                "SELECT actor_category, category_type, count(*) FROM actor "
                "WHERE actor_category IS NOT NULL AND category_type IS NOT NULL "
                "GROUP BY 1, 2"
            )
            return {(row[0], row[1]): int(row[2]) for row in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001 - the reason is reported, never the DSN
        print(f"no record counts: {type(exc).__name__}", file=sys.stderr)
        return None


def build_rows(counts: dict[tuple[str, str], int] | None) -> list[dict[str, str]]:
    pairs = phase5_pairs()
    missing = [pair for pair in pairs if pair not in MAPPING]
    if missing:
        raise SystemExit(f"the mapping table is missing {len(missing)} Phase 5 pair(s): {missing}")
    extra = sorted(set(MAPPING) - set(pairs))
    if extra:
        raise SystemExit(f"the mapping table names pairs Phase 5 never had: {extra}")

    catalog = load_category_catalog()
    rows: list[dict[str, str]] = []
    for old_category, old_type in pairs:
        new_category, new_type, rule, reason = MAPPING[(old_category, old_type)]
        if new_type is not None and not catalog.validates(new_category, new_type):
            raise SystemExit(
                f"mapping target {new_category}/{new_type} is not in the Guide catalog"
            )
        if new_category != old_category and rule != REVIEW:
            raise SystemExit(
                f"{old_category}/{old_type} changes category, so it must be review, not {rule}"
            )
        rows.append({
            "old_category": old_category,
            "old_type": old_type,
            "record_count": (
                str(counts.get((old_category, old_type), 0)) if counts is not None else UNVERIFIED
            ),
            "new_category": new_category,
            "new_type": new_type or "",
            "rule": rule,
            "reason": reason,
        })
    return rows


def render(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="verify the committed CSV matches what this script would write, and write nothing",
    )
    args = parser.parse_args(argv)

    counts = None if args.check else record_counts()
    rows = build_rows(counts)
    rendered = render(rows)

    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT} is missing", file=sys.stderr)
            return 1
        committed = OUTPUT.read_text(encoding="utf-8")
        # A committed CSV carrying real counts still has to agree on every other
        # column, so compare the count-free projection.
        if _without_counts(committed) != _without_counts(rendered):
            print(f"{OUTPUT} is out of date", file=sys.stderr)
            return 1
        print(f"{OUTPUT.name} is current ({len(rows)} rows)")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8", newline="")
    exact = sum(1 for row in rows if row["rule"] == EXACT)
    changes_category = sum(1 for row in rows if row["new_category"] != row["old_category"])
    print(f"wrote {OUTPUT} - {len(rows)} pairs, {exact} exact, {len(rows) - exact} review")
    print(f"{changes_category} mapping(s) change the actor category and are never automatic")
    if counts is None:
        print("record_count is UNVERIFIED: no local _test database was reachable")
    return 0


def _without_counts(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""))
    index = COLUMNS.index("record_count")
    return [[cell for position, cell in enumerate(row) if position != index] for row in reader]


if __name__ == "__main__":
    raise SystemExit(main())
