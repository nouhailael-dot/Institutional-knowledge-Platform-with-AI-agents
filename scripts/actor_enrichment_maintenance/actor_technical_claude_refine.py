import argparse
import json
import sys
from collections import defaultdict

from sqlalchemy import select, text

sys.path.insert(0, r"C:\Users\Ismail\Projects\GHUS-Platform")

from src.ai.client import HAIKU, UsageTracker, call_claude, parse_json_response  # noqa: E402
from src.db.models import Actor, ActorSector, Hub, HubActor, Sector  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TARGET_NAMES = [
    "3M Research Laboratories",
    "Abbott Laboratories",
    "ADM (Archer Daniels Midland)",
    "Advanced Light Source",
    "Agricultural Sustainability Institute",
    "Air Products (hydrogen systems)",
    "Albemarle",
    "Allen Institute for AI (Ai2)",
    "Amazon",
    "Amazon (AI & AWS)",
    "Amyris",
    "Anthropic",
    "Apple AI",
    "ArcelorMittal USA",
    "Argonne Advanced Photon Source",
    "Arizona Department of Water Resources",
    "Arizona Geological Survey",
    "Arizona State University (ASU)",
    "Arkema",
    "ASARCO",
    "ASU Global Institute of Sustainability",
    "ASU Kyl Center for Water Policy",
    "Atkinson Center for Sustainability",
    "Aurora Innovation",
    "Auton Lab",
    "Barrick Gold",
    "BASF (Gulf Coast)",
    "BASF Agricultural Solutions",
    "BASF Freeport",
    "Bayer Crop Science",
]

FIELDS = (
    "primary_technical_focus",
    "technical_approach",
    "current_activities",
    "technology_ip_notes",
    "key_constraints",
    "primary_lifecycle_role",
)

ROLES = {"discovery", "validation", "demonstration", "deployment", "scaling"}


SYSTEM = """You enrich GHUS ecosystem actor records.
Return valid JSON only, as {"actors":[...]}.
Use the provided row context plus conservative public/domain knowledge.
Do not invent patent numbers, confidential projects, grants, contracts, or exact partnerships.
If IP is uncertain, describe the likely IP posture cautiously.
Keep every text field concise: one sentence or a short semicolon-separated phrase.
primary_lifecycle_role must be one of: discovery, validation, demonstration, deployment, scaling."""


def compact(value, limit=900):
    text_value = " ".join((value or "").replace("\n", " ").split())
    return text_value[:limit]


def actor_payload(actor, hubs, sectors):
    return {
        "actor_id": str(actor.actor_id),
        "name": actor.name,
        "actor_type": actor.actor_type,
        "website": actor.website,
        "description": compact(actor.description, 650),
        "hubs": hubs[:4],
        "sectors": sectors[:4],
        "current_values": {field: compact(getattr(actor, field), 350) for field in FIELDS},
    }


def build_user(batch):
    return json.dumps(
        {
            "task": (
                "For each actor, improve the six technical fields. Preserve cautious language. "
                "Prefer actor-specific technical focus and activity over generic templates."
            ),
            "required_fields": list(FIELDS),
            "actors": batch,
        },
        ensure_ascii=False,
    )


def valid_update(item, actor_ids):
    actor_id = item.get("actor_id")
    if actor_id not in actor_ids:
        return False
    if item.get("primary_lifecycle_role") not in ROLES:
        return False
    return all(isinstance(item.get(field), str) and item.get(field).strip() for field in FIELDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--max-cost", type=float, default=0.10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected_names = TARGET_NAMES[: max(0, args.limit)]
    tracker = UsageTracker(model=HAIKU)
    applied = []
    skipped = []

    with SessionLocal() as session:
        session.execute(text("set statement_timeout to '10min'"))
        actors = list(
            session.execute(select(Actor).where(Actor.name.in_(selected_names))).scalars()
        )
        order = {name: i for i, name in enumerate(selected_names)}
        actors.sort(key=lambda actor: order.get(actor.name, 10_000))
        actor_ids = [actor.actor_id for actor in actors]

        hubs = defaultdict(list)
        sectors = defaultdict(list)
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

        payloads = [
            actor_payload(actor, hubs[actor.actor_id], sectors[actor.actor_id])
            for actor in actors
        ]
        actor_by_id = {str(actor.actor_id): actor for actor in actors}

        for start in range(0, len(payloads), max(1, args.batch_size)):
            if tracker.calls >= args.max_calls or tracker.cost_estimate() >= args.max_cost:
                skipped.extend(item["name"] for item in payloads[start:])
                break

            batch = payloads[start:start + args.batch_size]
            response_text = call_claude(
                HAIKU,
                SYSTEM,
                build_user(batch),
                max_tokens=3500,
                tracker=tracker,
            )
            parsed = parse_json_response(response_text)
            items = (parsed or {}).get("actors", [])
            valid_ids = {item["actor_id"] for item in batch}

            for item in items:
                if not valid_update(item, valid_ids):
                    skipped.append(item.get("actor_id", "invalid"))
                    continue
                actor = actor_by_id[item["actor_id"]]
                before = {field: getattr(actor, field) for field in FIELDS}
                for field in FIELDS:
                    setattr(actor, field, item[field].strip())
                after = {field: getattr(actor, field) for field in FIELDS}
                if before != after:
                    applied.append(actor.name)
            if not args.dry_run:
                session.commit()
            else:
                session.rollback()

    print(f"dry_run={args.dry_run}")
    print(f"calls={tracker.calls}")
    print(f"failures={tracker.failures}")
    print(f"input_tokens={tracker.input_tokens}")
    print(f"output_tokens={tracker.output_tokens}")
    print(f"estimated_cost=${tracker.cost_estimate():.4f}")
    print(f"applied_rows={0 if args.dry_run else len(applied)}")
    print(f"candidate_rows={len(selected_names)}")
    print(f"skipped={len(skipped)}")
    for name in applied:
        print("APPLIED|" + name)
    for item in skipped[:20]:
        print("SKIPPED|" + str(item))


if __name__ == "__main__":
    main()
