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
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Literal
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # make `src` importable no matter the CWD

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import browse
from src.documents.doc_store import build_store, search_chunks
from src.documents.extract import ExtractionError, extract_text
from src.generate import ask_handoff, condense_question, stream_answer
from src.map_agent.actor_profile import LEGACY_CATEGORIES, NOT_CLASSIFIED
from src.map_agent import parked, review
from src.map_agent import save as map_save
from src.datafeed.service import DataFeedError
from src.map_agent.dedup import mark_possible_duplicates
from src.map_agent.discovery_brief import propose_discovery
from src.map_agent.export import to_pptx, to_xlsx
from src.map_agent.pipeline import build_map
from src.map_agent.people_research import research_people
from src.map_agent.planner import map_chat
from src.map_agent.verify import summarize, verify
from src.map_agent.run_store import RunStore, RunContext, MapStopped
from src.map_agent.search_backend import availability as research_availability
from src.retrieve import retrieve
from src.discovery.bridge import DiscoveryBridge, DiscoveryBridgeError
from backend.access import require_login
from backend import datafeed_routes
from backend.datafeed_routes import router as datafeed_router
from src.plain_errors import GENERIC as PLAIN_GENERIC
from src.plain_errors import REASON_KEYS, explain, explain_payload, is_technical
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
    from src.trial import trial_start
    store = ReviewStore(enable_test_canonical=_local_review_demo_enabled())
    # The hosted trial's clean start: each sync sets aside what came before it.
    start = trial_start()
    store.trial_cutoff = start.timestamp() if start else None
    return store


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
    # The app keeps the last request lists and refreshes them in the background.
    return DiscoveryBridge(cache_lists=True)


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
    # The shared server reads Review's sources once at start (about a minute),
    # in the background, so the first visit to Review answers at once.
    if os.environ.get("GHUS_REVIEW_WARM_START", "").strip() == "1":
        start_review_sync_in_background(force=True)
        try:
            discovery_bridge().warm_lists()
        except Exception:  # noqa: BLE001 - Monitor then reads the lists on first visit
            logger.exception("Could not start reading the request lists")
    # Records deleted more than 30 days ago: the daily cleanup (GHUS_PURGE_MODE, off by default).
    scheduler = _start_purge_scheduler()
    yield
    if scheduler is not None:
        scheduler.stop()


def _start_purge_scheduler():
    from backend import accounts_routes
    from backend.purge_scheduler import PurgeScheduler, purge_mode
    if purge_mode() == "off" or not accounts_routes.accounts_enabled():
        return None
    try:
        scheduler = PurgeScheduler(bridge=review_admission_bridge(), store=accounts_routes.accounts_store())
        scheduler.start()
        return scheduler
    except Exception:  # noqa: BLE001 - the server runs without the cleanup; the log says so
        logger.exception("Could not start the scheduled cleanup")
        return None


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


# ------------------------------------------------- errors in plain words
# Every screen shows ``detail`` (a failed request) or ``error`` / ``status_reason``
# (a run that finished without what was asked). They are put into words a person
# without technical training understands here, once, for every page; the original
# stays beside them under ``technical`` for support. See src/plain_errors.py.

@app.exception_handler(StarletteHTTPException)
async def plain_http_error(request, exc):
    detail = exc.detail
    body = {"detail": detail}
    if isinstance(detail, str) and is_technical(detail):
        body = {"detail": explain(detail), "technical": detail}
    elif isinstance(detail, dict) and is_technical(detail.get("message")):
        body = {"detail": {**detail, "message": explain(detail["message"])},
                "technical": detail["message"]}
    return JSONResponse(jsonable_encoder(body), status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def plain_validation_error(request, exc):
    fields = sorted({str(error.get("loc", ())[-1]).replace("_", " ")
                     for error in exc.errors() if error.get("loc")})
    return JSONResponse(status_code=422, content=jsonable_encoder({
        "detail": ("Some information is missing or not valid"
                   + (f": {', '.join(fields)}." if fields else ".")),
        "errors": exc.errors(),
    }))


@app.exception_handler(Exception)
async def plain_unexpected_error(request, exc):
    logger.exception("Unexpected error on %s", request.url.path)
    return JSONResponse(status_code=500, content={
        "detail": PLAIN_GENERIC, "technical": f"{type(exc).__name__}: {exc}"[:500]})


@app.middleware("http")
async def plain_reasons(request, call_next):
    """A finished run's reasons (error, status_reason ...) in plain words."""
    response = await call_next(request)
    if (not request.url.path.startswith("/api/")
            or "application/json" not in response.headers.get("content-type", "")):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    if len(body) <= 3_000_000 and any(f'"{key}"'.encode() in body for key in REASON_KEYS):
        try:
            body = json.dumps(explain_payload(json.loads(body))).encode("utf-8")
        except ValueError:
            pass
    rebuilt = Response(content=body, status_code=response.status_code, media_type="application/json")
    # Every header as it came, repeated ones included: a sign-in sets three cookies, and a
    # dict of headers kept only the last one (accounts could not stay signed in).
    rebuilt.raw_headers.extend((k, v) for k, v in response.headers.raw
                               if k.lower() not in (b"content-length", b"content-type"))
    return rebuilt


# Registered last, so it runs first: the hosted app asks for a login before
# anything else answers. Individual accounts (backend/accounts_routes.py) only
# with GHUS_AUTH_MODE=supabase; otherwise the shared login (backend/access.py;
# off locally unless configured), exactly as before.
from backend import accounts_routes  # noqa: E402

if accounts_routes.accounts_enabled():
    from backend import accounts_admin  # noqa: E402

    app.include_router(accounts_routes.router)
    app.include_router(accounts_admin.router)
    app.middleware("http")(accounts_routes.require_account)
    accounts_routes.warn_without_administrator()
else:
    app.middleware("http")(require_login)


FRONTEND = ROOT / "frontend"


# --- read-only data loads, cached in-process (the whole live set is <1000 rows).
# 13 Nov 2026: each list is kept for DIRECTORY_FRESH_SECONDS, then read again.
# It was kept until the server restarted, so a record verified in Review, stored
# from the Data Feed or deleted in the database stayed invisible (or visible)
# in the Ecosystem Directory until the next deploy.
DIRECTORY_FRESH_SECONDS = float(os.environ.get("GHUS_DIRECTORY_FRESH_SECONDS") or 30)


def _fresh_for(seconds: float):
    """Like lru_cache(maxsize=1) on a function without arguments, for ``seconds``."""
    def wrap(load):
        state: dict[str, Any] = {}
        lock = Lock()

        def cached():
            with lock:
                if "value" in state and time.monotonic() - state["at"] < seconds:
                    return state["value"]
            value = load()
            with lock:
                state.update(value=value, at=time.monotonic())
            return value

        def cache_clear():
            with lock:
                state.clear()

        cached.cache_clear = cache_clear
        cached.__wrapped__ = load
        return cached
    return wrap


@_fresh_for(DIRECTORY_FRESH_SECONDS)
def _actors():
    return browse.load_actors()


@_fresh_for(DIRECTORY_FRESH_SECONDS)
def _hubs():
    return browse.load_hubs()


@_fresh_for(DIRECTORY_FRESH_SECONDS)
def _events():
    return browse.load_events()


@_fresh_for(DIRECTORY_FRESH_SECONDS)
def _people():
    return browse.load_people()


def _directory_changed() -> None:
    """Something was written to the Directory (a Review decision, a map save, a Data
    Feed import): its lists are read again on the next request, not up to
    DIRECTORY_FRESH_SECONDS later (23 Nov 2026)."""
    for cached in (_actors, _hubs, _events, _people):
        cached.cache_clear()


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
            "parked": bool(h.get("parked")),
            "map": h.get("map"),
        })
    return out


def _parked_hits(question: str, hits: list[dict], visible=None) -> list[dict]:
    """Parked organizations for Ask, from the asker's own maps. A secondary source:
    if it fails, Ask still answers from the database alone."""
    try:
        return parked.search(question, map_store(), skip_names=[h["name"] for h in hits],
                             visible=visible)
    except Exception as exc:
        print(f"Parked search skipped: {exc}", file=sys.stderr)
        return []


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
    # Who asked, taken now: the answer streams after this function returns.
    from src.identity import current_account
    asker = current_account()
    # Parked organizations come only from the asker's own maps (and those from
    # before accounts); read now, for the same reason. Unknown owners: none.
    try:
        own_maps = personal.visible_test("map")
    except personal.OwnershipUnavailable:
        own_maps = lambda _id: False  # noqa: E731

    def on_usage(model, usage):
        """The answer's token usage, priced like the maps' calls (accounts Phase 5)."""
        if asker is None:
            return
        import uuid

        from src.map_agent.costs import PRICES, usage_cost
        # The SDK gives an object; the shared pricing reads plain data.
        data = usage.model_dump() if hasattr(usage, "model_dump") else dict(getattr(usage, "__dict__", {}) or {})
        tokens_in, tokens_out = data.get("input_tokens"), data.get("output_tokens")
        priced = model in PRICES
        try:
            cost = usage_cost(model, data) / 1_000_000 if priced else None
        except Exception:  # noqa: BLE001 - unpriced tool use: tokens kept, cost unknown
            cost, priced = None, False
        activity.record_usage("ask", uuid.uuid4().hex, cost_usd=cost,
                              cost_basis="usage_priced" if priced else "unknown",
                              input_tokens=tokens_in, output_tokens=tokens_out,
                              detail={"model": model}, account=asker)

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
            merged = search_chunks(doc["store"], standalone) + _ask_visible(retrieve(standalone, top_k=8))
            yield _sse("meta", {"mode": "doc", "sources": _sources(merged), "rewritten": rewritten})
            if merged:
                for chunk in stream_answer(standalone, merged, on_usage=on_usage):
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

        hits = _ask_visible(retrieve(standalone))
        hits += _parked_hits(standalone, hits, own_maps)
        yield _sse("meta", {"mode": "semantic", "sources": _sources(hits), "rewritten": rewritten})
        if hits:
            for chunk in stream_answer(standalone, hits, on_usage=on_usage):
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
    # Browse's own connection: an instance with BROWSE_DATABASE_URL (the demo)
    # names its sectors from that database, never from DATABASE_URL in .env.
    with browse._readonly() as conn, conn.cursor() as cur:
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


# ------------------------------------------- Deleted records are hidden at once (Phase 6)
def _accounts_on() -> bool:
    """Individual accounts are in use (the switch is on, or someone is signed in)."""
    from backend.accounts_routes import accounts_enabled
    from src.identity import current_account
    return accounts_enabled() or current_account() is not None


def _deleted_ids(kind: str) -> set[str]:
    """Records awaiting permanent deletion (empty without individual accounts or 710)."""
    if not _accounts_on():
        return set()
    from backend.accounts_routes import accounts_store
    try:
        return accounts_store().hidden_ids(kind)
    except Exception:
        logger.warning("Could not read deleted %s records", kind, exc_info=True)
        return set()


def _without_deleted(rows: list[dict], kind: str, *, key: str = "id") -> list[dict]:
    hidden = _deleted_ids(kind)
    return [r for r in rows if str(r.get(key)) not in hidden] if hidden else rows


_ASK_KINDS = {"actor": "actor", "organization": "actor", "event": "event", "person": "person", "hub": "hub"}


def _ask_visible(hits: list[dict]) -> list[dict]:
    """Ask never answers from a deleted record."""
    hidden = {kind: _deleted_ids(kind) for kind in ("actor", "event", "person", "hub")}
    if not any(hidden.values()):
        return hits
    return [h for h in hits if str(h.get("entity_id")) not in
            hidden.get(_ASK_KINDS.get(str(h.get("entity_type") or "").lower(), ""), set())]


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
    enriched = _without_deleted(enriched, "actor")
    return JSONResponse(jsonable_encoder({"actors": activity.with_owners(enriched, "actor"),
                                          "options": options}))


# --- Delete in the Ecosystem Directory (29 Oct 2026). Removable, never wiped: the
# backend appends a GHUS decision ("rejected" to remove, "verified" to restore)
# through its own writer, and the database hides a rejected organization.
# Who is acting: src.identity, the one place (decided 29 Oct 2026; Review, Monitor
# and the Data Feed since 3 Nov). Nobody types a name or an email.
from src.identity import NO_SIGN_IN_YET, current_user, current_user_email  # noqa: E402
# Who did what, and who brought each record in (accounts Phase 3; does nothing without accounts).
from src.accounts import activity  # noqa: E402
# Personal pages (GHUS, 23 Nov 2026): maps, requests, imports, Review Results and
# Pending Deletion are each person's own; the Directory is shared.
from src.accounts import personal  # noqa: E402


@app.exception_handler(personal.OwnershipUnavailable)
async def _owners_unavailable(request, exc):
    # Refused rather than shown whole: a personal list never leaks everyone's items.
    return JSONResponse({"detail": exc.message}, status_code=503)


# A Review item's run, for "is it theirs?" on every route that names one.
personal.candidate_run = lambda candidate_id: (
    review_store().source_run_of(candidate_id) if hasattr(review_store(), "source_run_of") else None)


class DirectoryDecision(BaseModel):
    reason: str = ""
    confirm: bool = False


def _directory_decision(kind: str, actor_id: str, payload: DirectoryDecision):
    reviewer = current_user()
    reason = " ".join(payload.reason.split())
    if kind == "remove_from_directory" and not reason:
        raise HTTPException(status_code=400, detail="Give a reason: it is kept with the record.")
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirm the removal first.")
    bridge = review_admission_bridge()
    if not bridge.configured:
        raise HTTPException(status_code=503, detail=(
            "Deleting isn't set up on this computer: Review's decision writer is not configured."))
    try:
        outcome = bridge.apply({
            "decision_kind": kind, "entity_type": "actor", "entity_id": actor_id,
            "reviewer": reviewer, "reason": reason[:500],
            "idempotency_key": f"directory:{kind}:{actor_id}:{int(time.time())}"})
    except AdmissionBridgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    activity.note(reason=reason[:500], result=outcome.get("status"))
    activity.notify_owner("actor", actor_id, key=f"directory:{kind}:{actor_id}:{int(time.time())}",
                          link="browse",
                          title=f"'{outcome.get('name') or 'An organization'}' was "
                                f"{'removed from' if kind == 'remove_from_directory' else 'restored to'} "
                                "the Directory",
                          body=f"By {reviewer}." + (f" Reason: {reason[:200]}" if reason else ""))
    _actors.cache_clear()
    return outcome


@app.post("/api/browse/actors/{actor_id}/remove")
def directory_remove(actor_id: str, payload: DirectoryDecision):
    return _directory_decision("remove_from_directory", actor_id, payload)


@app.post("/api/browse/actors/{actor_id}/restore")
def directory_restore(actor_id: str, payload: DirectoryDecision):
    return _directory_decision("restore_to_directory", actor_id, payload)


class DirectoryEdit(BaseModel):
    changes: dict = {}
    ghus_notes: str | None = None


_DIRECTORY_EDIT_KINDS = {"actors": "actor", "events": "event", "people": "person", "hubs": "hub"}


@app.post("/api/browse/{kind}/{record_id}/edit")
def directory_edit(kind: str, record_id: str, payload: DirectoryEdit):
    """Save an edit made in the Ecosystem Directory (10 Nov 2026).

    The platform never writes the record itself: the backend's approved writer
    (decisions.record_directory_edit, through the admission process) checks
    every field and writes them in one transaction, with the person's name.
    """
    entity_type = _DIRECTORY_EDIT_KINDS.get(kind)
    if entity_type is None:
        raise HTTPException(status_code=404, detail="Unknown record type.")
    if not payload.changes and payload.ghus_notes is None:
        raise HTTPException(status_code=400, detail="Nothing to save: no field was changed.")
    bridge = review_admission_bridge()
    if not bridge.configured:
        raise HTTPException(status_code=503, detail=(
            "Saving isn't set up on this computer: Review's decision writer is not configured."))
    try:
        outcome = bridge.apply({
            "decision_kind": "edit_directory_record", "entity_type": entity_type,
            "entity_id": record_id, "changes": payload.changes,
            "ghus_notes": payload.ghus_notes, "reviewer": current_user(),
            "idempotency_key": f"directory:edit:{record_id}:{time.time_ns()}"})
    except AdmissionBridgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The lists are read again; an organization's name also shows on hubs and people.
    activity.note(changed=outcome.get("changed"), result=outcome.get("status"))
    if outcome.get("status") == "applied":
        activity.notify_owner(entity_type, record_id, link="browse",
                              key=f"edit:{entity_type}:{record_id}:{time.time_ns()}",
                              title="A record you brought in was edited",
                              body=f"{current_user()} changed: {', '.join(outcome.get('changed') or []) or 'details'}.")
    for cached in (_actors, _hubs, _events, _people):
        cached.cache_clear()
    return outcome


# ------------------------------------------------- Delete, keep 30 days, restore (Phase 6)
# GHUS policy (17 Nov 2026): a deleted record disappears from active use at once,
# waits 30 days under Pending Deletion (Dashboard; restorable), then the
# scheduled cleanup removes it permanently. The backend's approved writer does
# every step (decisions.delete_record / restore_record / purge_record).
class RecordDeletion(BaseModel):
    reason: str = Field(default="", max_length=500)
    confirm: bool = False


def _signed_in_account():
    from src.identity import current_account
    me = current_account()
    if me is None:
        raise HTTPException(status_code=409, detail="Deleting needs individual accounts (who deleted is recorded).")
    return me


def _deletion_label(entity_type: str, name: str | None) -> str:
    if entity_type == "person" or not name:
        return {"person": "A person", "event": "An event", "hub": "A hub"}.get(entity_type, "An organization")
    return f"'{name}'"


def _deletion_call(decision: dict) -> dict:
    bridge = review_admission_bridge()
    if not bridge.configured:
        raise HTTPException(status_code=503, detail=(
            "Deleting isn't set up on this computer: Review's decision writer is not configured."))
    try:
        outcome = bridge.apply(decision)
    except AdmissionBridgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from backend.accounts_routes import accounts_store
    accounts_store().forget_hidden()
    for cached in (_actors, _hubs, _events, _people):
        cached.cache_clear()
    return outcome


@app.post("/api/browse/{kind}/{record_id}/delete")
def directory_delete(kind: str, record_id: str, payload: RecordDeletion):
    """Delete a record: hidden at once, restorable for 30 days, then removed for good."""
    entity_type = _DIRECTORY_EDIT_KINDS.get(kind)
    if entity_type is None:
        raise HTTPException(status_code=404, detail="Unknown record type.")
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirm the deletion first.")
    me = _signed_in_account()
    outcome = _deletion_call({
        "decision_kind": "delete_record", "entity_type": entity_type, "entity_id": record_id,
        "reason": " ".join(payload.reason.split())[:500], "user_id": me.user_id, "reviewer": me.full_name,
        "idempotency_key": f"delete:{entity_type}:{record_id}:{time.time_ns()}"})
    # The audit history is permanent: a person's name stays out of it (and out of the
    # owner's notification), so nothing personal outlives the permanent deletion.
    shown = _deletion_label(entity_type, outcome.get("name"))
    activity.note(record_name=None if entity_type == "person" else outcome.get("name"),
                  deletion_id=outcome.get("deletion_id"), purge_after=outcome.get("purge_after"),
                  reason=payload.reason.strip() or None)
    activity.notify_owner(entity_type, record_id, link="deletions", key=f"deleted:{outcome.get('deletion_id')}",
                          title=f"{shown} you brought in was deleted",
                          body=f"By {me.full_name}. It can be restored from Pending Deletion "
                               "(on the Dashboard) for 30 days." + (f" Reason: {payload.reason.strip()[:200]}" if payload.reason.strip() else ""))
    return outcome


def _deletion_view(d: dict) -> dict:
    snapshot = d.get("snapshot") or {}
    row = snapshot.get("row") or {}
    keep = ("website", "city", "location_city", "country", "description", "title", "event_type", "location",
            "start_date", "primary_city", "state", "status")
    return {**{k: d[k] for k in ("deletion_id", "entity_type", "entity_id", "name", "reason", "deleted_at",
                                 "purge_after", "deleted_by", "days_remaining", "owner")},
            "details": {k: row[k] for k in keep if row.get(k)}, "links": snapshot.get("links") or {}}


@app.get("/api/review/deleted")
def review_deleted():
    """Deleted records waiting for permanent removal (Pending Deletion: the Dashboard card and
    page). Separate from Review Results: a deletion is not a rejection."""
    from backend.accounts_routes import accounts_store
    if not _accounts_on():
        return {"deleted": [], "retention_days": 30}
    # Each person's own deletions, admins included (personal pages, 23 Nov 2026).
    me = _signed_in_account()
    return {"deleted": [_deletion_view(d) for d in accounts_store().deletions()
                        if d.get("deleted_by_user_id") == me.user_id], "retention_days": 30}


class RestoreRequest(BaseModel):
    confirm: bool = False


@app.post("/api/review/deleted/{deletion_id}/restore")
def review_restore_deleted(deletion_id: str, payload: RestoreRequest):
    """Bring a deleted record back within its 30 days: status, owner, links and history as they were."""
    if payload.confirm is not True:
        raise HTTPException(status_code=400, detail="Confirm the restore first.")
    try:
        deletion_id = str(UUID(deletion_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown deletion.") from exc
    me = _signed_in_account()
    outcome = _deletion_call({"decision_kind": "restore_record", "deletion_id": deletion_id,
                              "user_id": me.user_id, "reviewer": me.full_name,
                              "idempotency_key": f"restore:{deletion_id}"})
    entity_type = outcome.get("entity_type") or "actor"
    activity.note(record_type=entity_type, record_id=outcome.get("entity_id"),
                  record_name=None if entity_type == "person" else outcome.get("name"))
    activity.notify_owner(entity_type, outcome.get("entity_id"), link="browse",
                          key=f"restored:{deletion_id}",
                          title=f"{_deletion_label(entity_type, outcome.get('name'))} you brought in was restored",
                          body=f"By {me.full_name}.")
    return outcome


@app.get("/api/browse/actors/{actor_id}/profile")
def browse_actor_profile(actor_id: str):
    if actor_id in _deleted_ids("actor"):
        raise HTTPException(status_code=404, detail="That organization was deleted.")
    return JSONResponse(jsonable_encoder(browse.load_actor_profile(actor_id)))


@app.get("/api/browse/actors/removed")
def browse_removed_actors():
    return JSONResponse(jsonable_encoder({"actors": browse.load_removed_actors()}))


@app.get("/api/browse/hubs")
def browse_hubs():
    return JSONResponse(jsonable_encoder(
        {"hubs": activity.with_owners(_without_deleted(_hubs(), "hub", key="hub_id"), "hub"),
         "columns": browse.hub_columns()}))


@app.get("/api/browse/events")
def browse_events():
    evts = _events()
    types = sorted({e["event_type"] for e in evts if e.get("event_type")})
    evts = _without_deleted(evts, "event")
    return JSONResponse(jsonable_encoder({"events": activity.with_owners(evts, "event"),
                                          "event_types": types}))


@app.get("/api/browse/people")
def browse_people():
    people = _people()
    return JSONResponse(jsonable_encoder(
        {"people": activity.with_owners(_without_deleted(people, "person"), "person"),
         "options": browse.people_filter_options(people)}))


# ---------------------------------------------------------------- Build the Map
# Phase 1 (discovery) takes minutes, so it can't be one blocking request: POST
# /api/map starts a job and returns an id, the frontend polls GET /api/map/{id}.
# Phase 2 (verification) is on demand and fast enough to answer inline, and is
# stateless — the frontend posts back the entities it already holds.
#
# Maps and usage persist locally, independently of the production actor DB.
# Maps research side by side for everyone (GHUS, 12 Nov 2026): a map waits on
# the AI service, not on this server, so many fit; more wait their turn.
_MAP_POOL = ThreadPoolExecutor(max_workers=max(1, int(os.environ.get("GHUS_MAP_WORKERS") or 8)))


def map_record(job_id):
    # Someone else's map is unknown here too (personal pages, 23 Nov 2026): this
    # covers the routes that name the map in the body (chat, start, upload).
    if not personal.may_open("map", job_id):
        raise HTTPException(status_code=404, detail="Unknown map session.")
    try:
        return map_store().get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown map session.")


def public_map(job_id):
    record = map_record(job_id)
    actors = ((record["result"] or {}).get("entities") or {}).get("actor", [])
    for actor in actors:
        if actor.get("actor_type") in LEGACY_CATEGORIES:
            actor["actor_type"] = LEGACY_CATEGORIES[actor["actor_type"]]
        actor.setdefault("category_type", NOT_CLASSIFIED)
    mark_possible_duplicates(actors)
    return {k: record[k] for k in ("id", "status", "stage", "description", "result", "error",
                                   "cost", "messages", "plan", "created", "updated")}


@app.post("/api/map/session")
def map_session():
    job_id = map_store().create()
    activity.claim("map", job_id, "created")
    return {"job_id": job_id}


@app.get("/api/maps")
def maps_recent():
    from src.trial import trial_start
    enabled, reason = research_availability()
    # Your own maps, and those from before accounts (personal pages, 23 Nov 2026).
    maps = personal.keep(map_store().recent(), "map")
    # The hosted trial lists only the maps made since it started (src.trial).
    if (start := trial_start()) is not None:
        maps = [m for m in maps if float(m.get("created") or 0) >= start.timestamp()]
    # Records each map sent to Review Results that nobody has decided yet (Dashboard).
    try:
        # Cards still undecided on the map itself: maps are reviewed on their own
        # page (GHUS, 12 Nov 2026), never in Review Results.
        pending = map_store().undecided([m["id"] for m in maps])
    except Exception:
        logger.warning("Could not count maps' pending Review records", exc_info=True)
        pending = {}
    for m in maps:
        m["pending_review"] = pending.get(m["id"], 0)
    return {"maps": maps, "research_available": enabled, "research_disabled_reason": reason}


@app.get("/api/me")
def who_am_i():
    """The signed-in person, and whether results can be emailed to them (12 Nov 2026)."""
    who = current_user()
    mail = bool(os.environ.get("GHUS_SMTP_HOST", "").strip()
                and (os.environ.get("GHUS_NOTIFY_FROM") or os.environ.get("GHUS_SMTP_USER") or "").strip())
    email = current_user_email()
    return {"signed_in": who != NO_SIGN_IN_YET, "name": None if who == NO_SIGN_IN_YET else who,
            "email": email, "email_notifications": bool(mail and email)}


@app.get("/api/dashboard/directory-activity")
def dashboard_directory_activity(days: int = Query(30, ge=1, le=366)):
    """The signed-in user's latest Directory contributions (Review decisions), newest first.

    Who is asking comes from the account (src.identity), never a typed name: until
    sign-in exists nobody is known, so the list is empty and says so.
    """
    from src.dashboard import directory_activity
    who = current_user()
    if who == NO_SIGN_IN_YET:
        return {"activity": [], "signed_in": False}
    try:
        return {"activity": directory_activity(who, days=days), "signed_in": True}
    except Exception:
        logger.exception("Dashboard directory activity failed")
        raise HTTPException(503, "The Directory activity could not be read right now.")


@app.get("/api/dashboard/start")
def dashboard_start():
    """When the Dashboard starts counting: the hosted trial's start (src.trial).

    Spending, counts and recent items only from that moment; earlier work stays
    in the database and on its own pages. Not set: no start, everything counts.
    """
    from src.trial import iso, trial_start
    return {"since": iso(trial_start())}


@app.get("/api/dashboard/spending")
def dashboard_spending():
    """Every month's request spending and the maps run on this computer. For the admin."""
    from src.dashboard import spending_by_month
    try:
        months = spending_by_month()
    except Exception:
        logger.exception("Dashboard spending failed")
        raise HTTPException(503, "Spending could not be read right now.")
    maps: dict[str, float] = {}
    for m in map_store().recent():
        month = time.strftime("%Y-%m", time.localtime(m["created"]))
        maps[month] = round(maps.get(month, 0.0) + float(m.get("spent_usd") or 0), 4)
    return {"months": months, "maps_on_this_computer": maps}


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
        activity.record_usage("people_search", task_id, detail={"map_id": job_id})
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
    if not payload.job_id:
        activity.claim("map", job_id, "created")
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
    if not payload.job_id:
        activity.claim("map", job_id, "created")
    record = map_record(job_id)
    if not (record["plan"] or payload.plan or {}).get("tasks"):
        raise HTTPException(status_code=400, detail="A search plan is required before research.")
    try:
        map_store().claim(job_id, "running", "Preparing research", ("draft", "ready"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    doc_text = record["doc_text"] or doc_text
    # The conversation reads like a chat: this search's results are shown right
    # after the message that started it (the plan's announcement).
    approved_plan = {**(record["plan"] or payload.plan),
                     "after_message": len(record["messages"] or [])}
    # A follow-up on a built map searches new ground; its message is that round's
    # request, not the map's. Keep the original as the map's name and request.
    fields = {"doc_text": doc_text, "plan": approved_plan}
    if not record["result"]:
        fields["description"] = desc
    map_store().update(job_id, **fields)
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


@app.post("/api/map/{job_id}/reopen")
def map_reopen(job_id: str):
    map_record(job_id)
    try:
        map_store().reopen(job_id)
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return public_map(job_id)


@app.post("/api/map/{job_id}/discovery-brief")
def map_discovery_brief(job_id: str):
    """Propose a Discovery request from a finished organization map.

    One small paid call on the map's own budget. Nothing is saved: the proposal
    goes to the Discovery page, where the user edits it before creating anything."""
    require_research()
    record = map_record(job_id)
    result = record["result"] or {}
    if (result.get("map_type") or "organizations") != "organizations":
        raise HTTPException(status_code=400, detail="Discovery looks for organizations only.")
    if not (result.get("entities") or {}).get("actor"):
        raise HTTPException(status_code=400, detail="This map has no organizations yet.")
    status, error = record["status"], record["error"]
    try:
        map_store().claim(job_id, "planning", "Discovery proposal", ("done", "error"))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        proposal = propose_discovery(record["messages"], record["description"],
                                     run=RunContext(map_store(), job_id))
    except Exception as exc:
        map_store().finish(job_id, status, error)
        raise HTTPException(status_code=502, detail=f"Could not propose a Discovery request: {exc}")
    map_store().finish(job_id, status, error)
    return {**proposal, "cost": map_record(job_id)["cost"]}


class ReviewRequest(BaseModel):
    name: str
    website: str | None = None
    action: Literal["park", "unpark", "reject", "ready", "unready"]
    kind: Literal["actor", "person", "event"] = "actor"


@app.post("/api/map/{job_id}/review")
def map_review(job_id: str, payload: ReviewRequest):
    """Park, unpark or permanently reject one organization, person or event in a saved map."""
    map_record(job_id)
    try:
        map_store().edit_result(job_id, lambda result, workflow: review.apply(
            result, workflow, payload.name, payload.website, payload.action, payload.kind))
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return public_map(job_id)


class SavePick(BaseModel):
    name: str
    website: str | None = None
    kind: Literal["actor", "person", "event"] = "actor"
    sector: str = ""


class SaveRequest(BaseModel):
    records: list[SavePick]
    uploaded_by: str = ""
    attest: bool = False


def _save_picks(job_id: str, records: list[SavePick]):
    """The verified cards a save names, as (kind, entity, sector)."""
    if not records:
        raise HTTPException(status_code=400, detail="Verify at least one result first.")
    if len(records) > 50:
        raise HTTPException(status_code=400, detail="Save at most 50 results at a time.")
    entities = ((map_record(job_id)["result"] or {}).get("entities") or {})
    picks = []
    for pick in records:
        found = [e for e in entities.get(pick.kind) or []
                 if (e.get("full_name") if pick.kind == "person" else e.get("name")) == pick.name
                 and (e.get("website") or "") == (pick.website or "")]
        if len(found) != 1:
            raise HTTPException(status_code=404, detail=f"{pick.name} is no longer in this map.")
        picks.append((pick.kind, found[0], pick.sector.strip()))
    return picks


def _save_service():
    from backend.datafeed_routes import datafeed_service
    service = datafeed_service()
    if not service.bridge.configured:
        raise HTTPException(status_code=503, detail=(
            "Saving to the database isn't set up on this computer yet: "
            "DATAFEED_DATABASE_URL is missing from .env."))
    return service


@app.post("/api/map/{job_id}/save-check")
def map_save_check(job_id: str, payload: SaveRequest):
    """Free and writes nothing: what saving each verified card would do."""
    picks = _save_picks(job_id, payload.records)
    try:
        return {"records": map_save.check(_save_service(), picks)}
    except DataFeedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/map/{job_id}/save")
def map_save_verified(job_id: str, payload: SaveRequest):
    """Verify -> the database, through the Data Feed and the backend's admission
    (28 Oct 2026). New organizations are added Verified; the rest wait in Review
    Results. Who verified is the current user (no typed name; accounts will fill it)."""
    uploader = current_user()
    if payload.attest is not True:
        raise HTTPException(status_code=400, detail="Confirm that you're authorized GHUS staff and checked the sources.")
    record = map_record(job_id)
    picks = _save_picks(job_id, payload.records)
    try:
        results = map_save.save(_save_service(), picks, uploader=uploader,
                                map_name=record["description"] or "untitled map")
    except DataFeedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _directory_changed()
    when = time.time()
    def change(result, workflow):
        for pick, outcome in zip(payload.records, results):
            review.mark_saved(result, workflow, pick.name, pick.website, pick.kind,
                              {"outcome": outcome["outcome"], "reason": outcome["reason"],
                               "by": uploader, "at": when})
        return result, workflow
    try:
        map_store().edit_result(job_id, change)
    except MapStopped as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {**public_map(job_id), "saved": results}


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


@app.post("/api/map/{job_id}/settle-charges")
def map_settle_charges(job_id: str, payload: BudgetExtensionRequest):
    """Count unconfirmed charges at their maximum so a blocked map can go on (12 Nov 2026)."""
    map_record(job_id)
    if payload.approve is not True:
        raise HTTPException(status_code=400, detail="Explicit approval is required to count the charge.")
    try:
        map_store().settle_unknown(job_id)
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
# 5 Nov 2026: reading Review's records from the shared database takes about a
# minute (hundreds of round trips). Review answers at once from its local copy
# and reads the database in the background; the page asks again while
# "syncing" is true. Only the first read for a store in this process (a fresh
# server, a test) waits, so an empty screen is never shown as the answer.
_review_sync_thread = None


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


def review_sync_running() -> bool:
    return _review_sync_thread is not None and _review_sync_thread.is_alive()


def start_review_sync_in_background(*, force: bool = True) -> bool:
    """Read Review's sources in a background thread; False if one is running."""
    global _review_sync_thread
    if review_sync_running():
        return False

    def run():
        try:
            _sync_review_candidates_now(force=force)
        except Exception:  # noqa: BLE001 - a failed refresh keeps the last copy
            logger.exception("Background Review synchronization failed")

    _review_sync_thread = Thread(target=run, name="review-sync", daemon=True)
    _review_sync_thread.start()
    return True


def _sync_review_candidates(*, force: bool = False):
    """Warnings from the last read of Review's sources, refreshing when stale.

    The first read for this store in this process runs before answering; after
    that a stale or forced refresh runs in the background and Review answers at
    once from its local copy (see review_sync_running()).
    """
    target = review_store()
    store_key = str(target.path.resolve())
    now = time.monotonic()
    fresh = (_review_sync_store_key == store_key
             and now - _review_sync_last < REVIEW_SYNC_INTERVAL_SECONDS)
    if fresh and not force:
        return list(_review_sync_warnings)
    if _review_sync_store_key == store_key or review_sync_running():
        start_review_sync_in_background(force=force)
        return list(_review_sync_warnings)
    return _sync_review_candidates_now(force=force)


def _sync_review_candidates_now(*, force: bool = False):
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
            if target.enable_test_canonical:
                # Tests and the demo build Review from map results directly.
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
                target.sync_external_candidates(
                    candidates, retired=getattr(postgres, "retired_keys", None))
                warnings.extend(source_warnings)
                target.set_sync_state("postgresql", success=not source_warnings,
                                      error="; ".join(source_warnings) or None)
            if not target.enable_test_canonical:
                # A map is reviewed on its own page, never in Review Results
                # (GHUS, 12 Nov 2026): its copies and saved records are folded away.
                target.retire_map_copies(local)
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
    reviewer: str = Field(default="", max_length=120)  # ignored: current_user() is recorded
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=5000)
    edited_payload: dict | None = None


class ReviewRejectionRequest(ReviewDecisionRequest):
    rejection_reason: str = Field(min_length=1, max_length=5000)


class ReviewCategoryRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=500)
    reviewer: str = Field(default="", max_length=120)  # ignored: current_user() is recorded
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=5000)
    categories: dict[str, str] = Field(default_factory=dict)


class ReviewItemDecisionRequest(BaseModel):
    decision_kind: str = Field(pattern="^(resolve_location|resolve_relationship)$")
    reviewer: str = Field(default="", max_length=120)  # ignored: current_user() is recorded
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=5000)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    keep_unlocated: bool = False
    approve: bool = False
    source_url: str | None = Field(default=None, max_length=2000)


class ReviewChangeRequest(BaseModel):
    choice: str = Field(min_length=1, max_length=20)
    reviewer: str = Field(default="", max_length=120)  # ignored: current_user() is recorded
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    notes: str | None = Field(default=None, max_length=5000)


class ReviewAdmissionRequest(ReviewDecisionRequest):
    decision_kind: str
    keep_both: bool = False
    target_id: str | None = None
    hub_ids: list[str] = Field(default_factory=list)
    proposed_hub: dict | None = None
    rejection_reason: str | None = None
    rejection_reason_other: str | None = Field(default=None, max_length=5000)
    # GHUS analyst notes, kept on the actor or event when it is verified.
    ghus_notes: str | None = Field(default=None, max_length=5000)


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
        mine = personal.keep(source.fetch_subscriptions(), "request", key="subscription_id")
        return {"subscriptions": mine, "configured": True}
    except PostgresReviewSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _raise_review_error(exc)


class SectorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    code: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    reviewer: str = Field(default="", max_length=120)  # ignored: current_user() is recorded


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
        outcome = bridge.apply({"decision_kind": "create_sector", **body.model_dump(),
                                "reviewer": current_user()})
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
    # Only the items from this person's own requests, imports and maps, and those
    # from before accounts (personal pages, 23 Nov 2026). Unknown owners: refused.
    hidden = personal.hidden_review_runs(review_store().source_run_ids())
    try:
        result = review_store().list(
            status=status, entity_type=entity_type,
            source_run_id=source_run_id, search=search,
            run_group=run_group, actor_category=actor_category,
            review_reason=review_reason, region=region, hidden_runs=hidden,
        )
        result["sync_warnings"] = sync_warnings
        # The database is being read in the background: the page asks again.
        result["syncing"] = review_sync_running()
        result["demo_banner"] = _demo_banner()
        result["admission_configured"] = review_admission_bridge().configured
        result["candidates"] = [_list_view(c) for c in result.get("candidates") or []]
        return result
    except Exception as exc:
        _raise_review_error(exc)


# What only an opened record needs. The list carried them for every record -
# the whole hub list alone 3.2 MB, fact histories 1.8 MB, 7.9 MB in all
# (2026-10-24) - and the page froze parsing it on every load and filter change.
# An opened record is read in full from /api/review/candidates/{id}.
_DETAIL_ONLY_METADATA = frozenset({
    "hubs", "fact_history", "facts", "relationships", "rubric", "score_breakdown",
    "page_facts", "pipeline", "fact_change", "top_matches", "hub_suggestions",
    "decided_changes", "evidence_items", "qualification_paths",
})


# The edit form of an opened record: constraints, original values, evidence.
_DETAIL_ONLY_FIELDS = frozenset({
    "original_payload", "field_constraints", "editable_fields", "rejection_reasons",
    "evidence",
})


def _list_view(candidate: dict) -> dict:
    light = {k: v for k, v in candidate.items() if k not in _DETAIL_ONLY_FIELDS}
    metadata = candidate.get("agent_metadata")
    if not isinstance(metadata, dict):
        return light
    meta = {k: v for k, v in metadata.items() if k not in _DETAIL_ONLY_METADATA}
    if isinstance(meta.get("quality"), dict):
        # The row shows completeness; the checks are read when it is opened.
        meta["quality"] = {"completeness": meta["quality"].get("completeness"),
                           "outcome": meta["quality"].get("outcome")}
    return {**light, "agent_metadata": meta}


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
    activity.note(decision="approve")
    try:
        return review_store().approve(
            candidate_id, reviewer=current_user(),
            idempotency_key=payload.idempotency_key, confirmed=payload.confirmed,
            notes=payload.notes, edited_payload=payload.edited_payload,
        )
    except Exception as exc:
        _raise_review_error(exc)


@app.post("/api/review/candidates/{candidate_id}/reject")
def review_candidate_reject(candidate_id: str, payload: ReviewRejectionRequest):
    activity.note(decision="reject", reason=payload.rejection_reason)
    try:
        return review_store().reject(
            candidate_id, reviewer=current_user(),
            rejection_reason=payload.rejection_reason,
            idempotency_key=payload.idempotency_key, confirmed=payload.confirmed,
            notes=payload.notes,
        )
    except Exception as exc:
        _raise_review_error(exc)


def _attribute_review(store, candidate_id: str, decision_kind: str, outcome: dict) -> None:
    """What the decision did, in its audit entry; a record it created gets its
    original owner: the importer when it came from a Data Feed import that has
    one, otherwise the person who verified it into the database."""
    try:
        candidate = store.get(candidate_id)
    except Exception:
        candidate = {}
    created = outcome.get("canonical_entity_id")
    activity.note(decision=decision_kind, result=outcome.get("status"),
                  record_type=candidate.get("entity_type"), record_name=candidate.get("display_name"),
                  canonical_entity_id=str(created) if created else None)
    source = str(candidate.get("source_run_id") or "")
    importer = activity.import_owner(source)
    words = {"new": "verified", "same_existing": "matched to an existing record", "reject": "rejected",
             "defer": "parked"}
    if importer and decision_kind in words:
        activity.notify_user(importer, key=f"decision:{candidate_id}:{decision_kind}", link="review",
                             title=f"'{candidate.get('display_name') or 'A record'}' from your import was "
                                   f"{words[decision_kind]}",
                             body=f"Decided in Review Results by {current_user()}.")
    if decision_kind == "new" and created and candidate.get("entity_type") in ("actor", "person", "event"):
        origin = ("imported" if source.startswith("datafeed:")
                  else "mapped" if source.startswith("v2-review:") else "discovered")
        activity.claim(candidate["entity_type"], created, origin, source_ref=f"review:{candidate_id}",
                       owner_user_id=importer)


@app.post("/api/review/candidates/{candidate_id}/decision")
def review_candidate_decision(candidate_id: str, payload: ReviewAdmissionRequest):
    store = review_store()
    try:
        decision = store.admission_request(
            candidate_id,
            decision_kind=payload.decision_kind,
            reviewer=current_user(),
            idempotency_key=payload.idempotency_key,
            target_id=payload.target_id,
            keep_both=payload.keep_both,
            notes=payload.notes,
            edited_payload=payload.edited_payload,
            hub_ids=payload.hub_ids,
            proposed_hub=payload.proposed_hub,
            rejection_reason=payload.rejection_reason,
            rejection_reason_other=payload.rejection_reason_other,
            confirmed=payload.confirmed,
            ghus_notes=payload.ghus_notes,
        )
        if decision.get("local_only"):
            # An actor update's card: what it wrote is already on the map.
            # The acknowledgement is kept in Review's own log; nothing is sent.
            outcome = {"decision_kind": decision["decision_kind"], "status": "applied",
                       "action": "looks_right" if decision["looks_right"] else "flagged",
                       "changes_to_map": "none"}
        else:
            outcome = review_admission_bridge().apply(decision)
            _directory_changed()
        _attribute_review(store, candidate_id, payload.decision_kind, outcome)
        return store.record_admission_success(
            candidate_id,
            idempotency_key=payload.idempotency_key,
            decision_kind=payload.decision_kind,
            reviewer=current_user(),
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


@app.post("/api/review/candidates/{candidate_id}/changes/{review_item_id}")
def review_candidate_change(candidate_id: str, review_item_id: str, payload: ReviewChangeRequest):
    """Decide one change on an actor's update profile.

    Keep the current value, use the new one, or keep both (locations only);
    confirm or refuse a proposed link or hub. Applied by the backend's approved
    writer: the current-fact pointer moves, both facts stay in the history.
    """
    store = review_store()
    try:
        UUID(review_item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown change.") from exc
    try:
        decision = store.change_request(
            candidate_id, review_item_id, choice=payload.choice, reviewer=current_user(),
            idempotency_key=payload.idempotency_key, notes=payload.notes,
            confirmed=payload.confirmed,
        )
        outcome = review_admission_bridge().apply(decision)
        updated = store.record_change_decision(
            candidate_id, review_item_id, choice=payload.choice, reviewer=current_user(),
            idempotency_key=payload.idempotency_key, notes=payload.notes, outcome=outcome,
        )
        # Re-read the map so the boxes show the value now current.
        try:
            _sync_review_candidates(force=True)
            updated = store.get(candidate_id)
        except Exception:
            logger.exception("Review re-read after a change decision failed")
        return updated
    except Exception as exc:
        _raise_review_error(exc)


# ---------------------------------------------------------------- discovery
# Actor discovery runs only for requests made here. The page never writes the
# request tables: every call goes through the backend's own command, which
# applies the same rules as the scheduler and the database.

class DiscoveryDraft(BaseModel):
    # Empty on a People request: the backend names it from the description, and
    # refuses any other request without a name.
    title: str = Field(default="", max_length=160)
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
    # What the request finds. Left out, it is an organization request exactly
    # as before; events and people carry their own scope (backend migration 580,
    # validated by agents/collection/subscriptions.py).
    discovery_entity: Literal["actor", "event", "person"] | None = None
    discovery_options: dict[str, Any] | None = None
    # Who asked: emailed about findings, and the only one who sees the request.
    requested_by: str | None = Field(default=None, max_length=254)


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


def _own_requests(payload):
    """Only the signed-in person's requests (and those from before accounts), and
    only their one-off organization updates (personal pages, 23 Nov 2026). A new
    dict: the cached list is shared and never changed."""
    if not isinstance(payload, dict):
        return payload
    out = {**payload, "requests": personal.keep(payload.get("requests") or [], "request",
                                                key="subscription_id")}
    if "one_time" in payload:
        out["one_time"] = personal.keep_checks(payload.get("one_time") or [])
    return out


@app.get("/api/discovery/requests")
def discovery_requests():
    return _own_requests(_discovery_call(discovery_bridge().list_requests))


@app.post("/api/discovery/preview")
def discovery_preview(draft: DiscoveryDraft):
    return _discovery_call(discovery_bridge().preview, draft.model_dump(exclude_none=True))


@app.post("/api/discovery/requests")
def discovery_create(draft: DiscoveryDraft):
    answer = _discovery_call(discovery_bridge().create, _as_requester(draft))
    created = activity.subscription_id(answer)
    activity.claim("request", created, "requested")
    activity.note(entity_type="request", entity_id=created, request_kind="discovery")
    return answer


@app.post("/api/discovery/requests/{subscription_id}/run")
def discovery_run_now(subscription_id: str):
    """Start a live run of one request now. A person pressing the button is the
    explicit dispatch a live run requires; the run itself takes minutes."""
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    # One run at a time per person (12 Nov 2026): who pressed it is the sign-in.
    answer = _discovery_call(lambda sid: discovery_bridge().run_now(sid, user=current_user()),
                             subscription_id)
    # Its cost goes to whoever pressed it (accounts Phase 5; nothing without accounts).
    activity.record_usage("run_now", f"{subscription_id}:{time.time_ns()}", trigger="run_now",
                          detail={"subscription_id": subscription_id})
    return answer


class EndDateChange(BaseModel):
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@app.post("/api/discovery/requests/{subscription_id}/end-date")
def discovery_end_date(subscription_id: str, change: EndDateChange):
    """Extend or shorten an active or paused recurring request's monitoring period."""
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    return _discovery_call(discovery_bridge().set_end_date, subscription_id, change.end_date)


# ------------------------------------------------------- specific actor updates
# Refresh what the map says about ONE existing actor - its funding, its recent
# activity, or every box - from its own pages. Search is a read-only query; the
# update itself runs in the GHUS backend, which writes through its approved
# fact writer. The page never writes canonical data.

class ActorUpdateRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=20)
    scope: str = Field(default="general", max_length=20)
    depth: str = Field(default="light", max_length=10)
    fields: list[str] = Field(default_factory=list, max_length=40)
    categories: list[str] = Field(default_factory=list, max_length=10)
    focus: str = Field(default="", max_length=200)


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
        raise HTTPException(status_code=503, detail="Organization search is not available on this instance.")
    try:
        return source.search_actors(q, sector=sector, category=category, state=state,
                                    updatable_only=not everyone, limit=limit)
    except PostgresReviewSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _actor_update_call(actor_id: str, step: str, payload: ActorUpdateRequest):
    try:
        UUID(actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown organization") from exc
    bridge = discovery_bridge()
    call = bridge.plan_update if step == "plan" else bridge.check_update
    return _discovery_call(lambda: call(actor_id, payload.model_dump()))


@app.post("/api/discovery/actors/{actor_id}/plan")
def discovery_actor_plan(actor_id: str, payload: ActorUpdateRequest):
    """What an update would do: boxes, Deep Pull gate, cost. Free; writes nothing."""
    return _actor_update_call(actor_id, "plan", payload)


@app.post("/api/discovery/actors/{actor_id}/check")
def discovery_actor_check(actor_id: str, payload: ActorUpdateRequest):
    """Read the actor's own pages once (capped) and compare. Writes nothing."""
    answer = _actor_update_call(actor_id, "check", payload)
    if isinstance(answer, dict) and answer.get("check_id"):
        cost = answer.get("cost_usd")
        activity.record_usage("actor_check", answer["check_id"],
                              cost_usd=float(cost) if cost is not None else None,
                              cost_basis="check_result" if cost is not None else "unknown",
                              detail={"actor_id": actor_id, "actor_name": answer.get("actor_name")})
    return answer


@app.post("/api/discovery/actor-checks/{check_id}/apply")
def discovery_actor_apply(check_id: str):
    """Write what a check found, through the backend's approved fact writer."""
    if not re.fullmatch(r"[0-9a-f]{32}", check_id or ""):
        raise HTTPException(status_code=404, detail="unknown check")
    return _discovery_call(discovery_bridge().apply_update, check_id)


# ------------------------------------------------------- actor update requests
# Keep chosen actors current: one actor or a bounded group, once or on a
# frequency, within an actor cap and a spend ceiling per run. Saved as a
# request in the GHUS backend and run by its request runner (the same one as
# Discovery requests); the page never writes these tables itself.

class UpdateRequestGroup(BaseModel):
    sector: str | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=60)
    state: str | None = Field(default=None, max_length=4)


class UpdateRequestDraft(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    actor_ids: list[str] = Field(default_factory=list, max_length=50)
    group: UpdateRequestGroup | None = None
    topic: str | None = Field(default=None, max_length=20)
    scope: str = Field(default="general", max_length=20)
    depth: str = Field(default="light", max_length=10)
    categories: list[str] = Field(default_factory=list, max_length=10)
    fields: list[str] = Field(default_factory=list, max_length=40)
    focus: str = Field(default="", max_length=1000)
    cadence: str = Field(default="once", max_length=20)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    max_actors_per_run: int | None = Field(default=None, ge=1, le=50)
    max_usd_per_run: float | None = Field(default=None, gt=0, le=5)
    requested_by: str | None = Field(default=None, max_length=254)


@app.get("/api/discovery/update-requests")
def discovery_update_requests():
    bridge = discovery_bridge()
    payload = _discovery_call(bridge.list_update_requests)
    # Run now's start, shown as running until the run record appears.
    mark = getattr(bridge, "mark_starting", None)
    return _own_requests(mark(payload) if mark else payload)


@app.post("/api/discovery/update-requests/plan")
def discovery_update_request_plan(draft: UpdateRequestDraft):
    """Which actors a request would read first, its cost and its runs. Free."""
    return _discovery_call(discovery_bridge().plan_update_request,
                           draft.model_dump(exclude_none=True))


@app.post("/api/discovery/update-requests")
def discovery_update_request_create(draft: UpdateRequestDraft):
    answer = _discovery_call(discovery_bridge().create_update_request, _as_requester(draft))
    created = activity.subscription_id(answer)
    activity.claim("request", created, "requested")
    activity.note(entity_type="request", entity_id=created, request_kind="actor_update")
    return answer


def _as_requester(draft) -> dict:
    """A request is the current user's: emailed to their account's address, never a typed one."""
    body = draft.model_dump(exclude_none=True)
    body.pop("requested_by", None)
    email = current_user_email()
    if email:
        body["requested_by"] = email
    return body


@app.post("/api/discovery/update-requests/{subscription_id}/{action}")
def discovery_update_request_change(subscription_id: str, action: str):
    """Pause, resume or cancel - or "run": run it now, live, in the background."""
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    if action == "run":
        answer = _discovery_call(lambda sid: discovery_bridge().run_now(sid, user=current_user()),
                                 subscription_id)
        activity.record_usage("run_now", f"{subscription_id}:{time.time_ns()}", trigger="run_now",
                              detail={"subscription_id": subscription_id})
        return answer
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(status_code=404, detail="unknown action")
    return _discovery_call(discovery_bridge().change_update_request, subscription_id, action)


@app.post("/api/discovery/requests/{subscription_id}/{action}")
def discovery_change(subscription_id: str, action: str):
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(status_code=404, detail="unknown action")
    try:
        UUID(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown request") from exc
    return _discovery_call(discovery_bridge().change, subscription_id, action)


@app.post("/api/review/candidates/{candidate_id}/review-item-decision")
def review_item_decision(candidate_id: str, payload: ReviewItemDecisionRequest):
    """Resolve a V2 location or relationship review item through GHUS."""
    store = review_store()
    try:
        request = store.review_item_decision_request(
            candidate_id, **{**payload.model_dump(), "reviewer": current_user()})
        outcome = review_admission_bridge().apply(request)
        _directory_changed()
        return store.record_review_item_success(request, outcome)
    except Exception as exc:
        _raise_review_error(exc)


@app.post("/api/review/category-decisions")
def review_category_decisions(payload: ReviewCategoryRequest):
    """Confirm GHUS actor categories for one or many category_doubt reviews at once."""
    # The items are named in the body: each must be this person's (personal pages).
    if not all(personal.may_open_candidate(cid) for cid in payload.candidate_ids):
        raise HTTPException(status_code=404, detail="Not found.")
    store = review_store()
    try:
        request = store.category_decision_request(
            payload.candidate_ids,
            reviewer=current_user(),
            idempotency_key=payload.idempotency_key,
            notes=payload.notes,
            categories=payload.categories,
            confirmed=payload.confirmed,
        )
        outcome = review_admission_bridge().apply(request)
        _directory_changed()
        return {"outcome": outcome, "candidates": store.record_category_success(request, outcome)}
    except Exception as exc:
        _raise_review_error(exc)


@app.get("/api/health")
def health():
    return {"ok": True}


# Data Feed: spreadsheet and manual records, staged for Review by the backend.
app.include_router(datafeed_router)
# A Data Feed import stored in the Directory shows on its next read.
datafeed_routes.directory_changed = _directory_changed


# ------------------------------------------------------------- My work (accounts Phase 3)
# What the signed-in person brought into Compass, and what they decided. Read from
# the session only: there is no way to ask for someone else's. The shared records
# themselves are not copied: these are lists of ids, named from the shared lists.
def _names_of(kind: str) -> dict[str, str]:
    try:
        if kind == "actor":
            return {str(a["id"]): a["name"] for a in _actors()}
        if kind == "event":
            return {str(e["id"]): e["name"] for e in _events()}
        if kind == "person":
            return {str(p["id"]): p["name"] for p in _people()}
        if kind == "hub":
            return {str(h.get("hub_id")): h.get("name") for h in _hubs()}
        if kind == "map":
            return {str(m["id"]): m.get("description") or "Untitled map" for m in map_store().recent()}
        if kind == "request":
            bridge, out = discovery_bridge(), {}
            for listing in (bridge.list_requests(), bridge.list_update_requests()):
                for r in (listing or {}).get("requests") or []:
                    rid = r.get("subscription_id") or r.get("actor_update_subscription_id") or r.get("id")
                    out[str(rid)] = r.get("title") or r.get("name") or "Untitled request"
            return out
        if kind == "import":
            from backend.datafeed_routes import datafeed_service
            return {str(i.get("run_id")): i.get("import_name") or "Untitled import"
                    for i in datafeed_service().history()}
    except Exception:
        logger.warning("Could not name %s records for My work", kind, exc_info=True)
    return {}


@app.get("/api/account/mine")
def account_mine():
    """My Records, My Requests, My Maps, My Imports: what I brought in, newest first."""
    from backend.accounts_routes import accounts_store
    from src.identity import current_account

    me = current_account()
    if me is None:
        return {"signed_in": False, "records": [], "requests": [], "maps": [], "imports": []}
    owned = accounts_store().owned_by(me.user_id)
    groups = {"records": [], "requests": [], "maps": [], "imports": []}
    names: dict[str, dict[str, str]] = {}
    for item in owned:
        kind = item["entity_type"]
        if kind not in names:
            names[kind] = _names_of(kind)
        name = names[kind].get(str(item["entity_id"]))
        group = ("requests" if kind == "request" else "maps" if kind == "map"
                 else "imports" if kind == "import" else "records")
        groups[group].append({**item, "name": name,
                              "note": None if name else "Not in the current list (removed, or not loaded)"})
    return {"signed_in": True, **groups}


# What counts as a review decision for My Review History.
REVIEW_ACTIONS = ("review.", "map.save", "map.review", "browse.", "datafeed.previews_confirm")


# ------------------------------------------------------------- Usage and costs (Phase 5)
# Costs are read from the ledgers that hold them (src/accounts/usage.py); nothing
# is copied. One's own usage needs usage.view_own; everyone's, usage.view_all.
def _usage_ops(store):
    from src.accounts import usage
    try:
        with map_store().connect() as map_db:
            return usage.operations(store, map_db), map_db_ok(map_db)
    except Exception:
        logger.warning("Map store unavailable for usage; map costs left out", exc_info=True)
        return usage.operations(store, None), False


def map_db_ok(map_db) -> bool:
    try:
        map_db.execute("SELECT 1 FROM calls LIMIT 1")
        return True
    except Exception:
        return False


def _month_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ops_json(ops) -> list[dict]:
    return [{**o, "started_at": o["started_at"].isoformat() if o.get("started_at") else None} for o in ops]


@app.get("/api/account/usage")
def account_usage(months: int = Query(6, ge=1, le=24)):
    """My usage: this month's spending and runs, recent paid operations, monthly history."""
    from src.accounts import usage
    store, me = _accounts_or_none()
    if me is None:
        return {"signed_in": False}
    ops, _ = _usage_ops(store)
    mine = usage.filtered(ops, user_id=me.user_id)
    month = _month_now()
    this_month = usage.filtered(mine, since=month, until=month)
    counts = store.monthly_counts(me.user_id)
    by_month = usage.summary(mine)["by_month"]
    history_months = sorted(set(by_month) | set(counts))[-months:]
    return {
        "signed_in": True, "month": month,
        "this_month": {**usage.summary(this_month)["total"],
                       "by_feature": usage.summary(this_month)["by_feature"],
                       **counts.get(month, {})},
        "recent": _ops_json(usage.newest_first(mine)[:15]),
        "history": [{"month": m, **by_month.get(m, {"cost_usd": 0, "not_final_usd": 0, "operations": 0}),
                     **counts.get(m, {})} for m in history_months],
    }


def _admin_filters(since, until, user_id, feature, unattributed):
    import re as _re
    for value in (since, until):
        if value and not _re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise HTTPException(status_code=422, detail="Months are written YYYY-MM.")
    return {"since": since or None, "until": until or None, "user_id": user_id or None,
            "feature": feature or None, "unattributed": unattributed}


@app.get("/api/admin/usage")
def admin_usage(since: str | None = None, until: str | None = None, user_id: str | None = None,
                feature: str | None = None, unattributed: bool = False):
    """Platform spending: totals, by person and month, by feature, counts, Not recorded,
    and the reconciliation with each ledger."""
    from src.accounts import usage
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    filters = _admin_filters(since, until, user_id, feature, unattributed)
    ops, map_ok = _usage_ops(store)
    chosen = usage.filtered(ops, **filters)
    try:
        with map_store().connect() as map_db:
            reconciliation = usage.reconcile(store, ops, map_db)
    except Exception:
        reconciliation = usage.reconcile(store, ops, None)
    return {
        "filters": filters, "summary": usage.summary(chosen),
        "not_recorded": usage.summary(usage.filtered(ops, unattributed=True,
                                                     since=filters["since"], until=filters["until"]))["total"],
        "counts": store.monthly_counts(filters["user_id"]),
        "reconciliation": reconciliation, "map_costs_included": map_ok,
        "people": [{"user_id": k, "name": v} for k, v in sorted(store.people().items(), key=lambda kv: kv[1])],
        "features": sorted({o["feature"] for o in ops}),
        "operations": _ops_json(usage.newest_first(chosen)[:500]),
    }


@app.get("/api/admin/usage/export")
def admin_usage_export(format: str = Query("csv", pattern="^(csv|xlsx)$"), since: str | None = None,
                       until: str | None = None, user_id: str | None = None, feature: str | None = None,
                       unattributed: bool = False):
    """The filtered operations as CSV or Excel (with by-person and by-feature sheets)."""
    from fastapi.responses import Response
    from src.accounts import usage
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    filters = _admin_filters(since, until, user_id, feature, unattributed)
    ops, _ = _usage_ops(store)
    chosen = usage.filtered(ops, **filters)
    name = f"compass-usage-{filters['since'] or 'all'}-{filters['until'] or 'now'}"
    if format == "csv":
        return Response(usage.to_csv(chosen), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return Response(usage.to_xlsx(chosen, usage.summary(chosen)),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


# ----------------------------------------------- Dashboard, notifications, preferences (Phase 4)
def _datafeed():
    from backend.datafeed_routes import datafeed_service
    return datafeed_service()


def _my_sync(store, me) -> None:
    """Bring this person's notifications up to date from their own work (at most once a
    minute), and give their imports' late records their owner."""
    from src.accounts.notifier import sync_for

    try:
        owned = store.owned_by(me.user_id)
        map_ids = {o["entity_id"] for o in owned if o["entity_type"] == "map"}
        import_ids = {o["entity_id"] for o in owned if o["entity_type"] == "import"}
        maps = [m for m in map_store().recent() if str(m["id"]) in map_ids] if map_ids else []
        imports = []
        if import_ids:
            try:
                imports = [i for i in _datafeed().history() if str(i.get("run_id")) in import_ids]
            except Exception:
                logger.warning("Import history unavailable for notifications", exc_info=True)
        sync_for(store, me.user_id, maps=maps, imports=imports,
                 created_entities=_datafeed().created_entities if import_ids else None)
    except Exception:
        logger.exception("Notification sync failed for %s", me.user_id)


def _accounts_or_none():
    from backend.accounts_routes import accounts_store
    from src.identity import current_account
    me = current_account()
    return (accounts_store(), me) if me else (None, None)


@app.get("/api/account/notifications")
def account_notifications(unread: bool = False):
    store, me = _accounts_or_none()
    if me is None:
        return {"signed_in": False, "unread": 0, "items": []}
    _my_sync(store, me)
    return {"signed_in": True, **store.notifications(me.user_id, unread_only=unread)}


@app.post("/api/account/notifications/read-all")
def account_notifications_read_all():
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return {"marked": store.mark_read(me.user_id)}


@app.post("/api/account/notifications/{notification_id}/read")
def account_notification_read(notification_id: int):
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    # Only one's own: another person's notification is simply not found.
    if not store.mark_read(me.user_id, notification_id):
        raise HTTPException(status_code=404, detail="No such unread notification.")
    return {"marked": 1}


class PreferencesChange(BaseModel):
    preferences: dict


@app.get("/api/account/preferences")
def account_preferences():
    from src.accounts.preferences import NOTIFY_KINDS, dashboard_choices
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return {"preferences": store.preferences(me.user_id), "notification_kinds": NOTIFY_KINDS,
            "dashboard_sections": dashboard_choices(me.permissions)}


@app.put("/api/account/preferences")
def account_preferences_update(change: PreferencesChange):
    from src.accounts.preferences import PreferenceError, merge
    store, me = _accounts_or_none()
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    try:
        merged = merge(store.preferences(me.user_id), change.preferences)
    except PreferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.set_preferences(me.user_id, merged)
    return {"preferences": merged}


@app.get("/api/account/record-trail")
def account_record_trail(entity_type: str = Query(..., pattern="^(actor|person|event|hub)$"),
                         entity_id: str = Query(..., min_length=1, max_length=80)):
    """Original owner, reviewer and last editor of one shared record: three roles, kept apart."""
    store, me = _accounts_or_none()
    if me is None:
        return {"owner": None, "reviewed_by": None, "last_edited_by": None}
    return store.record_trail(entity_type, entity_id)


@app.get("/api/account/dashboard")
def account_dashboard():
    """Everything the personal Dashboard shows, in one call, for the signed-in person."""
    store, me = _accounts_or_none()
    if me is None:
        return {"signed_in": False}
    _my_sync(store, me)
    mine = account_mine()
    preferences = store.preferences(me.user_id)
    owned_maps = {m["entity_id"] for m in mine["maps"]}
    maps = [m for m in map_store().recent() if str(m["id"]) in owned_maps] if owned_maps else []
    active = {"running", "planning", "verifying"}
    runs = [{"kind": "map", "id": m["id"], "name": m.get("description") or "Untitled map",
             "status": m.get("status"), "at": m.get("updated")} for m in maps
            if m.get("status") in active | {"done", "error", "interrupted", "budget_stopped", "cancelled"}]
    runs += [{"kind": "request", "id": r["run_id"], "name": r["title"], "status": r["status"],
              "at": r["finished_at"] or r["started_at"]} for r in store.request_runs(me.user_id)]
    sectors = []
    if preferences["sectors"] and me.can("records.view"):
        by_hub = _sectors_by_hub()
        for sector in preferences["sectors"]:
            count = sum(1 for a in _without_deleted(_actors(), "actor")
                        if any(sector in by_hub.get(h, []) for h in a.get("hubs", [])))
            sectors.append({"sector": sector, "organizations": count})
    return {
        "signed_in": True,
        "name": me.full_name, "role_label": me.role_label, "permissions": sorted(me.permissions),
        "hidden": preferences["dashboard"]["hidden"],
        "notifications": store.notifications(me.user_id, limit=8),
        "running": [r for r in runs if r["status"] in active],
        "recent_runs": [r for r in runs if r["status"] not in active][:8],
        "activity": [e for e in store.audit_entries(user_id=me.user_id, limit=40)
                     if not e["action"].startswith(("auth.", "access."))][:10],
        "counts": {k: len(mine[k]) for k in ("records", "requests", "maps", "imports")},
        "records": mine["records"][:5], "requests": mine["requests"][:5], "maps": mine["maps"][:5],
        "imports": mine["imports"][:5],
        "reviews": store.audit_entries(user_id=me.user_id, actions=REVIEW_ACTIONS, limit=5),
        "sectors": sectors,
    }


@app.get("/api/account/review-history")
def account_review_history(limit: int = Query(200, ge=1, le=1000)):
    """My Review History: what I verified, rejected, parked, edited or removed."""
    from backend.accounts_routes import accounts_store
    from src.identity import current_account

    me = current_account()
    if me is None:
        return {"signed_in": False, "history": []}
    return {"signed_in": True,
            "history": accounts_store().audit_entries(user_id=me.user_id, actions=REVIEW_ACTIONS,
                                                      limit=limit)}


# ---------------------------------------------------------------- static frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


# Mounted last so the /api routes above take precedence.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
