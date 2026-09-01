"""Layer 5 — Relevance floor. Pure Python, no cost.

Uses the judge's score (Layer 3) to separate strong matches from weak ones so
the map isn't padded with low-relevance entities. Deliberately does NOT delete:
it flags entities below the threshold so the UI can show them apart ("weaker
matches") rather than hiding them — the user still decides.

Entities that were never judged (verify not run on them) are left unflagged;
you can't floor what hasn't been scored.
"""

DEFAULT_THRESHOLD = 0.5


def apply_relevance_floor(entities: list[dict],
                          threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Annotate each entity with '_below_floor' (mutates in place).

    _below_floor = True  -> judged, score < threshold (weak match)
    _below_floor = False -> judged, score >= threshold (strong match)
    _below_floor = None  -> not judged yet (unknown)
    """
    for e in entities:
        judge = e.get("_judge") or {}
        score = judge.get("relevance_score")
        if score is None:
            e["_below_floor"] = None
        else:
            e["_below_floor"] = score < threshold
    return entities


def partition(entities: list[dict],
              threshold: float = DEFAULT_THRESHOLD) -> tuple[list[dict], list[dict]]:
    """Split into (kept, weak). Unjudged entities stay in 'kept'.

    kept = strong matches + not-yet-judged; weak = judged below the floor.
    """
    apply_relevance_floor(entities, threshold)
    kept = [e for e in entities if e.get("_below_floor") is not True]
    weak = [e for e in entities if e.get("_below_floor") is True]
    return kept, weak
