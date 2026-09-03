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
from src.generate import condense_question, stream_answer
from src.map_agent.export import to_pptx, to_xlsx
from src.map_agent.pipeline import build_map
from src.map_agent.planner import map_chat
from src.map_agent.verify import summarize, verify
from src.retrieve import retrieve
from src.router import format_sql_answer, plan, run_sql

app = FastAPI(title="UM6P Intelligence API")
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
# Same in-memory posture as _DOC_STORES: nothing is written to Postgres, and the
# store is capped so the process can't grow unbounded.
_MAP_JOBS: dict[str, dict] = {}
_MAP_CAP = 12
_MAP_POOL = ThreadPoolExecutor(max_workers=2)   # a map is expensive; don't fan out


def _evict_maps():
    while len(_MAP_JOBS) > _MAP_CAP:
        oldest = min(_MAP_JOBS, key=lambda k: _MAP_JOBS[k]["ts"])
        _MAP_JOBS.pop(oldest, None)


class ChatRequest(BaseModel):
    """One turn of the map-planning conversation. `messages` is the whole thread
    as plain {role, content} turns; `doc_id` refers to an /api/upload document."""
    messages: list[dict]
    doc_id: str | None = None


@app.post("/api/map/chat")
def map_chat_turn(payload: ChatRequest):
    """Talk with the planner until it has enough to search.

    Returns {"status": "reply"|"plan"|"error", ...}. On "reply" the agent is
    asking something — show it and send the user's answer back with the thread.
    On "plan" it has decided: the caller starts POST /api/map with that plan.
    """
    if not payload.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    doc = _DOC_STORES.get(payload.doc_id) if payload.doc_id else None
    return JSONResponse(jsonable_encoder(
        map_chat(payload.messages, doc["text"] if doc else None)))


def _run_map_job(job_id: str, description: str, doc_text: str | None,
                 do_enrich: bool, actor_focus: str, plan: dict | None):
    """Worker body: run the pipeline, park the result on the job record."""
    job = _MAP_JOBS.get(job_id)
    if job is None:
        return
    try:
        job["result"] = build_map(description, doc_text, do_enrich=do_enrich,
                                  actor_focus=actor_focus, plan=plan)
        job["status"] = "done"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


class MapRequest(BaseModel):
    """Run an APPROVED plan. Documents are uploaded separately via /api/upload,
    so the planning turns and this call can both refer to them by `doc_id`."""
    description: str
    plan: dict | None = None          # from /api/map/plan; None re-plans silently
    doc_id: str | None = None
    enrich: bool = False
    actor_focus: str = "research"


@app.post("/api/map")
def map_start(payload: MapRequest):
    """Start a map build. Returns {job_id}; poll GET /api/map/{job_id}.

    Normally called with the plan the user approved at /api/map/plan — discovery
    is expensive, so it should never run on a plan nobody saw. `actor_focus`
    defaults to "research" (~80/20 toward universities and national labs) and is
    deliberately NOT exposed in the UI.
    """
    desc = (payload.description or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="description is required")

    doc = _DOC_STORES.get(payload.doc_id) if payload.doc_id else None
    doc_text = doc["text"] if doc else None

    job_id = uuid4().hex
    focus = payload.actor_focus if payload.actor_focus in (
        "both", "companies", "research") else "research"
    _MAP_JOBS[job_id] = {"status": "running", "result": None, "error": None,
                         "description": desc, "ts": time.time()}
    _evict_maps()
    _MAP_POOL.submit(_run_map_job, job_id, desc, doc_text, payload.enrich,
                     focus, payload.plan)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/map/{job_id}")
def map_status(job_id: str):
    """Poll a map job. status is running | done | error; result present when done."""
    job = _MAP_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return JSONResponse(jsonable_encoder({
        "status": job["status"],
        "description": job["description"],
        "result": job["result"],
        "error": job["error"],
    }))


class VerifyRequest(BaseModel):
    """Phase-2 payload. `entities` are the ones the frontend already holds, and
    `request` must be the ORIGINAL map description — the judge grades against it."""
    entities: list[dict]
    request: str
    check_links: bool = True
    run_judge: bool = True


@app.post("/api/map/verify")
def map_verify(payload: VerifyRequest):
    """Run the verification layers (link check -> judge -> relevance floor).

    Works for one entity or all of them — the frontend decides what to send.
    Returns the annotated entities plus summary counts.
    """
    if not payload.entities:
        return {"entities": [], "summary": summarize([])}
    entities = verify(payload.entities, payload.request,
                      check_links=payload.check_links,
                      run_judge=payload.run_judge)
    return JSONResponse(jsonable_encoder({
        "entities": entities,
        "summary": summarize(entities),
    }))


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
