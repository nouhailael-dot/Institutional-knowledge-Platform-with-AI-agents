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
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # make `src` importable no matter the CWD

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import browse
from src.db import get_readonly_connection
from src.documents.doc_store import build_store, search_chunks
from src.documents.extract import ExtractionError, extract_text
from src.generate import stream_answer
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
    _DOC_STORES[doc_id] = {"store": store, "name": file.filename, "ts": time.time()}
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
               doc_id: str | None = Query(None)):
    """Server-Sent Events: `meta` (route + sources/sql), then `delta`* , then `done`.

    Mirrors app.py's Ask tab — SQL route answers exactly from the DB; everything
    else streams a cited answer from the map. When `doc_id` is attached, the
    answer merges document passages with map retrieval (same as the Streamlit
    doc flow) and skips the SQL route.
    """
    def gen():
        q = question.strip()
        if not q:
            yield _sse("done", {}); return

        # Document attached -> merge doc chunks + map hits into one cited answer.
        doc = _DOC_STORES.get(doc_id) if doc_id else None
        if doc is not None:
            merged = search_chunks(doc["store"], q) + retrieve(q, top_k=8)
            yield _sse("meta", {"mode": "doc", "sources": _sources(merged)})
            if merged:
                for chunk in stream_answer(q, merged):
                    yield _sse("delta", {"text": chunk})
            yield _sse("done", {})
            return

        mode, sql = plan(q)
        if mode == "sql":
            try:
                cols, rows = run_sql(sql)
                answer = format_sql_answer(q, sql, cols, rows)
                yield _sse("meta", {"mode": "sql", "sql": sql})
                yield _sse("delta", {"text": answer})
                yield _sse("done", {})
                return
            except Exception:
                mode = "semantic"      # fall back to map search, same as the UI

        hits = retrieve(q)
        yield _sse("meta", {"mode": "semantic", "sources": _sources(hits)})
        if hits:
            for chunk in stream_answer(q, hits):
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
    return JSONResponse(jsonable_encoder({"events": _events()}))


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- static frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


# Mounted last so the /api routes above take precedence.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
