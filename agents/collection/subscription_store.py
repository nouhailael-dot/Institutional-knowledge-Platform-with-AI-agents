"""The one writer for discovery requests and their run records.

Every write to ``actor_update_subscription``, ``actor_update_subscription_run``
and the subscription-triggered ``collection_run`` / ``collection_request`` rows
happens here, and nowhere else (enforced by the protected-table allowlist test).
None of these are canonical entities: a request says what to look for, a run
record says what was looked at. Actors themselves are still created only by
``agents/discovery/promote.py``, as Parked records awaiting a GHUS person.

Writes happen only when ``live=True``. Without it every function validates and
returns what it would have written, and the database is untouched.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import text

from agents.collection.subscriptions import (
    ACTIVE,
    CANCELLED,
    DISCOVERY_PAGE,
    EXPIRED,
    PAUSED,
    Subscription,
    SubscriptionError,
)

# Which status changes a person may make. Expired and cancelled are final: a
# finished request is not revived, a new one is made.
_TRANSITIONS: dict[str, dict[str, str]] = {
    "pause": {ACTIVE: PAUSED},
    "resume": {PAUSED: ACTIVE},
    "cancel": {ACTIVE: CANCELLED, PAUSED: CANCELLED},
}
_SUBSCRIPTION_COLUMNS = (
    "actor_update_subscription_id::text AS subscription_id, actor_ids::text[] AS actor_ids, "
    "sector_codes, topic_ids::text[] AS topic_ids, country, state_code, city, region_code, "
    "start_date, end_date, cadence, requested_by, requested_via, status, last_run_at, "
    "next_due_at, created_at, title, focus_terms, max_new_actors_per_run"
)


@dataclass(frozen=True)
class WriteResult:
    live: bool
    subscription_id: str | None
    statement: str
    values: dict[str, object]


def _today() -> date:
    return datetime.now(UTC).date()


def subscription_from_row(row: Mapping[str, object]) -> Subscription:
    last_run = row.get("last_run_at")
    if isinstance(last_run, datetime):
        last_run = last_run.date()
    return Subscription(
        subscription_id=str(row["subscription_id"]),
        start_date=row["start_date"],
        end_date=row["end_date"],
        cadence=str(row["cadence"]),
        requested_via=str(row["requested_via"]),
        status=str(row["status"]),
        actor_ids=tuple(row.get("actor_ids") or ()),
        sector_codes=tuple(row.get("sector_codes") or ()),
        topic_ids=tuple(row.get("topic_ids") or ()),
        country=row.get("country"),
        state_code=row.get("state_code"),
        city=row.get("city"),
        region_code=row.get("region_code"),
        requested_by=row.get("requested_by"),
        last_run_at=last_run,
        title=row.get("title"),
        focus_terms=tuple(row.get("focus_terms") or ()),
        max_new_actors_per_run=int(row.get("max_new_actors_per_run") or 10),
    )


# ------------------------------------------------------------------- reading

def load_discovery_requests(session, *, include_finished: bool = True) -> list[dict[str, object]]:
    sql = (
        f"SELECT {_SUBSCRIPTION_COLUMNS} FROM actor_update_subscription "
        "WHERE requested_via = :via"
    )
    if not include_finished:
        sql += " AND status IN ('active', 'paused')"
    sql += " ORDER BY created_at DESC"
    return [dict(row) for row in session.execute(text(sql), {"via": DISCOVERY_PAGE}).mappings()]


def load_request_runs(session, subscription_id: str, *, limit: int = 20) -> list[dict[str, object]]:
    rows = session.execute(text(
        "SELECT cr.collection_run_id::text AS collection_run_id, cr.status, cr.dry_run, "
        "cr.started_at, cr.finished_at, cr.found_count, cr.deduplicated_count, "
        "cr.staged_count, cr.review_item_count, cr.status_reason, cr.spent_usd, "
        "cr.config_snapshot->>'search_run_id' AS search_run_id "
        "FROM actor_update_subscription_run sr "
        "JOIN collection_run cr ON cr.collection_run_id = sr.collection_run_id "
        "WHERE sr.actor_update_subscription_id = CAST(:id AS uuid) "
        "ORDER BY cr.started_at DESC LIMIT :limit"
    ), {"id": subscription_id, "limit": limit}).mappings()
    return [dict(row) for row in rows]


def load_request_results(session, search_run_ids, *, limit: int = 50) -> list[dict[str, object]]:
    """The organisations a request's runs added to the map or sent to review.

    Rejected candidates are not listed: they never reached the map or the
    queue, and the run's counts already say how many there were.
    """

    ids = [str(i) for i in search_run_ids if i]
    if not ids:
        return []
    rows = session.execute(text(
        "SELECT candidate_id::text AS candidate_id, run_id::text AS search_run_id, url, "
        "record_preview->>'name' AS name, record_preview->>'website' AS website, "
        "record_preview->>'description' AS description, fit_score, score_band, "
        "record_preview->>'location_city' AS city, record_preview->>'state' AS state, "
        "record_preview->>'country' AS country, record_preview->>'actor_category' AS category, "
        "record_preview->>'primary_technical_focus' AS focus, "
        "record_preview->>'current_activities' AS activities, "
        "record_preview->>'funding_summary' AS funding, "
        "record_preview->>'match_reason' AS why_matched, "

        "(score_breakdown->>'priority_score')::float AS priority, "
        "triage_reason, created_at FROM search_candidate "
        "WHERE run_id = ANY(CAST(:ids AS uuid[])) AND entity_type = 'actor' "
        "AND score_band IN ('auto_high', 'review') "
        "ORDER BY score_band = 'auto_high' DESC, fit_score DESC NULLS LAST LIMIT :limit"
    ), {"ids": ids, "limit": limit}).mappings()
    return [dict(row) for row in rows]


def load_request_exclusions(session, search_run_ids, *, limit: int = 300) -> list[dict[str, object]]:
    """Every candidate a request's runs did NOT keep, with the recorded reason.

    Exclusion is never silent: rejected, not read (budget, limits), superseded
    by an official-site read, failed to load, or held back by the per-run cap -
    each carries the sentence that says why.
    """
    ids = [str(i) for i in search_run_ids if i]
    if not ids:
        return []
    rows = session.execute(text(
        "SELECT url, COALESCE(record_preview->>'name', title) AS name, triage_verdict, "
        "score_band, fit_score, triage_reason FROM search_candidate "
        "WHERE run_id = ANY(CAST(:ids AS uuid[])) AND entity_type = 'actor' "
        "AND COALESCE(score_band, '') NOT IN ('auto_high', 'review') "
        "ORDER BY fit_score DESC NULLS LAST LIMIT :limit"
    ), {"ids": ids, "limit": limit}).mappings()
    return [dict(row) for row in rows]


def search_run_since(session, started) -> tuple[str | None, float]:
    """The open-web actor search run started at or after ``started``, and its cost.

    Used when a run fails before returning its own figures. Only one runner
    holds the advisory lock at a time, so the first such run is this one.
    """
    row = session.execute(text(
        "SELECT run_id::text AS run_id, COALESCE(cost_usd, 0) AS cost FROM scrape_run "
        "WHERE source_name = 'open_web_search' AND entity_type = 'actor' "
        "AND started_at >= :started ORDER BY started_at LIMIT 1"
    ), {"started": started}).mappings().first()
    if row is None:
        return None, 0.0
    return str(row["run_id"]), float(row["cost"])


def topic_codes(session) -> dict[str, str]:
    return {
        str(row["topic_id"]): str(row["code"])
        for row in session.execute(text(
            "SELECT topic_id::text AS topic_id, code FROM topic WHERE active"
        )).mappings()
    }


# ------------------------------------------------------- what a person changes

def create_request(
    session,
    *,
    title: str,
    end_date: date,
    cadence: str,
    sector_codes: Iterable[str] = (),
    topic_ids: Iterable[str] = (),
    focus_terms: Iterable[str] = (),
    region_code: str | None = None,
    state_code: str | None = None,
    city: str | None = None,
    start_date: date | None = None,
    max_new_actors_per_run: int = 10,
    requested_by: str | None = None,
    live: bool = False,
) -> WriteResult:
    """Validate a Discovery-page request and, when live, record it.

    Validation is the planner's own (``Subscription``), so the page, this
    module and the database constraints all refuse the same things.
    """

    candidate = Subscription(
        subscription_id="new",
        start_date=start_date or _today(),
        end_date=end_date,
        cadence=cadence,
        requested_via=DISCOVERY_PAGE,
        sector_codes=tuple(code.strip().upper() for code in sector_codes if code.strip()),
        topic_ids=tuple(str(t) for t in topic_ids if str(t).strip()),
        state_code=(state_code or "").strip().upper() or None,
        city=(city or "").strip() or None,
        region_code=(region_code or "").strip() or None,
        title=title.strip(),
        focus_terms=tuple(dict.fromkeys(t.strip() for t in focus_terms if t.strip())),
        max_new_actors_per_run=int(max_new_actors_per_run),
        requested_by=requested_by,
    )
    values = {
        "title": candidate.title,
        "sector_codes": list(candidate.sector_codes) or None,
        "topic_ids": list(candidate.topic_ids) or None,
        "focus_terms": list(candidate.focus_terms),
        "region_code": candidate.region_code,
        "state_code": candidate.state_code,
        "city": candidate.city,
        "start_date": candidate.start_date,
        "end_date": candidate.end_date,
        "cadence": candidate.cadence,
        "requested_via": DISCOVERY_PAGE,
        "requested_by": requested_by,
        "max_new_actors_per_run": candidate.max_new_actors_per_run,
        "next_due_at": candidate.start_date,
    }
    statement = (
        "INSERT INTO actor_update_subscription (title, sector_codes, topic_ids, focus_terms, "
        "region_code, state_code, city, start_date, end_date, cadence, requested_via, "
        "requested_by, max_new_actors_per_run, next_due_at) VALUES (:title, :sector_codes, "
        "CAST(:topic_ids AS uuid[]), :focus_terms, :region_code, :state_code, :city, "
        ":start_date, :end_date, :cadence, :requested_via, :requested_by, "
        ":max_new_actors_per_run, :next_due_at) "
        "RETURNING actor_update_subscription_id::text"
    )
    if not live:
        return WriteResult(False, None, statement, values)
    new_id = session.execute(text(statement), values).scalar_one()
    session.commit()
    return WriteResult(True, str(new_id), statement, values)


def change_status(session, subscription_id: str, action: str, *, live: bool = False) -> WriteResult:
    """Pause, resume or cancel. Refuses a change the current status does not allow."""

    allowed = _TRANSITIONS.get(action)
    if allowed is None:
        raise SubscriptionError(f"unknown action {action!r}; use pause, resume or cancel")
    row = session.execute(text(
        "SELECT status, requested_via FROM actor_update_subscription "
        "WHERE actor_update_subscription_id = CAST(:id AS uuid)"
    ), {"id": subscription_id}).mappings().first()
    if row is None:
        raise SubscriptionError(f"no request {subscription_id}")
    if row["requested_via"] != DISCOVERY_PAGE:
        raise SubscriptionError("only Discovery-page requests are managed here")
    new_status = allowed.get(str(row["status"]))
    if new_status is None:
        raise SubscriptionError(f"a {row['status']} request cannot be {action}d")
    values = {"id": subscription_id, "status": new_status, "old": row["status"]}
    statement = (
        "UPDATE actor_update_subscription SET status = :status, updated_at = now(), "
        "next_due_at = CASE WHEN :status = 'active' THEN GREATEST(current_date, start_date) "
        "ELSE NULL END "
        "WHERE actor_update_subscription_id = CAST(:id AS uuid) AND status = :old"
    )
    if not live:
        return WriteResult(False, subscription_id, statement, values)
    if session.execute(text(statement), values).rowcount != 1:
        session.rollback()
        raise SubscriptionError("the request changed while it was being updated; try again")
    session.commit()
    return WriteResult(True, subscription_id, statement, values)


# ---------------------------------------------------------- what a run records

def ensure_collection_request(session, subscription: Subscription, topic_id: str | None) -> str:
    """The WS4 collection request a requested discovery run belongs to.

    One per request, created on its first run. ``approved`` is left false: no
    authenticated identity exists yet to attribute an approval to.
    """

    need = f"Discovery request {subscription.subscription_id}: {subscription.title or ''}".strip()
    existing = session.execute(text(
        "SELECT collection_request_id::text FROM collection_request "
        "WHERE requested_by = 'discovery_page' AND need_text = :need LIMIT 1"
    ), {"need": need}).scalar()
    if existing:
        return str(existing)
    return str(session.execute(text(
        "INSERT INTO collection_request (requested_by, request_kind, topic_id, need_text, layer) "
        "VALUES ('discovery_page', 'mapping', CAST(:topic AS uuid), :need, 1) "
        "RETURNING collection_request_id::text"
    ), {"topic": topic_id, "need": need}).scalar_one())


def start_run(
    session,
    *,
    collection_request_id: str,
    subscription: Subscription,
    fetch_budget: int,
    max_usd: float | None,
    config_snapshot: Mapping[str, object],
) -> str:
    return str(session.execute(text(
        "INSERT INTO collection_run (collection_request_id, job_name, dry_run, status, "
        "fetch_budget, max_usd, trigger_type, cadence, initiated_by, config_snapshot) "
        "VALUES (CAST(:request AS uuid), 'discovery_request', false, 'running', :budget, "
        ":max_usd, 'subscription', :cadence, 'discovery_page', CAST(:snapshot AS jsonb)) "
        "RETURNING collection_run_id::text"
    ), {
        "request": collection_request_id,
        "budget": int(fetch_budget),
        "max_usd": max_usd,
        "cadence": subscription.cadence,
        "snapshot": json.dumps(dict(config_snapshot), default=str),
    }).scalar_one())


def finish_run(
    session,
    *,
    collection_run_id: str,
    subscription: Subscription,
    status: str,
    status_reason: str | None,
    counts: Mapping[str, int],
    fetch_count: int,
    spent_usd: float,
    search_run_id: str | None = None,
) -> None:
    session.execute(text(
        # The call that trips the cost cap can overshoot it slightly. The true
        # spend is recorded; the cap is cleared for that row (the check is
        # spent <= max_usd) and the overrun is stated in the reason.
        "UPDATE collection_run SET status = :status, "
        "status_reason = CASE WHEN CAST(:spent AS numeric) > COALESCE(max_usd, CAST(:spent AS numeric)) "
        "  THEN concat_ws('; ', CAST(:reason AS text), 'spent ' || CAST(:spent AS numeric) "
        "  || ' USD, over the ' || max_usd || ' USD cap') ELSE CAST(:reason AS text) END, "
        "max_usd = CASE WHEN CAST(:spent AS numeric) > COALESCE(max_usd, CAST(:spent AS numeric)) "
        "  THEN NULL ELSE max_usd END, "
        "finished_at = now(), fetch_count = :fetch_count, spent_usd = CAST(:spent AS numeric), "
        "found_count = :found, deduplicated_count = :dedup, staged_count = :staged, "
        "review_item_count = :review, "
        # Which open-web search run this was, so its candidates can be shown.
        "config_snapshot = COALESCE(config_snapshot, '{}'::jsonb) || "
        "  jsonb_strip_nulls(jsonb_build_object('search_run_id', CAST(:search_run AS text))) "
        "WHERE collection_run_id = CAST(:run AS uuid)"
    ), {
        "status": status,
        "reason": (status_reason or None),
        "fetch_count": int(fetch_count),
        "spent": float(spent_usd),
        "found": int(counts.get("found", 0)),
        "dedup": int(counts.get("deduplicated", 0)),
        "staged": int(counts.get("staged", 0)),
        "review": int(counts.get("review", 0)),
        "run": collection_run_id,
        "search_run": search_run_id,
    })
    session.execute(text(
        "INSERT INTO actor_update_subscription_run "
        "(actor_update_subscription_id, collection_run_id, dry_run) "
        "VALUES (CAST(:sub AS uuid), CAST(:run AS uuid), false)"
    ), {"sub": subscription.subscription_id, "run": collection_run_id})


def advance_schedule(session, subscription: Subscription, *, ran_on: date) -> str:
    """After a completed run: record it, set the next date, or close the request."""

    from dataclasses import replace

    after = replace(subscription, last_run_at=ran_on)
    next_due = after.next_due(ran_on)
    status = ACTIVE if next_due is not None else EXPIRED
    session.execute(text(
        "UPDATE actor_update_subscription SET last_run_at = now(), next_due_at = :next, "
        "status = :status, updated_at = now() "
        "WHERE actor_update_subscription_id = CAST(:id AS uuid)"
    ), {"next": next_due, "status": status, "id": subscription.subscription_id})
    return status


def expire_finished(session, subscriptions: Iterable[Subscription], *, today: date) -> list[str]:
    """Close active requests whose period has ended. Returns their ids."""

    ended = [s.subscription_id for s in subscriptions
             if s.status == ACTIVE and s.is_expired(today)]
    for subscription_id in ended:
        session.execute(text(
            "UPDATE actor_update_subscription SET status = 'expired', next_due_at = NULL, "
            "updated_at = now() WHERE actor_update_subscription_id = CAST(:id AS uuid) "
            "AND status = 'active'"
        ), {"id": subscription_id})
    return ended


# ------------------------------------------------------------- actor updates
# One person-requested update of one actor (agents/collection/actor_updates.py)
# is recorded in the same ledger as discovery runs, by this one writer.

ACTOR_UPDATE_FETCH_BUDGET = 3  # home, About, one topic page


def start_actor_update_run(
    session,
    *,
    actor_id: str,
    topic_id: str,
    need: str,
    requested_by: str,
    job_name: str,
    cap_usd: float,
    spent_usd: float,
    pages_fetched: int,
    snapshot: Mapping[str, object],
) -> tuple[str, str]:
    """A collection request for the actor and its run; returns both ids."""
    request_id = str(session.execute(text(
        "INSERT INTO collection_request (requested_by, request_kind, topic_id, actor_id, "
        "need_text, layer) VALUES (:by, 'mapping', CAST(:topic AS uuid), CAST(:actor AS uuid), "
        ":need, 1) RETURNING collection_request_id::text"
    ), {"by": requested_by, "topic": topic_id, "actor": actor_id,
        "need": need[:2000]}).scalar_one())
    run_id = str(session.execute(text(
        "INSERT INTO collection_run (collection_request_id, job_name, dry_run, status, "
        "fetch_budget, fetch_count, max_usd, spent_usd, trigger_type, cadence, initiated_by, "
        "config_snapshot) VALUES (CAST(:request AS uuid), :job, false, 'running', :budget, "
        ":fetched, :cap, :spent, 'manual', 'once', :by, CAST(:snapshot AS jsonb)) "
        "RETURNING collection_run_id::text"
    ), {"request": request_id, "job": job_name, "budget": ACTOR_UPDATE_FETCH_BUDGET,
        "fetched": min(int(pages_fetched), ACTOR_UPDATE_FETCH_BUDGET),
        # The call that trips the cap can overshoot it slightly: the true spend
        # is kept and the cap cleared for this row, as finish_run does.
        "cap": cap_usd if spent_usd <= cap_usd else None, "spent": spent_usd,
        "by": requested_by, "snapshot": json.dumps(dict(snapshot), default=str)}).scalar_one())
    return request_id, run_id


def finish_actor_update_run(
    session,
    run_id: str,
    *,
    status: str,
    reason: str | None,
    found: int,
    review_items: int,
    outcomes: Mapping[str, str],
) -> None:
    session.execute(text(
        "UPDATE collection_run SET status = :status, status_reason = :reason, "
        "finished_at = now(), found_count = :found, staged_count = 0, deduplicated_count = 0, "
        "review_item_count = :review, config_snapshot = COALESCE(config_snapshot, '{}'::jsonb) "
        "|| CAST(:outcomes AS jsonb) WHERE collection_run_id = CAST(:run AS uuid)"
    ), {"status": status, "reason": reason, "found": int(found), "review": int(review_items),
        "run": run_id, "outcomes": json.dumps({"outcomes": dict(outcomes)})})
