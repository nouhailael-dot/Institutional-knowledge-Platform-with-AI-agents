"""
Phase 4 extractor — actor-type classification.

Pure logic, no database. The runner passes in the candidate type list (derived
from the actors already classified in the DB) plus an actor's name and
description. Returns a validated dict:

    {"actor_type": <one of candidate_types, or "other">,
     "confidence": <float 0.0-1.0>,
     "reasoning": <one short sentence>}

This is the lowest-risk Phase 4 task: it proposes a type for actors the
rule-based extractor could only label "other". It creates no new rows.
"""

from src.enrichment.claude_client import HAIKU, structured_json

OTHER = "other"

SYSTEM = """You classify organizations into a fixed controlled vocabulary.

You are given an organization's name, an optional description, and the list of
allowed type codes. Choose the single best-fitting code.

Rules:
- Return ONLY a code from the provided list. If none genuinely fits, return "other".
- Classify by what the organization IS (e.g. a national lab, a startup, a
  corporate R&D arm), not by what topic it works on.
- Be conservative: if the name is an unfamiliar acronym and the description is
  thin, lower your confidence rather than guessing a specific type.
- Respond with ONLY a JSON object, no prose and no markdown fences:
  {"actor_type": "<code>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}"""


def classify_actor(name: str, description: str, candidate_types: list[str],
                  model: str = HAIKU) -> dict:
    desc = (description or "").strip() or "(no description provided)"
    user = (
        f"Allowed type codes: {', '.join(candidate_types)}\n\n"
        f"Organization name: {name}\n"
        f"Description: {desc}\n\n"
        "Classify it."
    )
    out = structured_json(SYSTEM, user, model=model, max_tokens=300)

    # Validate + clamp so a bad model reply can never corrupt the DB.
    actor_type = str(out.get("actor_type", OTHER)).strip()
    if actor_type not in candidate_types and actor_type != OTHER:
        actor_type = OTHER
    try:
        confidence = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    reasoning = str(out.get("reasoning", ""))[:300]
    return {"actor_type": actor_type, "confidence": confidence, "reasoning": reasoning}