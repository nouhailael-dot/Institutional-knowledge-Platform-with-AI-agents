"""Backfill actor_profile, actor_capability_fact, and actor_evaluation.

This keeps all existing actor columns intact. It copies exact actor column
values into fact rows, derives evaluations from existing relevance/profile
tables, and optionally uses Claude to write compact actor_profile summaries.

Dry-run by default:
    python scripts/actor_enrichment_maintenance/backfill_actor_profile_fact_evaluation.py

Apply:
    python scripts/actor_enrichment_maintenance/backfill_actor_profile_fact_evaluation.py --apply --use-claude
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.client import HAIKU, SONNET, UsageTracker, call_claude, parse_json_response  # noqa: E402
from src.db.session import engine  # noqa: E402


logger = logging.getLogger("backfill_actor_profile_fact_evaluation")


FACT_FIELDS = {
    "primary_technical_focus": "technical_focus",
    "technical_approach": "technical_approach",
    "current_activities": "current_activity",
    "technology_ip_notes": "technology_ip",
    "key_constraints": "constraint",
    "funding_summary": "funding",
}


@dataclass
class Stats:
    actors_seen: int = 0
    profiles_upserted: int = 0
    profiles_from_claude: int = 0
    profiles_from_deterministic: int = 0
    facts_upserted: int = 0
    evaluations_from_relevance: int = 0
    evaluations_from_partnership: int = 0
    claude_batches: int = 0
    claude_failures: int = 0


def clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def truncate(value: Any, limit: int) -> str | None:
    s = clean(value)
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 3].rstrip() + "..."


def location(actor: dict[str, Any]) -> str | None:
    parts = [clean(actor.get("location_city")), clean(actor.get("state")), clean(actor.get("country"))]
    parts = [p for p in parts if p]
    return ", ".join(parts) or None


def deterministic_profile(actor: dict[str, Any]) -> dict[str, str | None]:
    loc = location(actor)
    identity_bits = [actor["name"]]
    if clean(actor.get("actor_type")):
        identity_bits.append(f"type: {actor['actor_type']}")
    if loc:
        identity_bits.append(f"location: {loc}")
    if clean(actor.get("website")):
        identity_bits.append(f"website: {actor['website']}")
    if clean(actor.get("hub_names")):
        identity_bits.append(f"hubs: {actor['hub_names']}")

    technical_parts = [
        clean(actor.get("primary_technical_focus")),
        clean(actor.get("technical_approach")),
        clean(actor.get("current_activities")),
        clean(actor.get("technology_ip_notes")),
        clean(actor.get("key_constraints")),
    ]
    technical_parts = [p for p in technical_parts if p]

    lifecycle = clean(actor.get("primary_lifecycle_role"))
    trl = actor.get("estimated_trl")
    lifecycle_summary = None
    if lifecycle and trl is not None:
        lifecycle_summary = f"Lifecycle role: {lifecycle}; estimated TRL: {trl}."
    elif lifecycle:
        lifecycle_summary = f"Lifecycle role: {lifecycle}."
    elif trl is not None:
        lifecycle_summary = f"Estimated TRL: {trl}."

    profile_bits = [clean(actor.get("description")), clean(actor.get("primary_technical_focus"))]
    profile_bits = [p for p in profile_bits if p]
    if not profile_bits:
        profile_bits = [f"{actor['name']} is tracked as an ecosystem actor."]

    return {
        "profile_summary": truncate(" ".join(profile_bits), 700),
        "identity_summary": truncate("; ".join(identity_bits), 700),
        "technical_summary": truncate(" ".join(technical_parts), 1000),
        "funding_summary": truncate(actor.get("funding_summary"), 900),
        "lifecycle_summary": truncate(lifecycle_summary, 500),
    }


def fetch_actors(conn, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        select
            a.actor_id,
            a.name,
            a.actor_type,
            a.description,
            a.website,
            a.location_city,
            a.state,
            a.country,
            a.primary_technical_focus,
            a.technical_approach,
            a.current_activities,
            a.technology_ip_notes,
            a.key_constraints,
            a.funding_summary,
            a.estimated_trl,
            a.primary_lifecycle_role,
            a.source_id,
            a.verification_status,
            a.confidence,
            a.merged_into_actor_id,
            string_agg(distinct h.name, '; ' order by h.name) as hub_names
        from actor a
        left join hub_actor ha on ha.actor_id = a.actor_id
        left join hub h on h.hub_id = ha.hub_id
        group by a.actor_id
        order by a.name
    """
    if limit:
        sql += " limit :limit"
        result = conn.execute(text(sql), {"limit": limit})
    else:
        result = conn.execute(text(sql))
    return [dict(row._mapping) for row in result]


def claude_profiles(
    actors: list[dict[str, Any]],
    model: str,
    tracker: UsageTracker,
    max_cost: float | None,
) -> dict[str, dict[str, str | None]]:
    if max_cost is not None and tracker.cost_estimate() >= max_cost:
        return {}

    payload = []
    for actor in actors:
        payload.append({
            "actor_id": str(actor["actor_id"]),
            "name": actor["name"],
            "actor_type": actor.get("actor_type"),
            "description": truncate(actor.get("description"), 500),
            "website": actor.get("website"),
            "location": location(actor),
            "hubs": truncate(actor.get("hub_names"), 300),
            "primary_technical_focus": truncate(actor.get("primary_technical_focus"), 350),
            "technical_approach": truncate(actor.get("technical_approach"), 350),
            "current_activities": truncate(actor.get("current_activities"), 350),
            "technology_ip_notes": truncate(actor.get("technology_ip_notes"), 250),
            "key_constraints": truncate(actor.get("key_constraints"), 250),
            "funding_summary": truncate(actor.get("funding_summary"), 300),
            "estimated_trl": actor.get("estimated_trl"),
            "primary_lifecycle_role": actor.get("primary_lifecycle_role"),
        })

    system = (
        "You cleanly summarize ecosystem actor database rows. Use only the provided fields. "
        "Do not invent awards, websites, projects, locations, or funding. If evidence is weak, say so plainly. "
        "Return strict JSON only."
    )
    user = json.dumps({
        "task": (
            "For each actor, produce concise database-ready profile fields. "
            "Keep profile_summary to 1-2 sentences. Keep other summaries short and faithful."
        ),
        "output_schema": {
            "profiles": [
                {
                    "actor_id": "uuid",
                    "profile_summary": "string|null",
                    "identity_summary": "string|null",
                    "technical_summary": "string|null",
                    "funding_summary": "string|null",
                    "lifecycle_summary": "string|null",
                }
            ]
        },
        "actors": payload,
    }, ensure_ascii=True)

    response = call_claude(model=model, system=system, user=user, max_tokens=5000, tracker=tracker)
    data = parse_json_response(response)
    if not data or not isinstance(data.get("profiles"), list):
        return {}

    out = {}
    expected_ids = {str(a["actor_id"]) for a in actors}
    for item in data["profiles"]:
        actor_id = str(item.get("actor_id", "")).strip()
        if actor_id not in expected_ids:
            continue
        out[actor_id] = {
            "profile_summary": truncate(item.get("profile_summary"), 700),
            "identity_summary": truncate(item.get("identity_summary"), 700),
            "technical_summary": truncate(item.get("technical_summary"), 1000),
            "funding_summary": truncate(item.get("funding_summary"), 900),
            "lifecycle_summary": truncate(item.get("lifecycle_summary"), 500),
        }
    return out


def upsert_profile(conn, actor: dict[str, Any], fields: dict[str, Any], source_id, generated_by: str) -> None:
    conn.execute(text("""
        insert into actor_profile (
            actor_profile_id, actor_id, profile_summary, identity_summary,
            technical_summary, funding_summary, lifecycle_summary, source_id,
            verification_status, confidence, generated_by
        )
        values (
            :actor_profile_id, :actor_id, :profile_summary, :identity_summary,
            :technical_summary, :funding_summary, :lifecycle_summary, :source_id,
            :verification_status, :confidence, :generated_by
        )
        on conflict (actor_id) do update set
            profile_summary = excluded.profile_summary,
            identity_summary = excluded.identity_summary,
            technical_summary = excluded.technical_summary,
            funding_summary = excluded.funding_summary,
            lifecycle_summary = excluded.lifecycle_summary,
            source_id = excluded.source_id,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """), {
        "actor_profile_id": uuid.uuid4(),
        "actor_id": actor["actor_id"],
        "profile_summary": fields.get("profile_summary"),
        "identity_summary": fields.get("identity_summary"),
        "technical_summary": fields.get("technical_summary"),
        "funding_summary": fields.get("funding_summary"),
        "lifecycle_summary": fields.get("lifecycle_summary"),
        "source_id": source_id,
        "verification_status": actor.get("verification_status"),
        "confidence": actor.get("confidence"),
        "generated_by": generated_by,
    })


def upsert_facts(conn, actor: dict[str, Any]) -> int:
    count = 0
    for source_field, fact_type in FACT_FIELDS.items():
        value = clean(actor.get(source_field))
        if not value:
            continue
        conn.execute(text("""
            insert into actor_capability_fact (
                actor_capability_fact_id, actor_id, fact_type, source_field,
                fact_value, source_id, evidence_url, verification_status,
                confidence, generated_by
            )
            values (
                :fact_id, :actor_id, :fact_type, :source_field,
                :fact_value, :source_id, :evidence_url, :verification_status,
                :confidence, :generated_by
            )
            on conflict (actor_id, fact_type, source_field) do update set
                fact_value = excluded.fact_value,
                source_id = excluded.source_id,
                evidence_url = excluded.evidence_url,
                verification_status = excluded.verification_status,
                confidence = excluded.confidence,
                generated_by = excluded.generated_by,
                updated_at = now()
        """), {
            "fact_id": uuid.uuid4(),
            "actor_id": actor["actor_id"],
            "fact_type": fact_type,
            "source_field": f"actor.{source_field}",
            "fact_value": value,
            "source_id": actor.get("source_id"),
            "evidence_url": actor.get("website"),
            "verification_status": actor.get("verification_status"),
            "confidence": actor.get("confidence"),
            "generated_by": "deterministic_actor_column_backfill",
        })
        count += 1
    return count


def combine(parts: list[tuple[str, Any]], limit: int = 1600) -> str | None:
    out = []
    for label, value in parts:
        value = clean(value)
        if value:
            out.append(f"{label}: {value}")
    return truncate(" | ".join(out), limit)


def upsert_evaluations(conn) -> tuple[int, int]:
    relevance_rows = conn.execute(text("""
        select
            ar.actor_id,
            ar.challenge_id as context_entity_id,
            c.name as evaluation_context,
            ar.relevance_score,
            ar.challenge_relevance_narrative,
            ar.why_relevant,
            ar.current_evidence,
            ar.source_links,
            ar.additional_validation_needed,
            ar.source_id
        from actor_relevance ar
        join challenge c on c.challenge_id = ar.challenge_id
    """)).mappings().all()

    relevance_count = 0
    for row in relevance_rows:
        summary = combine([
            ("Relevance", row["challenge_relevance_narrative"]),
            ("Why relevant", row["why_relevant"]),
            ("Validation needed", row["additional_validation_needed"]),
        ])
        evidence = combine([
            ("Current evidence", row["current_evidence"]),
            ("Source links", row["source_links"]),
        ])
        conn.execute(text("""
            insert into actor_evaluation (
                actor_evaluation_id, actor_id, evaluation_context,
                context_entity_type, context_entity_id, score, evaluation_summary,
                evidence_summary, source_id, verification_status, confidence, generated_by
            )
            values (
                :evaluation_id, :actor_id, :evaluation_context,
                'challenge', :context_entity_id, :score, :evaluation_summary,
                :evidence_summary, :source_id, 'phase_1', 1.0,
                'deterministic_actor_relevance_backfill'
            )
            on conflict (actor_id, evaluation_context, context_entity_type, context_entity_id)
            do update set
                score = excluded.score,
                evaluation_summary = excluded.evaluation_summary,
                evidence_summary = excluded.evidence_summary,
                source_id = excluded.source_id,
                verification_status = excluded.verification_status,
                confidence = excluded.confidence,
                generated_by = excluded.generated_by,
                updated_at = now()
        """), {
            "evaluation_id": uuid.uuid4(),
            "actor_id": row["actor_id"],
            "evaluation_context": row["evaluation_context"],
            "context_entity_id": row["context_entity_id"],
            "score": row["relevance_score"],
            "evaluation_summary": summary,
            "evidence_summary": evidence,
            "source_id": row["source_id"],
        })
        relevance_count += 1

    partnership_rows = conn.execute(text("""
        select
            actor_id,
            partnership_profile_id as context_entity_id,
            thematic_focus,
            why_valuable_for_um6p,
            key_entry_points,
            university_programmes,
            funding_delivery_mechanisms,
            budget_overview,
            key_constraints,
            source_id,
            verification_status,
            confidence
        from partnership_profile
    """)).mappings().all()

    partnership_count = 0
    for row in partnership_rows:
        summary = combine([
            ("Thematic focus", row["thematic_focus"]),
            ("UM6P value", row["why_valuable_for_um6p"]),
            ("Entry points", row["key_entry_points"]),
            ("University programmes", row["university_programmes"]),
            ("Funding mechanisms", row["funding_delivery_mechanisms"]),
        ])
        evidence = combine([
            ("Budget overview", row["budget_overview"]),
            ("Constraints", row["key_constraints"]),
        ])
        conn.execute(text("""
            insert into actor_evaluation (
                actor_evaluation_id, actor_id, evaluation_context,
                context_entity_type, context_entity_id, score, evaluation_summary,
                evidence_summary, source_id, verification_status, confidence, generated_by
            )
            values (
                :evaluation_id, :actor_id, 'UM6P partnership profile',
                'partnership_profile', :context_entity_id, :score, :evaluation_summary,
                :evidence_summary, :source_id, :verification_status, :confidence,
                'deterministic_partnership_profile_backfill'
            )
            on conflict (actor_id, evaluation_context, context_entity_type, context_entity_id)
            do update set
                score = excluded.score,
                evaluation_summary = excluded.evaluation_summary,
                evidence_summary = excluded.evidence_summary,
                source_id = excluded.source_id,
                verification_status = excluded.verification_status,
                confidence = excluded.confidence,
                generated_by = excluded.generated_by,
                updated_at = now()
        """), {
            "evaluation_id": uuid.uuid4(),
            "actor_id": row["actor_id"],
            "context_entity_id": row["context_entity_id"],
            "score": row["confidence"],
            "evaluation_summary": summary,
            "evidence_summary": evidence,
            "source_id": row["source_id"],
            "verification_status": row["verification_status"],
            "confidence": row["confidence"],
        })
        partnership_count += 1

    return relevance_count, partnership_count


def source_for_claude(conn, model: str):
    desc = f"Actor sidecar profile backfill generated from current actor rows using {model}"
    existing = conn.execute(text("""
        select source_id from source
        where source_type = 'ai_inference' and description = :description
    """), {"description": desc}).scalar_one_or_none()
    if existing:
        return existing
    source_id = uuid.uuid4()
    conn.execute(text("""
        insert into source (source_id, source_type, retrieved_at, description, trust_tier)
        values (:source_id, 'ai_inference', now(), :description, 'candidate')
    """), {"source_id": source_id, "description": desc})
    return source_id


def bulk_backfill_profiles(conn) -> int:
    result = conn.execute(text("""
        insert into actor_profile (
            actor_profile_id, actor_id, profile_summary, identity_summary,
            technical_summary, funding_summary, lifecycle_summary, source_id,
            verification_status, confidence, generated_by
        )
        select
            gen_random_uuid(),
            a.actor_id,
            coalesce(
                nullif(left(concat_ws(' ',
                    nullif(btrim(a.description), ''),
                    nullif(btrim(a.primary_technical_focus), '')
                ), 700), ''),
                left(a.name || ' is tracked as an ecosystem actor.', 700)
            ) as profile_summary,
            left(concat_ws('; ',
                a.name,
                case when nullif(btrim(a.actor_type), '') is not null then 'type: ' || a.actor_type end,
                case when nullif(btrim(concat_ws(', ', a.location_city, a.state, a.country)), '') is not null
                    then 'location: ' || concat_ws(', ', a.location_city, a.state, a.country) end,
                case when nullif(btrim(a.website), '') is not null then 'website: ' || a.website end,
                case when hub_names.hubs is not null then 'hubs: ' || hub_names.hubs end
            ), 700) as identity_summary,
            left(nullif(concat_ws(' ',
                nullif(btrim(a.primary_technical_focus), ''),
                nullif(btrim(a.technical_approach), ''),
                nullif(btrim(a.current_activities), ''),
                nullif(btrim(a.technology_ip_notes), ''),
                nullif(btrim(a.key_constraints), '')
            ), ''), 1000) as technical_summary,
            left(nullif(btrim(a.funding_summary), ''), 900) as funding_summary,
            left(nullif(concat_ws('; ',
                case when nullif(btrim(a.primary_lifecycle_role), '') is not null
                    then 'Lifecycle role: ' || a.primary_lifecycle_role end,
                case when a.estimated_trl is not null
                    then 'Estimated TRL: ' || a.estimated_trl::text end
            ), ''), 500) as lifecycle_summary,
            a.source_id,
            a.verification_status,
            a.confidence,
            'deterministic_actor_profile_backfill'
        from actor a
        left join (
            select ha.actor_id, string_agg(distinct h.name, '; ' order by h.name) as hubs
            from hub_actor ha
            join hub h on h.hub_id = ha.hub_id
            group by ha.actor_id
        ) hub_names on hub_names.actor_id = a.actor_id
        on conflict (actor_id) do update set
            profile_summary = excluded.profile_summary,
            identity_summary = excluded.identity_summary,
            technical_summary = excluded.technical_summary,
            funding_summary = excluded.funding_summary,
            lifecycle_summary = excluded.lifecycle_summary,
            source_id = excluded.source_id,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """))
    return result.rowcount


def bulk_backfill_facts(conn) -> int:
    result = conn.execute(text("""
        insert into actor_capability_fact (
            actor_capability_fact_id, actor_id, fact_type, source_field,
            fact_value, source_id, evidence_url, verification_status,
            confidence, generated_by
        )
        select
            gen_random_uuid(),
            a.actor_id,
            v.fact_type,
            v.source_field,
            v.fact_value,
            a.source_id,
            a.website,
            a.verification_status,
            a.confidence,
            'deterministic_actor_column_backfill'
        from actor a
        cross join lateral (
            values
                ('technical_focus', 'actor.primary_technical_focus', nullif(btrim(a.primary_technical_focus), '')),
                ('technical_approach', 'actor.technical_approach', nullif(btrim(a.technical_approach), '')),
                ('current_activity', 'actor.current_activities', nullif(btrim(a.current_activities), '')),
                ('technology_ip', 'actor.technology_ip_notes', nullif(btrim(a.technology_ip_notes), '')),
                ('constraint', 'actor.key_constraints', nullif(btrim(a.key_constraints), '')),
                ('funding', 'actor.funding_summary', nullif(btrim(a.funding_summary), ''))
        ) as v(fact_type, source_field, fact_value)
        where v.fact_value is not null
        on conflict (actor_id, fact_type, source_field) do update set
            fact_value = excluded.fact_value,
            source_id = excluded.source_id,
            evidence_url = excluded.evidence_url,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """))
    return result.rowcount


def bulk_backfill_relevance_evaluations(conn) -> int:
    result = conn.execute(text("""
        insert into actor_evaluation (
            actor_evaluation_id, actor_id, evaluation_context,
            context_entity_type, context_entity_id, score, evaluation_summary,
            evidence_summary, source_id, verification_status, confidence, generated_by
        )
        select
            gen_random_uuid(),
            ar.actor_id,
            c.name,
            'challenge',
            ar.challenge_id,
            ar.relevance_score,
            left(nullif(concat_ws(' | ',
                case when nullif(btrim(ar.challenge_relevance_narrative), '') is not null
                    then 'Relevance: ' || ar.challenge_relevance_narrative end,
                case when nullif(btrim(ar.why_relevant), '') is not null
                    then 'Why relevant: ' || ar.why_relevant end,
                case when nullif(btrim(ar.additional_validation_needed), '') is not null
                    then 'Validation needed: ' || ar.additional_validation_needed end
            ), ''), 1600),
            left(nullif(concat_ws(' | ',
                case when nullif(btrim(ar.current_evidence), '') is not null
                    then 'Current evidence: ' || ar.current_evidence end,
                case when nullif(btrim(ar.source_links), '') is not null
                    then 'Source links: ' || ar.source_links end
            ), ''), 1600),
            ar.source_id,
            'phase_1',
            1.0,
            'deterministic_actor_relevance_backfill'
        from actor_relevance ar
        join challenge c on c.challenge_id = ar.challenge_id
        on conflict (actor_id, evaluation_context, context_entity_type, context_entity_id)
        do update set
            score = excluded.score,
            evaluation_summary = excluded.evaluation_summary,
            evidence_summary = excluded.evidence_summary,
            source_id = excluded.source_id,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """))
    return result.rowcount


def bulk_backfill_partnership_evaluations(conn) -> int:
    result = conn.execute(text("""
        insert into actor_evaluation (
            actor_evaluation_id, actor_id, evaluation_context,
            context_entity_type, context_entity_id, score, evaluation_summary,
            evidence_summary, source_id, verification_status, confidence, generated_by
        )
        select
            gen_random_uuid(),
            pp.actor_id,
            'UM6P partnership profile',
            'partnership_profile',
            pp.partnership_profile_id,
            pp.confidence,
            left(nullif(concat_ws(' | ',
                case when nullif(btrim(pp.thematic_focus), '') is not null
                    then 'Thematic focus: ' || pp.thematic_focus end,
                case when nullif(btrim(pp.why_valuable_for_um6p), '') is not null
                    then 'UM6P value: ' || pp.why_valuable_for_um6p end,
                case when nullif(btrim(pp.key_entry_points), '') is not null
                    then 'Entry points: ' || pp.key_entry_points end,
                case when nullif(btrim(pp.university_programmes), '') is not null
                    then 'University programmes: ' || pp.university_programmes end,
                case when nullif(btrim(pp.funding_delivery_mechanisms), '') is not null
                    then 'Funding mechanisms: ' || pp.funding_delivery_mechanisms end
            ), ''), 1600),
            left(nullif(concat_ws(' | ',
                case when nullif(btrim(pp.budget_overview), '') is not null
                    then 'Budget overview: ' || pp.budget_overview end,
                case when nullif(btrim(pp.key_constraints), '') is not null
                    then 'Constraints: ' || pp.key_constraints end
            ), ''), 1600),
            pp.source_id,
            pp.verification_status,
            pp.confidence,
            'deterministic_partnership_profile_backfill'
        from partnership_profile pp
        on conflict (actor_id, evaluation_context, context_entity_type, context_entity_id)
        do update set
            score = excluded.score,
            evaluation_summary = excluded.evaluation_summary,
            evidence_summary = excluded.evidence_summary,
            source_id = excluded.source_id,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """))
    return result.rowcount


def apply_claude_profile_updates(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn.execute(text("""
        insert into actor_profile (
            actor_profile_id, actor_id, profile_summary, identity_summary,
            technical_summary, funding_summary, lifecycle_summary, source_id,
            verification_status, confidence, generated_by
        )
        values (
            :actor_profile_id, :actor_id, :profile_summary, :identity_summary,
            :technical_summary, :funding_summary, :lifecycle_summary, :source_id,
            :verification_status, :confidence, :generated_by
        )
        on conflict (actor_id) do update set
            profile_summary = excluded.profile_summary,
            identity_summary = excluded.identity_summary,
            technical_summary = excluded.technical_summary,
            funding_summary = excluded.funding_summary,
            lifecycle_summary = excluded.lifecycle_summary,
            source_id = excluded.source_id,
            verification_status = excluded.verification_status,
            confidence = excluded.confidence,
            generated_by = excluded.generated_by,
            updated_at = now()
    """), rows)
    return len(rows)


def run(args) -> tuple[Stats, UsageTracker | None]:
    stats = Stats()
    tracker = UsageTracker(model=args.model) if args.use_claude else None

    conn = engine.connect()
    tx = conn.begin()
    try:
        stats.actors_seen = conn.execute(text("select count(*) from actor")).scalar_one()
        stats.profiles_upserted = bulk_backfill_profiles(conn)
        stats.profiles_from_deterministic = stats.profiles_upserted
        stats.facts_upserted = bulk_backfill_facts(conn)
        stats.evaluations_from_relevance = bulk_backfill_relevance_evaluations(conn)
        stats.evaluations_from_partnership = bulk_backfill_partnership_evaluations(conn)

        if args.use_claude:
            actors = fetch_actors(conn, args.limit)
            profile_source_id = source_for_claude(conn, args.model)
            for i in range(0, len(actors), args.batch_size):
                if args.max_claude_cost is not None and tracker.cost_estimate() >= args.max_claude_cost:
                    break
                batch = actors[i : i + args.batch_size]
                generated = claude_profiles(batch, args.model, tracker, args.max_claude_cost)
                stats.claude_batches += 1
                if not generated:
                    stats.claude_failures += 1
                    continue
                rows = []
                actors_by_id = {str(actor["actor_id"]): actor for actor in batch}
                for actor_id, fields in generated.items():
                    actor = actors_by_id.get(actor_id)
                    if not actor:
                        continue
                    rows.append({
                        "actor_profile_id": uuid.uuid4(),
                        "actor_id": actor["actor_id"],
                        "profile_summary": fields.get("profile_summary"),
                        "identity_summary": fields.get("identity_summary"),
                        "technical_summary": fields.get("technical_summary"),
                        "funding_summary": fields.get("funding_summary"),
                        "lifecycle_summary": fields.get("lifecycle_summary"),
                        "source_id": profile_source_id,
                        "verification_status": actor.get("verification_status"),
                        "confidence": actor.get("confidence"),
                        "generated_by": args.model,
                    })
                stats.profiles_from_claude += apply_claude_profile_updates(conn, rows)

        stats.profiles_from_deterministic = (
            stats.profiles_upserted - stats.profiles_from_claude
        )

        if args.apply:
            tx.commit()
        else:
            tx.rollback()
    except Exception:
        tx.rollback()
        raise
    finally:
        conn.close()

    return stats, tracker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--use-claude", action="store_true")
    parser.add_argument("--model", default=HAIKU, choices=[HAIKU, SONNET])
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-claude-cost", type=float, default=0.75)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats, tracker = run(args)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    print(f"actors_seen={stats.actors_seen}")
    print(f"profiles_upserted={stats.profiles_upserted}")
    print(f"profiles_from_claude={stats.profiles_from_claude}")
    print(f"profiles_from_deterministic={stats.profiles_from_deterministic}")
    print(f"facts_upserted={stats.facts_upserted}")
    print(f"evaluations_from_relevance={stats.evaluations_from_relevance}")
    print(f"evaluations_from_partnership={stats.evaluations_from_partnership}")
    print(f"claude_batches={stats.claude_batches}")
    print(f"claude_failures={stats.claude_failures}")
    if tracker:
        print(tracker.summary())
    if not args.apply:
        print("Dry run only; rerun with --apply to write changes.")


if __name__ == "__main__":
    main()
