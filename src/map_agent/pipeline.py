"""Orchestrator — run the full mapping pipeline end to end.

    plan_search  ->  discover (per task)  ->  enrich (per entity)  ->  dedup

Discovery tasks run in parallel threads (each is one blocking API call chain);
enrichment runs in parallel too. Everything is gathered, deduplicated, and
grouped by entity type for the frontend.
"""

from concurrent.futures import ThreadPoolExecutor

from src.map_agent.dedup import deduplicate
from src.map_agent.discover import discover
from src.map_agent.enrich import enrich_entity
from src.map_agent.planner import _EMPTY_REQS, plan_search
from src.map_agent.select import apply_request

# These are network-bound API call chains, not CPU work, so a wider pool just
# collapses the waves. A 7-task / 58-entity run at 4 workers took >20 minutes.
MAX_WORKERS = 10


def build_map(description: str, doc_text: str | None = None,
              do_enrich: bool = False, actor_focus: str = "research",
              plan: dict | None = None) -> dict:
    """Run the full pipeline. Returns results grouped by entity type.

    `do_enrich` defaults to False: it is one agent call PER ENTITY and was the
    bulk of a >20-minute run, while only topping up fields discovery already
    found. Turn it on when completeness matters more than latency.

    `actor_focus` defaults to "research" — the planner weights the search plan
    ~80/20 toward universities, national labs, and research centers. Override
    with "both" or "companies" only for a deliberately commercial map.

    Return shape:
        {
          "tasks": [...],                      # the search plan (for transparency)
          "requirements": {...},               # what was asked for beyond the topic
          "selection_note": "...",             # why non-matching ones were left out
          "counts": {"actor": N, ...},
          "entities": {"actor": [...], "person": [...], "event": [...]},
        }
    Entities carry _selected / _rank / _why from the selection stage.
    """
    # Stage 1 — plan, unless the caller already agreed one with the user. The
    # UI plans first (and may ask questions), shows the plan, and passes it here
    # on approval — so discovery never runs on a plan nobody looked at.
    if plan is not None:
        tasks = plan.get("tasks") or []
        requirements = {**_EMPTY_REQS, **(plan.get("requirements") or {})}
    else:
        tasks, requirements = plan_search(description, doc_text,
                                          actor_focus=actor_focus)
    if not tasks:
        return {"tasks": [], "requirements": requirements, "selection_note": "",
                "counts": {}, "entities": {}}

    # Stage 2 — discover (parallel, one call chain per task)
    found: list[dict] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [
            pool.submit(discover, t["query"], t["entity_type"], t.get("focus", ""))
            for t in tasks
        ]
        for fut in futures:
            try:
                found.extend(fut.result())
            except Exception as e:
                # Collected, not just printed: a failed search and a search that
                # legitimately found nothing look identical downstream otherwise.
                failures.append(str(e))
                print(f"[pipeline] discover task failed: {e}")

    if not found:
        return {"tasks": tasks, "requirements": requirements, "selection_note": "",
                "failures": failures, "counts": {}, "entities": {}}

    # Stage 3 — enrich (parallel, one call chain per entity)
    if do_enrich:
        enriched: list[dict] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(enrich_entity, e) for e in found]
            for fut in futures:
                try:
                    enriched.append(fut.result())
                except Exception as e:
                    print(f"[pipeline] enrich failed: {e}")
        found = enriched

    # Stage 4 — deduplicate
    merged = deduplicate(found)

    # Stage 5 — enforce the request. The only point where the whole candidate
    # set and the original wording exist together. Annotates in place; nothing
    # is dropped, so the caller can still show what was excluded.
    sel = apply_request(merged, description, requirements, doc_text)
    merged = sel["selected"] + sel["rest"]          # best first, rest after

    # Group by entity type
    grouped: dict[str, list[dict]] = {"actor": [], "person": [], "event": []}
    for e in merged:
        et = e.get("_entity_type", "actor")
        grouped.setdefault(et, []).append(e)

    counts = {k: len(v) for k, v in grouped.items() if v}
    return {"tasks": tasks, "requirements": requirements,
            "selection_note": sel["note"], "failures": failures,
            "counts": counts, "entities": grouped}
