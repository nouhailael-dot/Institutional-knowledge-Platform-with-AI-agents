"""FastAPI layer over the existing RAG engine (src/).

This does NOT reimplement anything — it wraps the same functions app.py calls,
so the React frontend gets identical behavior: SQL-vs-semantic routing, streamed
cited answers, and the Browse data. Run from the repo root:

    uvicorn backend.app:app --reload --port 8000

The engine stays UI-agnostic; swapping or redesigning the frontend never touches
retrieve / generate / router / browse.
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # make `src` importable no matter the CWD

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import browse
from src.db import get_readonly_connection
from src.documents.doc_store import build_store, search_chunks
from src.documents.extract import ExtractionError, extract_text
from src.generate import condense_question, map_prompt_from_conversation, stream_answer
from src.map_agent.export import to_pptx, to_xlsx
from src.map_agent.pipeline import build_map
from src.map_agent.people_research import research_people
from src.map_agent.planner import map_chat
from src.map_agent.verify import summarize, verify
from src.map_agent.run_store import RunStore, RunContext, MapStopped
from src.map_agent.search_backend import availability as research_availability
from src.retrieve import retrieve
from src.discovery.bridge import DiscoveryBridge, DiscoveryBridgeError
from src.review.store import register_sector_codes
from src.review import (AdmissionBridge, AdmissionBridgeError, DuplicateRisk, PostgresReviewSource,
                        PostgresReviewSourceError, ReadOnlyRunStore,
                        ReviewConflict, ReviewNotConfigured, ReviewStore,
                        ReviewValidationError, TaxonomyError, catalog_payload)
from src.router import format_sql_answer, plan, run_sql

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def map_store():
    return RunStore()


def _local_review_demo_enabled() -> bool:
    """Allow approvals only in the explicitly isolated local demo database."""
    if os.environ.get("REVIEW_DEMO_MODE", "").strip() != "1":
        return False
    if os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("Review demo mode refuses to run while DATABASE_URL is configured.")
    configured = os.environ.get("REVIEW_STORE_DB", "").strip()
    if not configured:
        raise RuntimeError("Review demo mode requires REVIEW_STORE_DB inside the project .demo folder.")
    store_path = Path(configured).expanduser().resolve()
    demo_root = (ROOT / ".demo").resolve()
    if demo_root not in store_path.parents:
        raise RuntimeError("Review demo mode is restricted to the project .demo folder.")
    return True


@lru_cache(maxsize=1)
def review_store():
    return ReviewStore(enable_test_canonical=_local_review_demo_enabled())


def review_source_store():
    """Optional second result source; it is never recovered or opened writable."""
    configured = os.environ.get("REVIEW_SOURCE_RUN_DB", "").strip()
    return ReadOnlyRunStore(configured) if configured else None


def review_postgres_source():
    """Optional original-platform discovery source, always opened read-only."""
    if os.environ.get("REVIEW_DEMO_MODE", "").strip() == "1":
        return None
    return PostgresReviewSource.from_environment()


@lru_cache(maxsize=1)
def review_admission_bridge():
    return AdmissionBridge()


@lru_cache(maxsize=1)
def discovery_bridge():
    return DiscoveryBridge()


@asynccontextmanager
async def lifespan(app):
    map_store().recover()
    # The review store is the only place that knows a pre-promotion candidate
    # was decided. If it is configured somewhere a redeploy wipes, every
    # rejection quietly becomes pending again and the queue refills with work a
    # reviewer already refused. Say so at startup rather than discovering it.
    try:
        for warning in review_store().persistence_warnings():
            logger.warning("Review persistence: %s", warning)
    except Exception:
        logger.exception("Could not check review-store persistence")
    yield


app = FastAPI(title="UM6P Intelligence API", lifespan=lifespan)


@app.middleware("http")
async def revalidate_frontend_assets(request, call_next):
    """Browsers must re-check the page's scripts and styles on every load.

    Module scripts were being served from the browser cache after an update, so
    a reviewer kept seeing the previous screen. "no-cache" still lets the
    browser reuse an unchanged file (304); it only forbids skipping the check.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response
FRONTEND = ROOT / "frontend"


# --- read-only data loads, cached in-process (the whole live set is <1000 rows).
# lru_cache keeps Browse snappy; restart the server to pick up source-data edits.
@lru_cache(maxsize=1)
def _actors():
    return browse.load_actors()


@lru_cache(maxsize=1)
def _hubs():
    return browse.load_hubs()


@lru_cache(maxsize=1)
def _events():
    return browse.load_events()


# ---------------------------------------------------------------- Doc upload
# The stateless API replaces Streamlit's st.session_state: an uploaded doc is
# embedded once and its in-memory store is held here, keyed by a returned id.
# Nothing is written to Postgres (same as the Streamlit version). Capped so the
# process can't grow unbounded; oldest evict first.
_DOC_STORES: dict[str, dict] = {}
_DOC_CAP = 24


def _evict_docs():
    while len(_DOC_STORES) > _DOC_CAP:
        oldest = min(_DOC_STORES, key=lambda k: _DOC_STORES[k]["ts"])
        _DOC_STORES.pop(oldest, None)


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    """Extract + embed a doc; return an id the Ask stream can attach. No DB write."""
    data = file.file.read()                       # sync read -> FastAPI threadpools this
    try:
        text = extract_text(data, file.filename)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store = build_store(text, file.filename)
    doc_id = uuid4().hex
    # `text` is kept alongside the embedded store: Ask searches the store, but the
    # map planner needs the raw excerpt as prompt context.
    _DOC_STORES[doc_id] = {"store": store, "text": text, "name": file.filename,
                           "ts": time.time()}
    _evict_docs()
    return {"doc_id": doc_id, "name": file.filename}


# ---------------------------------------------------------------- Ask (streamed)
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _sources(hits: list[dict]) -> list[dict]:
    out = []
    for h in hits:
        text = h.get("doc_text") or ""
        out.append({
            "name": h["name"],
            "entity_type": h["entity_type"],
            "preview": text[:300] + ("…" if len(text) > 300 else ""),
        })
    return out


@app.get("/api/ask/stream")
def ask_stream(question: str = Query(..., min_length=1),
               doc_id: str | None = Query(None),
               history: str | None = Query(None)):
    """Server-Sent Events: `meta` (route + sources/sql + rewritten), then `delta`*, `done`.

    Multi-turn: `history` is a JSON list of prior turns [{"q":..,"a":..}, ...]. When
    present, the follow-up is condensed into a standalone question (cheap model)
    before routing/retrieval, so "which of those are in Florida?" resolves against
    the previous answer instead of being searched literally. `meta.rewritten`
    carries the standalone form when it differs (shown in the UI for transparency).
    """
    def gen():
        q = question.strip()
        if not q:
            yield _sse("done", {}); return

        turns = []
        if history:
            try:
                turns = json.loads(history)
            except Exception:
                turns = []
        standalone = condense_question(turns, q) if turns else q
        rewritten = standalone if standalone.strip().lower() != q.lower() else None

        # Document attached -> merge doc chunks + map hits into one cited answer.
        doc = _DOC_STORES.get(doc_id) if doc_id else None
        if doc is not None:
            merged = search_chunks(doc["store"], standalone) + retrieve(standalone, top_k=8)
            yield _sse("meta", {"mode": "doc", "sources": _sources(merged), "rewritten": rewritten})
            if merged:
                for chunk in stream_answer(standalone, merged):
                    yield _sse("delta", {"text": chunk})
            yield _sse("done", {})
            return

        mode, sql = plan(standalone)
        if mode == "sql":
            try:
                cols, rows = run_sql(sql)
                answer = format_sql_answer(standalone, sql, cols, rows)
                yield _sse("meta", {"mode": "sql", "sql": sql, "rewritten": rewritten})
                yield _sse("delta", {"text": answer})
                yield _sse("done", {})
                return
            except Exception:
                mode = "semantic"      # fall back to map search, same as the UI

        hits = retrieve(standalone)
        yield _sse("meta", {"mode": "semantic", "sources": _sources(hits), "rewritten": rewritten})
        if hits:
            for chunk in stream_answer(standalone, hits):
                yield _sse("delta", {"text": chunk})
        yield _sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


class MapPromptRequest(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/ask/map-prompt")
def ask_map_prompt(payload: MapPromptRequest):
    """Compose a Build a Map description from an Ask conversation.

    Called when the user clicks, never speculatively on every answer. Spends
    nothing from a map budget — this is Ask-side, like the answer itself.
    """
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Ask a question first.")
    try:
        return map_prompt_from_conversation(payload.history, payload.question)
    except Exception:
        raise HTTPException(status_code=502,
                            detail="Could not prepare the map description. Open Build the Map and describe it yourself.")


# ---------------------------------------------------------------- Browse (JSON)
# --- sector is DERIVED, not stored: actor_sector is empty, but hubs carry
# `primary_sectors`. So an actor's sectors = the sectors of the hubs it's in.
# Approximate (hub-level), but it's the only sector signal the data supports.
@lru_cache(maxsize=1)
def _sector_code_to_name() -> dict:
    with get_readonly_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT code, name FROM sector")
        return {code: name for code, name in cur.fetchall()}


@lru_cache(maxsize=1)
def _sectors_by_hub() -> dict:
    names = _sector_code_to_name()
    out = {}
    for h in _hubs():                                   # primary_sectors is "AGRI, WATER"
        codes = [c.strip() for c in (h.get("primary_sectors") or "").split(",") if c.strip()]
        out[h["name"]] = [names.get(c, c) for c in codes]
    return out


@app.get("/api/browse/actors")
def browse_actors():
    by_hub = _sectors_by_hub()
    all_sectors = set()
    enriched = []
    for a in _actors():
        secs = sorted({s for hub in a["hubs"] for s in by_hub.get(hub, [])})
        all_sectors.update(secs)
        enriched.append({**a, "sectors": secs})
    options = browse.actor_filter_options(_actors())
    options["sectors"] = sorted(all_sectors)
    return JSONResponse(jsonable_encoder({"actors": enriched, "options": options}))


@app.get("/api/browse/hubs")
def browse_hubs():
    return JSONResponse(jsonable_encoder(
        {"hubs": _hubs(), "columns": browse.hub_columns()}))


@app.get("/api/browse/events")
def browse_events():
    evts = _events()
    types = sorted({e["event_type"] for e in evts if e.get("event_type")})
    return JSONResponse(jsonable_encoder({"events": evts, "event_types": types}))


# ---------------------------------------------------------------- Build the Map
# Phase 1 (discovery) takes minutes, so it can't be one blocking request: POST
# /api/map starts a job and returns an id, the frontend polls GET /api/map/{id}.
# Phase 2 (verification) is on demand and fast enough to answer inline, and is
# stateless — the frontend posts back the entities it already holds.
#
# Maps and usage persist locally, independently of the production actor DB.
_MAP_POOL = ThreadPoolExecutor(max_workers=2)   # a map is expensive; don't fan out


def map_record(job_id):
    try:
        return map_store().get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown map session.")


def public_map(job_id):
    record = map_record(job_id)
    return {k: record[k] for k in ("id", "status", "stage", "description", "result", "error",
                                   "cost", "messages", "plan", "created", "updated")}


@app.post("/api/map/session")
def map_session():
    return {"job_id": map_store().create()}


@app.get("/api/maps")
def maps_recent():
    enabled, reason = research_availability()
    return {"maps": map_store().recent(), "research_available": enabled, "research_disabled_reason": reason}


def require_research():
    enabled, reason = research_availability()
    if not enabled:
        raise HTTPException(status_code=503, detail=reason)


def people_actor(job_id, name, website):
    record = map_record(job_id)
    actors = (record.get("result") or {}).get("entities", {}).get("actor", [])
    matches = [a for a in actors if a.get("name") == name and (a.get("website") or "") == website]
    if len(matches) != 1:
        raise HTTPException(status_code=400, detail="Choose one organization from the saved map.")
    return record, matches[0], json.dumps([name, website])


class PeopleRequest(BaseModel):
    actor_name: str
    website: str = ""
    criteria: str
    request_key: str
    approve: bool = False


@app.get("/api/map/{job_id}/people")
def people_history(job_id: str, actor_name: str, website: str = ""):
    _, _, key = people_actor(job_id, actor_name, website)
    return {"tasks": [public_map(r["id"]) for r in map_store().people_tasks(job_id, key)]}


def _run_people_job(task_id, actor, topic, criteria):
    context = RunContext(map_store(), task_id)
    try:
        result = research_people(context, actor, topic, criteria)
        if result.get("extraction_errors"):
            map_store().finish(task_id, "error", "People search incomplete: " + "; ".join(result["extraction_errors"]), attempt=context.attempt)
        else:
            map_store().finish(task_id, attempt=context.attempt)
    except Exception as exc:
        map_store().finish(task_id, "error", str(exc), attempt=context.attempt)


@app.post("/api/map/{job_id}/people")
def start_people_search(job_id: str, payload: PeopleRequest):
    require_research()
    if payload.approve is not True:
        raise HTTPException(status_code=400, detail="Approve the separate $3 estimated allowance first.")
    criteria = payload.criteria.strip()
    if not criteria or len(criteria) > 2000 or not 1 <= len(payload.request_key) <= 100:
        raise HTTPException(status_code=400, detail="Provide criteria (up to 2,000 characters) and a request key.")
    record, actor, key = people_actor(job_id, payload.actor_name, payload.website)
    if record["status"] in ("running", "planning", "verifying"):
        raise HTTPException(status_code=409, detail="Wait for the institutional map to finish first.")
    try:
        task_id, created = map_store().create_people_task(job_id, key, payload.request_key,
            f"People at {actor['name']}: {criteria}",
            {"kind": "people", "parent_id": job_id, "actor": actor, "criteria": criteria})
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if created:
        try:
            _MAP_POOL.submit(_run_people_job, task_id, actor, record["description"], criteria)
        except Exception:
            map_store().finish(task_id, "error", "Worker could not start; no research dispatched.")
            raise HTTPException(status_code=503, detail="Could not start people search.")
    return public_map(task_id)


@app.post("/api/map/upload")
def map_upload(job_id: str = Form(...), file: UploadFile = File(...)):
    record = map_record(job_id)
    if record["status"] not in ("draft", "awaiting_reply"):
        raise HTTPException(status_code=409, detail="This map cannot accept a new document.")
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Please use a document smaller than 10 MB.")
    try:
        text = extract_text(data, file.filename)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Build the Map only needs text; do not buy Ask embeddings for this upload.
    map_store().update(job_id, doc_text=text[:6000])
    return {"job_id": job_id, "name": file.filename}


class ChatRequest(BaseModel):
    """One turn of the map-planning conversation. `messages` is the whole thread
    as plain {role, content} turns; `doc_id` refers to an /api/upload document."""
    messages: list[dict]
    doc_id: str | None = None
    job_id: str | None = None


@app.post("/api/map/chat")
def map_chat_turn(payload: ChatRequest):
    """Talk with the planner until it has enough to search.

    Returns {"status": "reply"|"plan"|"error", ...}. On "reply" the agent is
    asking something — show it and send the user's answer back with the thread.
    On "plan" it has decided: the caller starts POST /api/map with that plan.
    """
    require_research()
    if not payload.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    description = "\n".join(str(m.get("content", "")) for m in payload.messages if m.get("role") == "user")
    job_id = payload.job_id or map_store().create(description)
    record = map_record(job_id)
    try:
        map_store().claim(job_id, "planning", "Planning", ("draft", "awaiting_reply"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    doc = _DOC_STORES.get(payload.doc_id) if payload.doc_id else None
    text = record["doc_text"] or (doc["text"][:6000] if doc else None)
    map_store().update(job_id, description=description, messages=payload.messages, doc_text=text)
    try:
        result = map_chat(payload.messages, text, run=RunContext(map_store(), job_id))
        messages = list(payload.messages)
        if result.get("status") in ("reply", "plan"):
            messages.append({"role": "assistant", "content": result.get("message") or result.get("summary", "")})
        fields = {"messages": messages}
        if result.get("status") == "plan":
            fields["plan"] = result
        map_store().update(job_id, **fields)
        state = {"plan": "ready", "reply": "awaiting_reply"}.get(result.get("status"), "error")
        map_store().finish(job_id, state, result.get("message") if state == "error" else None)
    except Exception as exc:
        map_store().finish(job_id, "error", str(exc))
        result = {"status": "error", "message": str(exc)}
    record = map_record(job_id)
    if record["cancelled"]:
        result = {"status": "error", "message": record["error"] or "Map stopped."}
    return {**result, "job_id": job_id, "cost": record["cost"]}


def _run_map_job(job_id: str, description: str, plan: dict | None, attempt=None):
    """Worker body: run the pipeline, park the result on the job record."""
    context = RunContext(map_store(), job_id, attempt=attempt)
    try:
        context.check()
        result = build_map(description, plan=plan, run=context)
        context.checkpoint(result)
        map_store().finish(job_id, attempt=context.attempt)
    except Exception as exc:
        map_store().finish(job_id, "error", str(exc), attempt=context.attempt)


class MapRequest(BaseModel):
    """Start a saved plan. Legacy request fields remain for older clients."""
    description: str
    plan: dict | None = None          # fallback when the session has no saved plan
    doc_id: str | None = None
    enrich: bool = False             # compatibility only; True is rejected
    actor_focus: str = "research"    # compatibility only; focus is resolved in planning
    job_id: str | None = None


@app.post("/api/map")
def map_start(payload: MapRequest):
    """Start a map build. Returns {job_id}; poll GET /api/map/{job_id}.

    The conversational planner supplies the plan. This endpoint never silently
    replans, and the session's saved plan takes precedence over a supplied plan.
    """
    require_research()
    if payload.enrich:
        raise HTTPException(status_code=400, detail="Autonomous enrichment is disabled.")
    desc = (payload.description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")

    doc = _DOC_STORES.get(payload.doc_id) if payload.doc_id else None
    doc_text = doc["text"] if doc else None

    job_id = payload.job_id or map_store().create(desc)
    record = map_record(job_id)
    if not (record["plan"] or payload.plan or {}).get("tasks"):
        raise HTTPException(status_code=400, detail="A search plan is required before research.")
    try:
        map_store().claim(job_id, "running", "Preparing research", ("draft", "ready"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    doc_text = record["doc_text"] or doc_text
    approved_plan = record["plan"] or payload.plan
    map_store().update(job_id, description=desc, doc_text=doc_text, plan=approved_plan)
    _MAP_POOL.submit(_run_map_job, job_id, desc, approved_plan, map_record(job_id)["attempt"])
    return {"job_id": job_id, "status": "running"}


@app.get("/api/map/{job_id}")
def map_status(job_id: str):
    """Poll a map job. status is running | done | error; result present when done."""
    return public_map(job_id)


@app.post("/api/map/{job_id}/stop")
def map_stop(job_id: str):
    map_record(job_id)
    map_store().stop(job_id)
    return public_map(job_id)


class BudgetExtensionRequest(BaseModel):
    approve: bool = False


@app.post("/api/map/{job_id}/budget-extension")
def map_budget_extension(job_id: str, payload: BudgetExtensionRequest):
    map_record(job_id)
    if payload.approve is not True:
        raise HTTPException(status_code=400, detail="Explicit approval is required to raise the total budget to $3.")
    try:
        map_store().approve_extension(job_id)
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return public_map(job_id)


@app.post("/api/map/{job_id}/resume")
def map_resume(job_id: str, payload: BudgetExtensionRequest):
    require_research()
    if payload.approve is not True:
        raise HTTPException(status_code=400, detail="Explicit approval is required to continue paid research.")
    record = map_record(job_id)
    try:
        map_store().resume(job_id)
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        _MAP_POOL.submit(_run_map_job, job_id, record["description"],
                         record["plan"], map_record(job_id)["attempt"])
    except Exception:
        map_store().finish(job_id, "error", "Could not start the worker; no new API request was made.")
        raise HTTPException(status_code=503, detail="Could not start the worker.")
    return public_map(job_id)


class VerifyRequest(BaseModel):
    """Phase-2 payload. `entities` are the ones the frontend already holds, and
    `request` must be the ORIGINAL map description — the judge grades against it."""
    entities: list[dict]
    request: str
    check_links: bool = True
    run_judge: bool = True
    job_id: str | None = None


@app.post("/api/map/verify")
def map_verify(payload: VerifyRequest):
    """Run the verification layers (link check -> judge -> relevance floor).

    Works for one entity or all of them — the frontend decides what to send.
    Returns the annotated entities plus summary counts.
    """
    if not payload.entities:
        return {"entities": [], "summary": summarize([])}
    if not payload.job_id:
        raise HTTPException(status_code=400, detail="Open a saved map before verifying so its budget is tracked.")
    record = map_record(payload.job_id)
    try:
        map_store().claim(payload.job_id, "verifying", "Verification", ("done", "error"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    context = RunContext(map_store(), payload.job_id)
    entities = payload.entities
    error = None
    try:
        verify(entities, record["description"], check_links=payload.check_links,
               run_judge=payload.run_judge, run=context)
    except Exception as exc:
        error = str(exc)
    # Preserve even a partially completed verification batch.
    saved = map_record(payload.job_id)["result"] or {"entities": {}}
    for entity in entities:
        group = saved.setdefault("entities", {}).setdefault(entity.get("_entity_type", "actor"), [])
        name = entity.get("name") or entity.get("full_name")
        for index, old in enumerate(group):
            if (old.get("name") or old.get("full_name")) == name:
                group[index] = entity
                break
    context.checkpoint(saved)
    map_store().finish(payload.job_id, "error" if error else "done", error)
    return {"entities": entities, "summary": summarize(entities), "error": error,
            "cost": map_record(payload.job_id)["cost"]}


class ExportRequest(BaseModel):
    """Export the map the frontend currently holds (so it reflects any
    verification the user ran). `result` is the pipeline result object;
    `fmt` is 'xlsx' or 'pptx'."""
    result: dict
    request: str = ""
    fmt: str = "xlsx"


_EXPORT = {
    "xlsx": (to_xlsx, "map.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pptx": (to_pptx, "map.pptx",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}


@app.post("/api/map/export")
def map_export(payload: ExportRequest):
    """Return the map as a downloadable .xlsx or .pptx (selected entities only)."""
    spec = _EXPORT.get(payload.fmt)
    if spec is None:
        raise HTTPException(status_code=400, detail="fmt must be 'xlsx' or 'pptx'")
    render, filename, media = spec
    data = render(payload.result, payload.request)
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------- Human review
_review_sync_lock = Lock()
_review_sync_last = 0.0
_review_sync_warnings = []
_review_sync_store_key = None
REVIEW_SYNC_INTERVAL_SECONDS = 120


# The headline lives in the UI label; this is the explanation beneath it.
DEMO_BANNER = (
    "This instance reads an isolated demonstration database. Nothing shown here "
    "is a GHUS record, and no decision taken here reaches production."
)


def _demo_banner() -> str | None:
    """One unmissable line when this instance serves demonstration data.

    Set GHUS_DEMO_MODE=1 only on a demo instance pointed at an isolated test
    database. It changes nothing except that every Review response says plainly
    what it is looking at, so a demo can never be mistaken for the real queue.
    It is deliberately NOT a sync warning: a warning is something that went
    wrong, and this is a statement about which data is on screen.
    """

    return DEMO_BANNER if os.environ.get("GHUS_DEMO_MODE", "").strip() == "1" else None


def _sync_review_candidates(*, force: bool = False):
    global _review_sync_last, _review_sync_warnings, _review_sync_store_key
    target = review_store()
    store_key = str(target.path.resolve())
    now = time.monotonic()
    if (not force and _review_sync_store_key == store_key
            and now - _review_sync_last < REVIEW_SYNC_INTERVAL_SECONDS):
        return list(_review_sync_warnings)
    with _review_sync_lock:
        now = time.monotonic()
        if (not force and _review_sync_store_key == store_key
                and now - _review_sync_last < REVIEW_SYNC_INTERVAL_SECONDS):
            return list(_review_sync_warnings)
        warnings = []
        try:
            local = map_store()
            target.sync_run_store(local)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Review storage is unavailable. Check the local review-store configuration.",
            ) from exc

        try:
            external = review_source_store()
            if (external is not None and external.exists()
                    and external.path.resolve() != local.path.resolve()):
                target.sync_run_store(external)
        except Exception:
            logger.exception("Optional SQLite review source synchronization failed")
            warnings.append("The optional SQLite review source could not be synchronized.")

        try:
            postgres = review_postgres_source()
            if postgres is not None:
                candidates, source_warnings = postgres.fetch_candidates()
                target.sync_external_candidates(candidates)
                warnings.extend(source_warnings)
                target.set_sync_state("postgresql", success=not source_warnings,
                                      error="; ".join(source_warnings) or None)
        except PostgresReviewSourceError as exc:
            logger.warning("PostgreSQL review source unavailable: %s", exc)
            warnings.append(str(exc))
            target.set_sync_state("postgresql", success=False, error=str(exc))
        except Exception:
            logger.exception("PostgreSQL review source synchronization failed")
            warning = "The PostgreSQL review source could not be synchronized."
            warnings.append(warning)
            target.set_sync_state("postgresql", success=False, error=warning)
        _review_sync_last = time.monotonic()
        _review_sync_store_key = store_key
        _review_sync_warnings = list(warnings)
        return warnings


def _raise_review_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail="Unknown review candidate.") from exc
    if isinstance(exc, DuplicateRisk):
        duplicates = [
            {"entity_id": row.get("entity_id"), "name": row.get("name"),
             "website": row.get("website")}
            for row in exc.matches
        ]
        raise HTTPException(status_code=409, detail={
            "message": str(exc), "duplicates": duplicates,
        }) from exc
    if isinstance(exc, ReviewConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (ReviewValidationError, TaxonomyError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ReviewNotConfigured):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, AdmissionBridgeError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(
        status_code=500,
        detail="The review operation failed without changing the candidate.",
    ) from exc


class ReviewUpdateRequest(BaseModel):
    fields: dict


class ReviewDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=5000)
    edited_payload: dict | None = None


class ReviewRejectionRequest(ReviewDecisionRequest):
    rejection_reason: str = Field(min_length=1, max_length=5000)


class ReviewAdmissionRequest(ReviewDecisionRequest):
    decision_kind: str
    target_id: str | None = None
    hub_ids: list[str] = Field(default_factory=list)
    proposed_hub: dict | None = None
    rejection_reason: str | None = None
    rejection_reason_other: str | None = Field(default=None, max_length=5000)


@app.get("/api/review/catalog")
def review_catalog():
    """The controlled vocabularies the Review screen may offer.

    Served from one place so no dropdown can drift from the Intern Guide
    catalog, and so an invalid category/type pair cannot be constructed in the
    browser at all.
    """
    return catalog_payload()


@app.get("/api/review/subscriptions")
def review_subscriptions():
    """Actor update subscriptions and their runs (WS6), read-only.

    Empty when no PostgreSQL source is configured or migration 540 has not been
    applied. Nothing can be created or changed through this endpoint: a
    subscription is a GHUS request, and until the scheduler contract is built
    the Review screen only reports what exists.
    """
    source = review_postgres_source()
    if source is None:
        return {"subscriptions": [], "configured": False}
    try:
        return {"subscriptions": source.fetch_subscriptions(), "configured": True}
    except PostgresReviewSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _raise_review_error(exc)


class SectorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    reviewer: str = Field(min_length=1, max_length=120)


def _fallback_sectors() -> list[dict]:
    from src.review.taxonomy import NON_THEMATIC_SECTORS, THEMATIC_SECTORS

    return [{"code": c, "name": n, "is_thematic": True} for c, n in THEMATIC_SECTORS] + [
        {"code": c, "name": n, "is_thematic": False} for c, n in NON_THEMATIC_SECTORS]


@app.get("/api/review/sectors")
def review_sectors():
    """The sector dropdown's options: the database list, so sectors added in
    Review appear at once. Falls back to the configured list without one."""
    source = review_postgres_source()
    sectors = []
    if source is not None:
        try:
            sectors = source.fetch_sectors()
        except Exception as exc:  # noqa: BLE001 - the fallback list still works
            logger.warning("sector list unavailable: %s", exc)
    sectors = sectors or _fallback_sectors()
    register_sector_codes(s["code"] for s in sectors)
    return {"sectors": sectors, "can_create": review_admission_bridge().configured}


@app.post("/api/review/sectors")
def review_create_sector(body: SectorCreate):
    """Add a sector a real actor needs. Written by the GHUS backend (the
    approved canonical writer), never by this app."""
    bridge = review_admission_bridge()
    if not bridge.configured:
        raise HTTPException(status_code=503, detail=(
            "Sectors can only be added when admission is configured on this instance."))
    try:
        outcome = bridge.apply({"decision_kind": "create_sector", **body.model_dump()})
    except AdmissionBridgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    register_sector_codes([outcome.get("code") or ""])
    return outcome


@app.get("/api/review/hub-proposals")
def review_hub_proposals():
    """Open Phase 7 hub proposals. Read-only: detection never creates a hub."""
    source = review_postgres_source()
    if source is None:
        return {"proposals": [], "configured": False}
    try:
        return {"proposals": source.fetch_hub_proposals(), "configured": True}
    except PostgresReviewSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _raise_review_error(exc)


@app.get("/api/review/candidates")
def review_candidates(status: str = Query("pending_review"),
                      entity_type: str | None = Query(None),
                      source_run_id: str | None = Query(None),
                      run_group: str | None = Query(None),
                      actor_category: str | None = Query(None),
                      review_reason: str | None = Query(None),
                      region: str | None = Query(None),
                      search: str | None = Query(None, max_length=200),
                      refresh: bool = Query(False)):
    sync_warnings = _sync_review_candidates(force=refresh)
    try:
        result = review_store().list(
            status=status, entity_type=entity_type,
            source_run_id=source_run_id, search=search,
            run_group=run_group, actor_category=actor_category,
            review_reason=review_reason, region=region,
        )
        result["sync_warnings"] = sync_warnings
        result["demo_banner"] = _demo_banner()
        result["admission_configured"] = review_admission_bridge().configured
        return result
    except Exception as exc:
        _raise_review_error(exc)


@app.get("/api/review/candidates/{candidate_id}")
def review_candidate(candidate_id: str):
    try:
        return review_store().get(candidate_id)
    except Exception as exc:
        _raise_review_error(exc)


@app.patch("/api/review/candidates/{candidate_id}")
def review_candidate_update(candidate_id: str, payload: ReviewUpdateRequest):
    try:
        return review_store().update(candidate_id, payload.fields)
    except Exception as exc:
        _raise_review_error(exc)


@app.post("/api/review/candidates/{candidate_id}/approve")
def review_candidate_approve(candidate_id: str, payload: ReviewDecisionRequest):
    try:
        return review_store().approve(
            candidate_id, reviewer=payload.reviewer,
            idempotency_key=payload.idempotency_key, confirmed=payload.confirmed,
            notes=payload.notes, edited_payload=payload.edited_payload,
        )
    except Exception as exc:
        _raise_review_error(exc)


@app.post("/api/review/candidates/{candidate_id}/reject")
def review_candidate_reject(candidate_id: str, payload: ReviewRejectionRequest):
    try:
        return review_store().reject(
            candidate_id, reviewer=payload.reviewer,
            rejection_reason=payload.rejection_reason,
            idempotency_key=payload.idempotency_key, confirmed=payload.confirmed,
            notes=payload.notes,
        )
    except Exception as exc:
        _raise_review_error(exc)


@app.post("/api/review/candidates/{candidate_id}/decision")
def review_candidate_decision(candidate_id: str, payload: ReviewAdmissionRequest):
    store = review_store()
    try:
        decision = store.admission_request(
            candidate_id,
            decision_kind=payload.decision_kind,
            reviewer=payload.reviewer,
            idempotency_key=payload.idempotency_key,
            target_id=payload.target_id,
            notes=payload.notes,
            edited_payload=payload.edited_payload,
            hub_ids=payload.hub_ids,
            proposed_hub=payload.proposed_hub,
            rejection_reason=payload.rejection_reason,
            rejection_reason_other=payload.rejection_reason_other,
            confirmed=payload.confirmed,
        )
        outcome = review_admission_bridge().apply(decision)
        return store.record_admission_success(
            candidate_id,
            idempotency_key=payload.idempotency_key,
            decision_kind=payload.decision_kind,
            reviewer=payload.reviewer,
            notes=payload.notes,
            rejection_reason=payload.rejection_reason,
            outcome=outcome,
        )
    except AdmissionBridgeError as exc:
        store.record_admission_failure(
            candidate_id,
            idempotency_key=payload.idempotency_key,
            decision_kind=payload.decision_kind,
            error=str(exc),
        )
        _raise_review_error(exc)
    except Exception as exc:
        _raise_review_error(exc)


# ---------------------------------------------------------------- discovery
# Actor discovery runs only for requests made here. The page never writes the
# request tables: every call goes through the backend's own command, which
# applies the same rules as the scheduler and the database.

class DiscoveryDraft(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    sector_codes: list[str] = Field(default_factory=list, max_length=8)
    topic_ids: list[str] = Field(default_factory=list, max_length=8)
    focus_terms: list[str] = Field(default_factory=list, max_length=8)
    region_code: str | None = None
    state_code: str | None = None
    city: str | None = Field(default=None, max_length=120)
    start_date: str | None = None
    end_date: str
    cadence: str
    max_new_actors_per_run: int = Field(default=10, ge=1, le=50)


def _discovery_call(fn, *args):
    if not discovery_bridge().configured:
        raise HTTPException(status_code=503, detail=(
            "Discovery requests are not configured on this instance."))
    try:
        return fn(*args)
    except DiscoveryBridgeError as exc:
        raise HTTPException(status_code=422 if exc.rejected else 502, detail=str(exc)) from exc


@app.get("/api/discovery/status")
def discovery_status():
    return {"configured": discovery_bridge().configured}


@app.get("/api/discovery/options")
def discovery_options():
    return _discovery_call(discovery_bridge().options)


@app.get("/api/discovery/requests")
def discovery_requests():
    return _discovery_call(discovery_bridge().list_requests)


@app.post("/api/discovery/preview")
def discovery_preview(draft: DiscoveryDraft):
    return _discovery_call(discovery_bridge().preview, draft.model_dump(exclude_none=True))


@app.post("/api/discovery/requests")
def discovery_create(draft: DiscoveryDraft):
    return _discovery_call(discovery_bridge().create, draft.model_dump(exclude_none=True))


@app.post("/api/discovery/requests/{subscription_id}/run")
def discovery_run_now(subscription_id: str):
    """Start a live run of one request now. A person pressing the button is the
    explicit dispatch a live run requires; the run itself takes minutes."""
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    return _discovery_call(discovery_bridge().run_now, subscription_id)


# ------------------------------------------------------- specific actor updates
# Refresh what the map says about ONE existing actor - its funding, its recent
# activity, or every box - from its own pages. Search is a read-only query; the
# update itself runs in the GHUS backend, which writes through its approved
# fact writer. The page never writes canonical data.

class ActorUpdateRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=20)
    fields: str = Field(default="funding_activity", max_length=400)
    live: bool = False


@app.get("/api/discovery/actors")
def discovery_actor_search(q: str = Query("", max_length=120),
                           sector: str | None = Query(None, max_length=20),
                           category: str | None = Query(None, max_length=60),
                           state: str | None = Query(None, max_length=4),
                           everyone: bool = Query(False),
                           limit: int = Query(12, ge=1, le=50)):
    """Actors on the map, by words typed and/or a group (sector, category, state).

    ``everyone`` includes actors with no website, which an update cannot read.
    """
    source = review_postgres_source()
    if source is None:
        raise HTTPException(status_code=503, detail="Actor search is not available on this instance.")
    try:
        return source.search_actors(q, sector=sector, category=category, state=state,
                                    updatable_only=not everyone, limit=limit)
    except PostgresReviewSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/discovery/actors/{actor_id}/update")
def discovery_actor_update(actor_id: str, payload: ActorUpdateRequest):
    try:
        UUID(actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown actor") from exc
    return _discovery_call(
        lambda: discovery_bridge().update_actor(
            actor_id, topic=payload.topic, fields=payload.fields, live=payload.live))


@app.post("/api/discovery/requests/{subscription_id}/{action}")
def discovery_change(subscription_id: str, action: str):
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(status_code=404, detail="unknown action")
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    return _discovery_call(discovery_bridge().change, subscription_id, action)


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- static frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


# Mounted last so the /api routes above take precedence.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
