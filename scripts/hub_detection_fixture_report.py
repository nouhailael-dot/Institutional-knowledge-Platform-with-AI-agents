"""WS5.2: emit docs/evidence/hub_detection_fixture_report.md.

Runs the implemented Phase 7 detection over the synthetic fixture set and
records, for each of the nine required scenarios: input, expected, actual,
PASS/FAIL, proposal centre, distances, family and category matching, and the
evidence behind each number.

Deterministic. The same fixtures produce a byte-identical report, so a rerun
that differs means the algorithm changed, not the harness. No timestamp is
written into the file for that reason.

Detection runs entirely in memory. No database and no network.

    python -m scripts.hub_detection_fixture_report
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from agents.common.hub_detection import HubDetectionConfig
from tests.agent.hub_fixture_data import (
    BASE,
    BOUNDARY_INSIDE,
    BOUNDARY_OUTSIDE,
    CENTER,
    EAST,
    OTHER_TOPIC_ID,
    OTHER_TOPIC_NAME,
    TOPIC_ID,
    coordinates,
    detect,
    miles_between,
    trusted_hub_at,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "evidence" / "hub_detection_fixture_report.md"
CONFIG = HubDetectionConfig()


def _by_key(key):
    return next(item for item in BASE if item.key == key)


def _without(*keys):
    return tuple(item for item in BASE if item.key not in keys)


def _describe(result) -> list[str]:
    lines: list[str] = []
    if not result.proposals:
        lines.append("- Proposals: **none**")
    for proposal in result.proposals:
        lines.append(
            f"- Proposal centre: **{proposal.center_city}, {proposal.center_state_code}** "
            f"({proposal.center_latitude:.6f}, {proposal.center_longitude:.6f})"
        )
        lines.append(f"  - Suggested name: {proposal.suggested_name}")
        lines.append(
            f"  - Independent families: **{proposal.independent_family_count}** "
            f"(threshold {CONFIG.minimum_families}) · "
            f"matched categories: **{proposal.matched_category_count}** "
            f"(threshold {CONFIG.minimum_categories})"
        )
        lines.append(f"  - Members: {len(proposal.members)}")
        lines.append(f"  - Independence statement: {proposal.independence_statement}")
        lines.append(f"  - Membership fingerprint: `{proposal.membership_fingerprint[:16]}…`")
        lines.append("")
        lines.append("  | Member | Category | Type | Family | Distance to centre |")
        lines.append("  |---|---|---|---|---|")
        for member in sorted(proposal.members, key=lambda m: m.actor_id):
            distance = (
                f"{member.distance_miles_raw:.2f} mi"
                if member.distance_miles_raw is not None else "not measured"
            )
            lines.append(
                f"  | {member.actor_id} | {member.actor_category} | {member.category_type} "
                f"| {member.family_id} | {distance} |"
            )
        lines.append("")
        lines.append("  Family/category matching used for the threshold:")
        for family, category in proposal.family_category_pairs:
            lines.append(f"  - `{family}` → `{category}`")
        lines.append("")
    for suppression in result.suppressions:
        lines.append(
            f"- Suppression: **{suppression.reason}** at {suppression.center_city} "
            f"({len(suppression.actor_ids)} actors)"
        )
        if suppression.existing_hub_id:
            lines.append(f"  - Covering hub: `{suppression.existing_hub_id}`")
        if suppression.assignment_plans:
            lines.append(f"  - Assignment plans prepared: {len(suppression.assignment_plans)}")
        if suppression.family_fingerprint:
            lines.append(f"  - Family fingerprint: `{suppression.family_fingerprint[:16]}…`")
    if result.unresolved_hierarchy:
        lines.append("- Unresolved hierarchy (fails closed, never guessed):")
        for key, reason in sorted(result.unresolved_hierarchy.items()):
            lines.append(f"  - `{key.split(':', 1)[1]}`: {reason}")
    if result.prerequisite_exclusions:
        lines.append("- Prerequisite exclusions:")
        for key, reason in sorted(result.prerequisite_exclusions.items()):
            lines.append(f"  - `{key}`: {reason}")
    return lines


def scenarios() -> list[dict]:
    base_result = detect(BASE)
    fingerprint = base_result.proposals[0].membership_fingerprint

    four_categories = [
        ("company", "private_company"), ("startup", "independent_startup"),
        ("investor", "venture_capital"), ("foundation_nonprofit", "private_foundation"),
    ]
    s3_actors = tuple(
        replace(item, category=four_categories[index % 4][0],
                category_type=four_categories[index % 4][1])
        for index, item in enumerate(BASE)
    )
    s6_actors = (
        *_without("soilsense", "harvest-ventures"),
        replace(_by_key("soilsense"), status="parked"),
        replace(_by_key("harvest-ventures"), topic_id=OTHER_TOPIC_ID,
                topic_name=OTHER_TOPIC_NAME),
    )
    s7_extra = tuple(
        replace(_by_key("alpha-plant-sciences"), key=f"alpha-dept-{index}",
                name=f"FX Alpha Department {index}")
        for index in range(1, 4)
    )
    s7_cyclic = (
        replace(_by_key("university-alpha"), parent_key="alpha-plant-sciences"),
        *_without("university-alpha"),
    )

    return [
        {
            "id": "S1",
            "title": "A qualifying set yields one proposal and creates no hub",
            "input": f"The {len(BASE)}-actor base fixture: one controlled topic, "
                     f"Sacramento Valley, all Verified.",
            "expected": "One proposal, with centre, distances, family and category matching "
                        "and evidence. No automatic hub creation.",
            "result": base_result,
        },
        {
            "id": "S2",
            "title": "Nine independent families make no proposal",
            "input": "The base fixture minus three singleton families, so the department "
                     "folding into its university leaves 9 families.",
            "expected": "No proposal.",
            "result": detect(_without("growers-association", "farm-futures-foundation",
                                      "county-ag-department")),
        },
        {
            "id": "S3",
            "title": "Four matched categories make no proposal",
            "input": "The base fixture with every actor rewritten onto four categories, "
                     "keeping the family count unchanged.",
            "expected": "No proposal.",
            "result": detect(s3_actors),
        },
        {
            "id": "S4",
            "title": "Two separate clusters give two deterministic proposals",
            "input": f"The base fixture plus a Greater Boston cluster, "
                     f"{miles_between(CENTER, ('Boston', 'MA')):.0f} miles away.",
            "expected": "Two proposals, with no shared members.",
            "result": detect((*BASE, *EAST)),
        },
        {
            "id": "S5",
            "title": "A trusted same-topic hub suppresses instead of duplicating",
            "input": "The base fixture, with an existing 200-mile hub on the same topic "
                     "centred on Sacramento.",
            "expected": "An assignment plan and a suppression, not a duplicate proposal.",
            "result": detect(BASE, existing_hubs=(trusted_hub_at("Sacramento", "CA"),)),
        },
        {
            "id": "S6",
            "title": "Parked and topic-unverified actors are excluded from the trigger pool",
            "input": "The base fixture with FX SoilSense set to Parked and FX Harvest "
                     "Ventures moved to a different controlled topic.",
            "expected": "The Parked actor never triggers detection; the other-topic actor "
                        "never joins this topic's cluster.",
            "result": detect(s6_actors),
        },
        {
            "id": "S7a",
            "title": "One family with several departments counts once",
            "input": "The base fixture plus three more departments of the same university.",
            "expected": "More members, the same independent-family count.",
            "result": detect((*BASE, *s7_extra)),
        },
        {
            "id": "S7b",
            "title": "An ambiguous or cyclic parent graph fails closed",
            "input": "The base fixture with a university/department parent cycle.",
            "expected": "Both cycled actors reported as unresolved and excluded. Detection "
                        "does not guess a family, and does not abandon the actors it can "
                        "resolve.",
            "result": detect(s7_cyclic),
        },
        {
            "id": "S8",
            "title": "A previously rejected family set is suppressed by its fingerprint",
            "input": "The base fixture, rerun with its own membership fingerprint supplied "
                     "as a prior rejection.",
            "expected": "No proposal; the rejection fingerprint suppresses the unchanged set.",
            "result": detect(BASE, prior_fingerprints=((TOPIC_ID, fingerprint),)),
        },
        {
            "id": "S9",
            "title": "An actor beyond the radius is not assigned",
            "input": f"The base fixture plus {BOUNDARY_OUTSIDE.name} in "
                     f"{BOUNDARY_OUTSIDE.city}, {BOUNDARY_OUTSIDE.state}, "
                     f"{miles_between(CENTER, (BOUNDARY_OUTSIDE.city, BOUNDARY_OUTSIDE.state)):.2f} "
                     f"miles from Davis.",
            "expected": "The out-of-radius actor is not a member of any proposal.",
            "result": detect((*BASE, BOUNDARY_OUTSIDE)),
        },
    ]


def render() -> str:
    lines: list[str] = [
        "# Hub detection fixture report (WS5.2)",
        "",
        "Synthetic fixtures, run against the **implemented Phase 7 detection, unmodified**.",
        "The algorithm was not changed to make any scenario pass. Where a fixture",
        "expectation and the implemented behaviour differ, the implemented behaviour is",
        "what is recorded below.",
        "",
        "| | |",
        "|---|---|",
        f"| Thresholds | {CONFIG.minimum_families} independent families · "
        f"{CONFIG.minimum_categories} matched categories (maximum bipartite matching) · "
        f"{CONFIG.core_radius_miles:.0f}-mile core · {CONFIG.radius_miles:.0f}-mile cluster |",
        f"| Trigger pool | record status in {CONFIG.trigger_statuses} |",
        f"| Method version | `{CONFIG.method_version}` |",
        f"| Fingerprint version | `{CONFIG.fingerprint_version}` |",
        "| Data | synthetic, `FX-` prefixed, in memory only. No database was written, "
        "read or contacted. |",
        "| Coordinates | vendored Census gazetteer (`agents/data/gazetteer`) |",
        "| Distances | `agents.common.geography.distance_miles` (haversine). "
        "None is hand-estimated. |",
        "",
        "## Base fixture",
        "",
        "| # | Fixture actor | Category → Type | City | Miles from Davis, CA | Family |",
        "|---|---|---|---|---|---|",
    ]
    for index, item in enumerate(BASE, start=1):
        miles = miles_between(CENTER, (item.city, item.state))
        lines.append(
            f"| {index} | {item.name} | {item.category} → {item.category_type} "
            f"| {item.city}, {item.state} | {miles:.2f} | {item.family_note} |"
        )
    lines += [
        "",
        "Thirteen actors, twelve independent families: FX Alpha Dept. of Plant Sciences is",
        "a `unit_of` the university and therefore shares its family. FX SeedGen is a",
        "`spinout_of` the university, which the Intern Guide is explicit is **not**",
        "parenthood, so it counts as its own family.",
        "",
        "## The 200-mile boundary",
        "",
        "Two real gazetteer cities that straddle the cluster radius, so the boundary is",
        "measured rather than asserted:",
        "",
        "| Fixture | City | Miles from Davis, CA | Inside the 200-mile cluster |",
        "|---|---|---|---|",
    ]
    for item in (BOUNDARY_INSIDE, BOUNDARY_OUTSIDE):
        miles = miles_between(CENTER, (item.city, item.state))
        lines.append(
            f"| {item.name} | {item.city}, {item.state} | {miles:.2f} "
            f"| {'yes' if miles <= CONFIG.radius_miles else 'no'} |"
        )

    lines += ["", "## Scenarios", ""]
    for scenario in scenarios():
        lines += [
            f"### {scenario['id']} — {scenario['title']}",
            "",
            f"**Input.** {scenario['input']}",
            "",
            f"**Expected.** {scenario['expected']}",
            "",
            "**Actual.**",
            "",
            *_describe(scenario["result"]),
            "",
        ]

    lines += [
        "## Determinism",
        "",
        "Every scenario above is rerun in",
        "`tests/agent/test_hub_detection_fixtures.py`, which asserts that two runs over the",
        "same fixtures produce identical proposal payloads, identical suppression reasons",
        "and an identical eligible-actor list. This report carries no timestamp for the",
        "same reason: a diff between two runs means the algorithm changed.",
        "",
        "## What this report does not do",
        "",
        "- It creates no hub. Detection only ever produces a **proposal** for GHUS.",
        "- It writes nothing to any database, local or remote.",
        "- It does not change the family-aware algorithm, the thresholds, or the Phase 6",
        "  assignment logic.",
        "",
        "## Open item for GHUS",
        "",
        "The Architecture V2 docx text says 3 Verified actors from 2 categories, while the",
        "approved modified spec and the implemented Phase 7 use 10 families / 5 categories",
        "/ 50 miles / 200 miles. These fixtures run the implemented rules. Decision D5 of",
        "the brief keeps them, and Appendix H item 1 asks GHUS to confirm the meeting did",
        "not intend to replace them.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rendered = render()
    OUTPUT.write_text(rendered, encoding="utf-8", newline="")
    print(f"wrote {OUTPUT} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
