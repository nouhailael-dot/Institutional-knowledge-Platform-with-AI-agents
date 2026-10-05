"""FastAPI layer over the existing RAG engine (src/).

This does NOT reimplement anything — it wraps the same functions app.py calls,
so the React frontend gets identical behavior: SQL-vs-semantic routing, streamed
cited answers, and the Browse data. Run from the repo root:

    uvicorn backend.app:app --reload --port 8000

The engine stays UI-agnostic; swapping or redesigning the frontend never touches
retrieve / generate / router / browse.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # make `src` importable no matter the CWD

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import browse
from src.db import get_readonly_connection
from src.documents.doc_store import build_store, search_chunks
from src.documents.extract import ExtractionError, extract_text
from src.generate import ask_handoff, condense_question, stream_answer
from src.map_agent.export import to_pptx, to_xlsx
from src.map_agent.pipeline import build_map
from src.map_agent.people_research import research_people
from src.map_agent.planner import map_chat
from src.map_agent.verify import summarize, verify
from src.map_agent.run_store import RunStore, RunContext, MapStopped
from src.map_agent.search_backend import availability as research_availability
from src.retrieve import retrieve
from src.router import format_sql_answer, plan, run_sql

@lru_cache(maxsize=1)
def map_store():
    return RunStore()


@asynccontextmanager
async def lifespan(app):
    map_store().recover()
    yield


app = FastAPI(title="UM6P Intelligence API", lifespan=lifespan)
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


class HandoffRequest(BaseModel):
    history: list[dict] = []


@app.post("/api/ask/handoff")
def ask_to_map_handoff(payload: HandoffRequest):
    """What an Ask conversation established, so Build a Map need not start cold.

    Called when the user clicks, never speculatively. Ask-side work: it spends
    nothing from a map budget and starts no research.
    """
    if not payload.history:
        raise HTTPException(status_code=400, detail="There is no conversation to carry over.")
    try:
        return ask_handoff(payload.history)
    except Exception:
        raise HTTPException(status_code=502,
                            detail="Could not read the conversation. Describe the map yourself.")


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
    # Background from an Ask conversation. Reaches the planner like an attached
    # document and never joins `description`, which later stages grade against.
    ask_context: str | None = None


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
    # Once a map exists the thread carries questions too, so the joined turns stop
    # being the request. Keep the request that produced these results; a follow-up
    # that asks for new ground extends it with its own message instead.
    if record["result"]:
        description = record["description"] or description
    try:
        # "done"/"error" included: the thread stays open after a map is built so
        # the user can ask about what was found, or ask for more.
        map_store().claim(job_id, "planning", "Planning",
                          ("draft", "awaiting_reply", "done", "error"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    doc = _DOC_STORES.get(payload.doc_id) if payload.doc_id else None
    text = record["doc_text"] or (doc["text"][:6000] if doc else None)
    map_store().update(job_id, description=description, messages=payload.messages, doc_text=text)
    try:
        result = map_chat(payload.messages, text, run=RunContext(map_store(), job_id),
                          ask_context=payload.ask_context, result=record["result"])
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


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- static frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


# Mounted last so the /api routes above take precedence.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
