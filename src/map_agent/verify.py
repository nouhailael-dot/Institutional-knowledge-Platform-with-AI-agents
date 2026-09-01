"""Phase 2 orchestrator — run the verification layers over discovered entities.

    urlcheck (Layer 2)  ->  judge (Layer 3)  ->  floor (Layer 5)

Runs ON DEMAND, after the user has already seen the fast phase-1 results. The
order is deliberate: the free deterministic link check runs first and its
verdict is handed to the judge, so a dead-link entity is judged with that fact
in view rather than scored blind.

Entities are annotated in place. The keys added are:
    _link_check, _links_ok   (Layer 2)
    _judge                   (Layer 3)
    _below_floor             (Layer 5)
"""

from src.map_agent.floor import DEFAULT_THRESHOLD, apply_relevance_floor, partition
from src.map_agent.judge import judge_entities
from src.map_agent.urlcheck import verify_links


def verify(entities: list[dict], request: str,
           threshold: float = DEFAULT_THRESHOLD,
           check_links: bool = True,
           run_judge: bool = True) -> list[dict]:
    """Run the verification layers over `entities` (mutates in place).

    `request` is the user's ORIGINAL map description — the judge grades each
    entity against it, so it must be the real request, not a search query.

    The flags let a caller run a cheaper subset (e.g. links only, no LLM cost).
    """
    if not entities:
        return entities

    if check_links:
        verify_links(entities)

    if run_judge:
        judge_entities(entities, request)

    # Floor depends on judge scores; unjudged entities are left unflagged.
    apply_relevance_floor(entities, threshold)
    return entities


def verify_one(entity: dict, request: str,
               threshold: float = DEFAULT_THRESHOLD,
               check_links: bool = True,
               run_judge: bool = True) -> dict:
    """Verify a single entity — the 'verify this card' path."""
    verify([entity], request, threshold, check_links, run_judge)
    return entity


def verify_and_split(entities: list[dict], request: str,
                     threshold: float = DEFAULT_THRESHOLD,
                     check_links: bool = True,
                     run_judge: bool = True) -> tuple[list[dict], list[dict]]:
    """Verify, then split into (kept, weak) for a UI that separates them.

    Unjudged entities stay in `kept` — you can't floor what wasn't scored.
    """
    verify(entities, request, threshold, check_links, run_judge)
    return partition(entities, threshold)


def summarize(entities: list[dict]) -> dict:
    """Small counts dict for the UI/API: how did verification go?"""
    judged = [e for e in entities if (e.get("_judge") or {}).get("relevance_score") is not None]
    scores = [e["_judge"]["relevance_score"] for e in judged]
    return {
        "total": len(entities),
        "judged": len(judged),
        "strong": sum(1 for e in entities if e.get("_below_floor") is False),
        "weak": sum(1 for e in entities if e.get("_below_floor") is True),
        "dead_links": sum(1 for e in entities if e.get("_links_ok") is False),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
    }
