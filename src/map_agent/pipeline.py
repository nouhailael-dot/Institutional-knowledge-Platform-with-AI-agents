"""Orchestrator — run the full mapping pipeline end to end.

    plan_search  ->  discover (per task)  ->  enrich (per entity)  ->  dedup

Discovery tasks run in parallel threads (each is one blocking API call chain);
enrichment runs in parallel too. Everything is gathered, deduplicated, and
grouped by entity type for the frontend.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy

from src.map_agent.dedup import deduplicate
from src.map_agent.discover import discover
from src.map_agent.enrich import enrich_entity
from src.map_agent.planner import _EMPTY_REQS, _bounded_tasks, plan_search
from src.map_agent.relationships import link_people_to_actors
from src.map_agent.select import apply_request
from src.map_agent.run_store import MapStopped

# These are network-bound API call chains, not CPU work, so a wider pool just
# collapses the waves. A 7-task / 58-entity run at 4 workers took >20 minutes.
MAX_WORKERS = 10


def build_map(description: str, doc_text: str | None = None,
              do_enrich: bool = False, actor_focus: str = "research",
              plan: dict | None = None, run=None) -> dict:
    """Active API uses only the resumable controlled workflow."""
    from src.map_agent.research import build_controlled_map
    if do_enrich:
        raise ValueError("Per-entity autonomous enrichment is disabled; use the controlled evidence workflow.")
    return build_controlled_map(description, plan, run)


def build_map_legacy(description: str, doc_text: str | None = None,
                     do_enrich: bool = False, actor_focus: str = "research",
                     plan: dict | None = None, run=None) -> dict:
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
        # Never trust a browser-supplied or stale plan to respect paid-search
        # limits. Enforce the same ceiling again at the execution boundary.
        tasks = _bounded_tasks(plan.get("tasks") or [])
        requirements = {**_EMPTY_REQS, **(plan.get("requirements") or {})}
    else:
        tasks, requirements = plan_search(description, doc_text,
                                          actor_focus=actor_focus, run=run)
    if not tasks:
        return {"tasks": [], "requirements": requirements, "selection_note": "",
                "counts": {}, "entities": {}}

    # Stage 2 — discover (parallel, one call chain per task)
    found: list[dict] = []
    failures: list[str] = []

    def checkpoint(stage):
        if run:
            grouped = {"actor": [], "person": [], "event": []}
            for entity in link_people_to_actors(deduplicate(deepcopy(found))):
                grouped.setdefault(entity.get("_entity_type", "actor"), []).append(entity)
            run.checkpoint({"tasks": tasks, "requirements": requirements,
                            "selection_note": "Partial results; selection has not completed.",
                            "failures": list(failures), "partial": True,
                            "counts": {k: len(v) for k, v in grouped.items()}, "entities": grouped})

    checkpoint("Discovery")
    stopped = None
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [
            pool.submit(discover, t["query"], t["entity_type"], t.get("focus", ""), run=run)
            for t in tasks
        ]
        for fut in as_completed(futures):
            try:
                found.extend(fut.result())
            except MapStopped as exc:
                stopped = exc
            except Exception as e:
                # Collected, not just printed: a failed search and a search that
                # legitimately found nothing look identical downstream otherwise.
                failures.append(str(e))
                print(f"[pipeline] discover task failed: {e}")
            checkpoint("Discovery")

    if stopped:
        raise stopped
    if run:
        run.check()

    if not found:
        return {"tasks": tasks, "requirements": requirements, "selection_note": "",
                "failures": failures, "counts": {}, "entities": {}}

    # Stage 3 — enrich (parallel, one call chain per entity)
    if do_enrich:
        enriched: list[dict] = list(found)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(enrich_entity, e, run=run): i for i, e in enumerate(found)}
            for fut in as_completed(futures):
                try:
                    enriched[futures[fut]] = fut.result()
                except MapStopped as exc:
                    stopped = exc
                except Exception as e:
                    print(f"[pipeline] enrich failed: {e}")
                found = list(enriched)
                checkpoint("Enrichment")
        found = enriched
        if stopped:
            raise stopped
    if run:
        run.check()

    # Stage 4 — deduplicate
    merged = deduplicate(found)

    # People are discovered with their organizations. Normalize duplicates and
    # affiliations, then attach each person to every actor they belong to. Keep
    # the top-level people collection for API/export compatibility.
    merged = link_people_to_actors(merged)

    # Stage 5 — enforce the request. The only point where the whole candidate
    # set and the original wording exist together. Annotates in place; nothing
    # is dropped, so the caller can still show what was excluded.
    people = [e for e in merged if e.get("_entity_type") == "person"]
    candidates = [e for e in merged if e.get("_entity_type") != "person"]
    sel = apply_request(candidates, description, requirements, doc_text, run=run)

    # A person follows the selection state of the organization(s) they belong
    # to. They do not compete with organizations for a requested result limit.
    selected_actor_names = {
        (e.get("name") or "").strip().lower() for e in sel["selected"]
        if e.get("_entity_type") == "actor"
    }
    for person in people:
        org_names = {
            (x.get("actor_name") or "").strip().lower()
            for x in person.get("organizations") or []
        }
        person["_selected"] = bool(org_names & selected_actor_names)
        person["_rank"] = None
        person["_why"] = None

    merged = sel["selected"] + sel["rest"] + people  # best first, rest after

    # Group by entity type
    grouped: dict[str, list[dict]] = {"actor": [], "person": [], "event": []}
    for e in merged:
        et = e.get("_entity_type", "actor")
        grouped.setdefault(et, []).append(e)

    counts = {k: len(v) for k, v in grouped.items() if v}
    return {"tasks": tasks, "requirements": requirements,
            "selection_note": sel["note"], "failures": failures,
            "counts": counts, "entities": grouped}
