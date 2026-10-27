"""Audit and selectively improve actor enrichment fields.

This is a quality pass over columns previously filled by enrichment scripts:
website, location_city, state, country, technical profile fields, lifecycle role,
and funding_summary.

By default it only audits. With --apply, it uses Claude Sonnet on the highest-risk
rows and updates the narrative fields that can be corrected conservatively:
technical profile fields, primary_lifecycle_role, and funding_summary.

It intentionally does not let Claude overwrite official websites or locations.
Those fields are audited and reported, because hallucinated URLs/locations are
worse than blanks in a database.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # ghus-backend/
sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.client import SONNET, UsageTracker, call_claude, parse_json_response  # noqa: E402
from src.db.models import Actor, ActorSector, Hub, HubActor, Sector  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TEXT_FIELDS = (
    "primary_technical_focus",
    "technical_approach",
    "current_activities",
    "technology_ip_notes",
    "key_constraints",
    "funding_summary",
)

TECHNICAL_FIELDS = (
    "primary_technical_focus",
    "technical_approach",
    "current_activities",
    "technology_ip_notes",
    "key_constraints",
    "primary_lifecycle_role",
)

AUDITED_FIELDS = (
    "website",
    "location_city",
    "state",
    "country",
    *TECHNICAL_FIELDS,
    "funding_summary",
)

ROLES = {"discovery", "validation", "demonstration", "deployment", "scaling", "Multiple Roles"}

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

WEAK_PHRASES = (
    "existing ghus context references the actor",
    "applied research, translational r&d, ecosystem coordination",
    "applied research, commercialization, or ecosystem coordination",
    "for the linked ecosystem use case",
    "linked hub ecosystem",
    "hub-linked actor referenced",
    "no high-confidence structured api match",
    "no dedicated patent or product portfolio was confirmed",
    "technology/ip posture should be validated directly with the actor",
    "representative or aggregate actor row",
    "category or group of related organizations",
    "general funding profile:",
)

FUNDING_PREFIXES = (
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

AUTHORITATIVE_WEBSITE_PATTERNS = (
    ".edu",
    ".gov",
    ".org",
    ".com",
    ".net",
    ".ai",
    ".io",
    ".co",
    ".us",
    ".vc",
    ".climate",
    ".in",
    ".bio",
    ".google",
    ".int",
    ".xyz",
    ".mil",
    ".nyc",
    ".br",
)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: int


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def lower(value: Any) -> str:
    return clean(value).lower()


def is_blank(value: Any) -> bool:
    return clean(value) == ""


def shorten(value: Any, limit: int = 700) -> str:
    value = clean(value)
    return value[:limit]


def is_url_only(value: Any) -> bool:
    value = clean(value)
    return bool(re.fullmatch(r"https?://\S+", value))


def has_replacement_artifact(value: Any) -> bool:
    value = str(value or "")
    return "\ufffd" in value or "â€”" in value or "â€" in value or "Ã" in value


def is_representative(actor: Actor) -> bool:
    name = lower(actor.name)
    description = lower(actor.description)
    if any(
        protected in name
        for protected in (
            "national institutes of health",
            "novartis institutes",
            "texas corn producers board",
            "texas a&m engineering extension service (teex)",
        )
    ):
        return False
    generic_name = any(name.endswith(term) or f" {term} " in name for term in GENERIC_NAME_TERMS)
    category_name = any(
        phrase in name
        for phrase in (
            "ecosystem mapping",
            " ecosystem",
            "cluster",
            "regional ",
            " e.g.",
            " issuers",
            " partnerships",
            " initiatives",
            " authorities",
            " actors",
            " at scale",
            "where the",
            "system knowledge",
        )
    )
    if "parent un body" in description:
        return True
    if "synthetic, generated from" in description:
        return generic_name or category_name
    if "aggregate actor label" in description or "category or group of related organizations" in description:
        return generic_name or category_name
    if generic_name or category_name:
        return True
    return False


def exactish(actor: Actor) -> bool:
    if is_representative(actor):
        return False
    name = lower(actor.name)
    if any(term in name for term in ("regional presence", "midwest presence", "gulf coast")):
        return False
    return True


def actor_kind(actor: Actor) -> str:
    name = lower(actor.name)
    type_text = lower(" ".join([actor.actor_type or "", actor.actor_type_raw or ""]))
    website = lower(actor.website)
    description = lower(actor.description)
    primary_text = " ".join([name, type_text, website])
    all_text = " ".join([primary_text, description])

    if any(term in primary_text for term in ("national laboratory", "nrel", "argonne", "lawrence livermore", "oak ridge", "jet propulsion laboratory")):
        return "national_lab"
    if any(term in primary_text for term in ("hospital", "medical center", "school of medicine", "college of medicine", "cancer center", "clinic")):
        return "health"
    if any(
        term in primary_text
        for term in (
            "united nations",
            "world bank",
            "unesco",
            "unicef",
            "fao ",
            "undp",
            "un_",
            "un agency",
            "un programme",
            "un committee",
            "world health",
            "world food",
            "un women",
            "unido",
            "international telecommunication union",
            "intergovernmental",
        )
    ):
        return "intergovernmental"
    if any(term in name for term in ("ventures", "venture capital", " capital", " fund", "funds", "accelerator", "incubator")):
        return "finance"
    if any(term in type_text for term in ("industrial_partner", "project_developer", "company", "corporate")):
        return "company"
    if any(term in primary_text for term in ("inc.", " llc", " ltd", "corp", "corporation", "company", "startup", "solutions", "technologies")):
        return "company"
    if any(
        term in name
        for term in (
            "chevron",
            "general electric",
            "phillips 66",
            "basf",
            "bayer",
            "barrick",
            "biogen",
            "biotechnology",
            "bioworks",
            "recycling",
            "u.s. steel",
            "arca climate technologies",
            "deep isolation",
            "carbon to stone",
            "allonnia",
            "anactisis",
            "3m research laboratories",
            "abbott laboratories",
            "arcelormittal",
            "rainbow rare earths",
        )
    ):
        return "company"
    if any(term in type_text for term in ("venture", "capital", "fund", "accelerator", "incubator", "investor")):
        return "finance"
    if any(term in type_text for term in ("federal_agency", "state_agency", "public_agency", "government")):
        return "public_sector"
    if any(term in name for term in ("nist", "noaa ", "national institute of standards")):
        return "public_sector"
    if any(term in primary_text for term in ("department of", "ministry", "authority", "commission", "agency", "office of")):
        return "public_sector"
    if any(term in primary_text for term in ("university", "college", "institute of technology", "school of", "uc ", "caltech", "mit")):
        return "academic"
    if any(term in all_text for term in ("national laboratory", "hospital", "medical center", "united nations", "world bank")):
        return actor_kind_from_secondary_text(all_text)
    if any(term in all_text for term in ("inc.", " llc", " ltd", "corp", "corporation", "company")):
        return "company"
    return "general"


def actor_kind_from_secondary_text(text_value: str) -> str:
    if "national laboratory" in text_value:
        return "national_lab"
    if any(term in text_value for term in ("hospital", "medical center")):
        return "health"
    if any(term in text_value for term in ("united nations", "world bank")):
        return "intergovernmental"
    return "general"


def funding_prefix(value: Any) -> str:
    value = clean(value)
    for prefix in FUNDING_PREFIXES:
        if value.startswith(prefix):
            return prefix
    return ""


def funding_mismatch(actor: Actor) -> bool:
    summary = clean(actor.funding_summary)
    if is_representative(actor):
        return False
    if not funding_prefix(summary):
        return False
    kind = actor_kind(actor)
    if is_blank(summary):
        return False
    expected = {
        "national_lab": (
            "National-lab funding profile:",
            "Public-sector funding profile:",
            "Research-organization funding profile:",
        ),
        "health": (
            "Health and biomedical funding profile:",
            "Academic funding profile:",
            "Research-organization funding profile:",
            "Association/consortium funding profile:",
        ),
        "intergovernmental": (
            "UN/intergovernmental funding profile:",
            "Multilateral finance profile:",
            "Public-sector funding profile:",
        ),
        "public_sector": (
            "Public-sector funding profile:",
            "UN/intergovernmental funding profile:",
            "Health and biomedical funding profile:",
            "National-lab funding profile:",
            "Research-organization funding profile:",
        ),
        "academic": (
            "Academic funding profile:",
            "Research-organization funding profile:",
            "Association/consortium funding profile:",
            "Health and biomedical funding profile:",
            "National-lab funding profile:",
            "Public-sector funding profile:",
        ),
        "finance": (
            "Private investment funding profile:",
            "Startup-support funding profile:",
            "Multilateral finance profile:",
            "UN/intergovernmental funding profile:",
            "Corporate/operator funding profile:",
        ),
    }.get(kind)
    if not expected:
        return False
    if isinstance(expected, tuple):
        return not summary.startswith(expected)
    return not summary.startswith(expected)


def audit_actor(actor: Actor) -> list[Issue]:
    issues: list[Issue] = []
    rep = is_representative(actor)
    exact = exactish(actor)

    for field in AUDITED_FIELDS:
        value = getattr(actor, field)
        if is_blank(value):
            severity = 2 if field in {"website", "location_city", "state", "country"} else 4
            issues.append(Issue(f"blank_{field}", severity))
        elif has_replacement_artifact(value):
            issues.append(Issue(f"encoding_artifact_{field}", 5))

    website = clean(actor.website)
    if website and not website.startswith(("http://", "https://")):
        issues.append(Issue("website_not_http_url", 4))
    if website and not any(pattern in lower(website) for pattern in AUTHORITATIVE_WEBSITE_PATTERNS):
        issues.append(Issue("website_unusual_domain", 2))

    for field in TECHNICAL_FIELDS:
        value = lower(getattr(actor, field))
        if field != "primary_lifecycle_role" and any(phrase in value for phrase in WEAK_PHRASES):
            severity = 4 if exact else 2
            issues.append(Issue(f"weak_template_{field}", severity))

    role = clean(actor.primary_lifecycle_role)
    if role and role not in ROLES:
        issues.append(Issue("invalid_lifecycle_role", 4))

    summary = clean(actor.funding_summary)
    if is_url_only(summary):
        issues.append(Issue("funding_url_only", 5))
    prefix = funding_prefix(summary)
    if prefix == "General funding profile:" and exact:
        issues.append(Issue("funding_too_general_for_exact_actor", 4))
    if prefix == "Representative or aggregate actor row;" and exact:
        issues.append(Issue("funding_representative_for_exact_actor", 5))
    if funding_mismatch(actor):
        issues.append(Issue("funding_profile_type_mismatch", 3))

    if rep and not summary.startswith("Representative or aggregate actor row;"):
        issues.append(Issue("representative_row_not_marked_in_funding", 2))

    return issues


def score_issues(issues: list[Issue]) -> int:
    return sum(issue.severity for issue in issues)


def load_context(session, actor_ids):
    hubs: dict[Any, list[str]] = defaultdict(list)
    sectors: dict[Any, list[str]] = defaultdict(list)
    if not actor_ids:
        return hubs, sectors

    for actor_id, hub_name in session.execute(
        select(HubActor.actor_id, Hub.name)
        .join(Hub, Hub.hub_id == HubActor.hub_id)
        .where(HubActor.actor_id.in_(actor_ids))
    ):
        hubs[actor_id].append(hub_name)

    for actor_id, sector_name in session.execute(
        select(ActorSector.actor_id, Sector.name)
        .join(Sector, Sector.sector_id == ActorSector.sector_id)
        .where(ActorSector.actor_id.in_(actor_ids))
    ):
        sectors[actor_id].append(sector_name)

    return hubs, sectors


def actor_payload(actor: Actor, issues: list[Issue], hubs: list[str], sectors: list[str]) -> dict[str, Any]:
    return {
        "actor_id": str(actor.actor_id),
        "name": actor.name,
        "actor_type": actor.actor_type,
        "actor_kind_guess": actor_kind(actor),
        "representative_or_aggregate": is_representative(actor),
        "website": actor.website,
        "location": {
            "city": actor.location_city,
            "state": actor.state,
            "country": actor.country,
        },
        "description": shorten(actor.description, 900),
        "hubs": hubs[:5],
        "sectors": sectors[:5],
        "flagged_issues": [issue.code for issue in issues],
        "current_values": {field: shorten(getattr(actor, field), 650) for field in (*TECHNICAL_FIELDS, "funding_summary")},
    }


SYSTEM = """You are a careful data-quality editor for a GHUS actor intelligence database.
You correct weak actor enrichment text. Return JSON only with this shape:
{"actors":[{"actor_id":"...","decision":"replace|keep","reason":"...","primary_technical_focus":"...","technical_approach":"...","current_activities":"...","technology_ip_notes":"...","key_constraints":"...","primary_lifecycle_role":"...","funding_summary":"..."}]}

Rules:
- Use the supplied actor name, type, website, location, description, hubs, sectors, and cautious public/domain knowledge.
- Replace generic templates with actor-specific, database-ready wording when the actor is specific.
- If the row is representative/aggregate, keep it clearly representative instead of pretending it is one real organization.
- Do not invent grant IDs, patent numbers, confidential projects, private contracts, exact dollar amounts, or unprovided URLs.
- Funding summaries should describe likely funding model/source categories, not fabricate named awards.
- technology_ip_notes should distinguish public research/open literature, university IP, company proprietary IP, user-facility know-how, or unclear posture.
- key_constraints should be actor- and domain-relevant, not a generic validation warning.
- current_activities should describe present plausible activity area, not say only that GHUS context referenced the actor.
- Keep each text field under 28 words; one compact sentence or phrase, no bullets.
- Keep reason under 12 words.
- primary_lifecycle_role must be exactly one of: discovery, validation, demonstration, deployment, scaling, Multiple Roles.
- If the existing text is already good, decision can be keep, but still return clean values for all fields."""


def build_user(batch: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "task": (
                "Audit these flagged actor rows and return corrected narrative fields. "
                "Focus on exact, useful, conservative text suitable for a production database. "
                "Return compact JSON only; no markdown and no extra commentary."
            ),
            "actors": batch,
        },
        ensure_ascii=False,
    )


def valid_item(item: dict[str, Any], valid_ids: set[str]) -> tuple[bool, str]:
    actor_id = item.get("actor_id")
    if actor_id not in valid_ids:
        return False, "unknown_actor_id"
    if item.get("decision") not in {"replace", "keep"}:
        return False, "bad_decision"
    if item.get("primary_lifecycle_role") not in ROLES:
        return False, "bad_role"
    for field in (*TEXT_FIELDS, "primary_lifecycle_role"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            return False, f"blank_{field}"
        if has_replacement_artifact(item[field]):
            return False, f"encoding_artifact_{field}"
    joined = lower(" ".join(item.get(field, "") for field in TEXT_FIELDS))
    if "existing ghus context references the actor" in joined:
        return False, "still_generic_current_activities"
    if "no high-confidence structured api match" in joined:
        return False, "still_api_match_template"
    if is_url_only(item.get("funding_summary")):
        return False, "url_only_funding"
    return True, ""


def print_audit(rows: list[tuple[Actor, list[Issue]]], limit: int) -> None:
    issue_counts = Counter(issue.code for _, issues in rows for issue in issues)
    weak_rows = [(actor, issues) for actor, issues in rows if issues]
    exact_weak = [(actor, issues) for actor, issues in weak_rows if exactish(actor)]
    representative_weak = [(actor, issues) for actor, issues in weak_rows if is_representative(actor)]

    print(f"actor_rows={len(rows)}")
    print(f"rows_with_any_issue={len(weak_rows)}")
    print(f"exact_rows_with_issue={len(exact_weak)}")
    print(f"representative_rows_with_issue={len(representative_weak)}")
    print("issue_counts:")
    for code, count in issue_counts.most_common():
        print(f"  {code}: {count}")

    print(f"top_flagged_rows_limit={limit}")
    for actor, issues in sorted(weak_rows, key=lambda item: score_issues(item[1]), reverse=True)[:limit]:
        codes = ",".join(issue.code for issue in issues)
        print(f"ROW|score={score_issues(issues)}|name={actor.name}|kind={actor_kind(actor)}|issues={codes}")


def choose_candidates(
    rows: list[tuple[Actor, list[Issue]]],
    limit: int,
    include_representative_weak: bool = False,
) -> list[tuple[Actor, list[Issue]]]:
    candidates = []
    for actor, issues in rows:
        if not issues:
            continue
        codes = {issue.code for issue in issues}
        editable_critical = any(
            code in {
                "blank_primary_technical_focus",
                "blank_technical_approach",
                "blank_current_activities",
                "blank_technology_ip_notes",
                "blank_key_constraints",
                "blank_primary_lifecycle_role",
                "blank_funding_summary",
                "funding_url_only",
                "funding_representative_for_exact_actor",
                "invalid_lifecycle_role",
                "funding_too_general_for_exact_actor",
            }
            or (
                code.startswith("encoding_artifact_")
                and not code.startswith(("encoding_artifact_website", "encoding_artifact_location_city", "encoding_artifact_state", "encoding_artifact_country"))
            )
            for code in codes
        )
        weak_text = any(code.startswith("weak_template_") for code in codes)
        useful_mismatch = "funding_profile_type_mismatch" in codes and weak_text
        eligible = exactish(actor) or (include_representative_weak and weak_text)
        if eligible and (editable_critical or weak_text or useful_mismatch):
            candidates.append((actor, issues))
    candidates.sort(key=lambda item: score_issues(item[1]), reverse=True)
    return candidates[:limit]


def apply_claude_updates(session, candidates, hubs, sectors, args) -> tuple[list[str], list[str], UsageTracker]:
    tracker = UsageTracker(model=SONNET)
    applied: list[str] = []
    skipped: list[str] = []
    actor_by_id = {str(actor.actor_id): actor for actor, _ in candidates}
    payloads = [
        actor_payload(actor, issues, hubs[actor.actor_id], sectors[actor.actor_id])
        for actor, issues in candidates
    ]

    for start in range(0, len(payloads), args.batch_size):
        if tracker.calls >= args.max_calls or tracker.cost_estimate() >= args.max_cost:
            skipped.extend(item["name"] for item in payloads[start:])
            break

        batch = payloads[start:start + args.batch_size]
        response_text = call_claude(
            SONNET,
            SYSTEM,
            build_user(batch),
            max_tokens=args.max_tokens,
            tracker=tracker,
        )
        parsed = parse_json_response(response_text)
        items = (parsed or {}).get("actors", [])
        valid_ids = {item["actor_id"] for item in batch}
        if not items:
            skipped.extend(item["name"] for item in batch)
            continue

        batch_changed = False
        for item in items:
            ok, why = valid_item(item, valid_ids)
            if not ok:
                skipped.append(f"{item.get('actor_id', 'unknown')}:{why}")
                continue
            if item["decision"] == "keep":
                skipped.append(f"{actor_by_id[item['actor_id']].name}:kept_by_claude")
                continue

            actor = actor_by_id[item["actor_id"]]
            before = {field: getattr(actor, field) for field in (*TECHNICAL_FIELDS, "funding_summary")}
            for field in (*TECHNICAL_FIELDS, "funding_summary"):
                setattr(actor, field, item[field].strip())
            after = {field: getattr(actor, field) for field in (*TECHNICAL_FIELDS, "funding_summary")}
            if before != after:
                applied.append(actor.name)
                batch_changed = True

        if args.dry_run:
            session.rollback()
        elif batch_changed:
            session.commit()

    return applied, skipped, tracker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate-limit", type=int, default=30)
    parser.add_argument("--include-representative-weak", action="store_true")
    parser.add_argument("--show-limit", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--max-cost", type=float, default=0.30)
    parser.add_argument("--max-tokens", type=int, default=2200)
    args = parser.parse_args()

    if args.apply and args.audit_only:
        raise SystemExit("--apply and --audit-only cannot both be set")

    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(session.execute(select(Actor).order_by(Actor.name)).scalars())
        actor_ids = [actor.actor_id for actor in actors]
        hubs, sectors = load_context(session, actor_ids)
        rows = [(actor, audit_actor(actor)) for actor in actors]
        print_audit(rows, args.show_limit)

        candidates = choose_candidates(rows, args.candidate_limit, args.include_representative_weak)
        print(f"claude_candidate_rows={len(candidates)}")
        for actor, issues in candidates[: args.show_limit]:
            codes = ",".join(issue.code for issue in issues)
            print(f"CANDIDATE|score={score_issues(issues)}|name={actor.name}|issues={codes}")

        if args.audit_only or not args.apply:
            print("mode=audit_only")
            return

        applied, skipped, tracker = apply_claude_updates(session, candidates, hubs, sectors, args)
        print("mode=apply")
        print(f"model={SONNET}")
        print(f"calls={tracker.calls}")
        print(f"failures={tracker.failures}")
        print(f"input_tokens={tracker.input_tokens}")
        print(f"output_tokens={tracker.output_tokens}")
        print(f"estimated_cost=${tracker.cost_estimate():.4f}")
        print(f"applied_rows={len(applied)}")
        print(f"skipped_rows={len(skipped)}")
        for name in applied:
            print(f"APPLIED|{name}")
        for item in skipped[:60]:
            print(f"SKIPPED|{item}")

        refreshed = [(actor, audit_actor(actor)) for actor in actors]
        remaining_candidates = choose_candidates(refreshed, args.candidate_limit, args.include_representative_weak)
        print(f"remaining_top_candidate_rows={len(remaining_candidates)}")


if __name__ == "__main__":
    main()
