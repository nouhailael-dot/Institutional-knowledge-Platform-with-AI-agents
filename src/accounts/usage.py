"""Who spent what (accounts Phase 5): paid operations, attributed, from the existing ledgers.

Costs are never copied. Each operation's cost is read from the ledger that
already holds it:

| Feature                     | Ledger                                  | Who it is charged to |
|-----------------------------|-----------------------------------------|----------------------|
| Discovery requests          | collection_run (job discovery_request)  | Run now: the person who pressed it. Scheduled: the request's owner, trigger "scheduled" |
| Organization Updates        | collection_run (job actor_update_request)| same |
| Organization checks, Deep Pull | collection_run (job actor_update), by its check id | the person who ran the check |
| Data Feed AI completion     | scrape_run (source ghus_data_feed)      | who started the completion, else the import's owner |
| Explore and Map             | the map store's calls (its own run)     | the map's owner |
| People search               | the map store's calls (the search's run)| who started the search |
| Ask Compass                 | none: its token usage, recorded per answer | who asked |

An organization check that was never applied has no run in the ledger; its cost
is the one the check reported (kept with who ran it). Once applied, the run's
cost is used instead, so nothing is counted twice.

Nothing is guessed: an operation without a recorded person is "Not recorded",
and a cost that is not final says so (in progress, partial run, estimate,
unknown).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone

NOT_RECORDED = "Not recorded"
FEATURES = {
    "discovery_request": "Discovery requests",
    "actor_update_request": "Organization Updates",
    "actor_update": "Organization checks and Deep Pull",
    "datafeed": "Data Feed AI completion",
    "map": "Explore and Map",
    "people_search": "People search",
    "ask": "Ask Compass",
}
MICRO = 1_000_000
RUN_NOW_WINDOW = (-60, 30 * 60)       # a run starting within this many seconds of Run now


def _when(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _status_basis(status: str | None) -> str:
    return {"running": "in progress", "failed": "partial run"}.get(status or "", "final")


def operations(store, map_db=None) -> list[dict]:
    """Every paid operation known to Compass, attributed and labelled. ``map_db`` is
    an open sqlite3 connection to the map store (or None)."""
    people = store.people()
    events = store.usage_events()
    by_kind: dict[str, dict[str, dict]] = defaultdict(dict)
    for e in events:
        by_kind[e["kind"]][e["reference"]] = e
    owners = {kind: store.owners_of_type(kind) for kind in ("request", "map", "import")}

    def person(user_id):
        return (user_id, people.get(user_id, NOT_RECORDED)) if user_id else (None, NOT_RECORDED)

    ops: list[dict] = []

    # Run now presses, per request, oldest first; each explains at most one run.
    run_now = defaultdict(list)
    for e in by_kind["run_now"].values():
        sid = (e["detail"] or {}).get("subscription_id")
        if sid:
            run_now[sid].append(e)
    used: set[str] = set()

    runs = sorted(store.run_ledger(), key=lambda r: _when(r["started_at"]) or _OLDEST)
    for run in runs:
        job = run["job_name"]
        started = _when(run["started_at"])
        user_id, trigger, how = None, "manual", None
        if job == "actor_update" and run["check_id"]:
            check = by_kind["actor_check"].get(run["check_id"])
            if check:
                user_id, how = check["user_id"], "ran the check"
        elif run["subscription_id"]:
            sid = run["subscription_id"]
            press = next((e for e in run_now.get(sid, []) if e["reference"] not in used and started
                          and RUN_NOW_WINDOW[0] <= (started - _when(e["occurred_at"])).total_seconds()
                          <= RUN_NOW_WINDOW[1]), None)
            if press:
                used.add(press["reference"])
                user_id, trigger, how = press["user_id"], "run_now", "pressed Run now"
            elif sid in owners["request"]:
                user_id, trigger, how = owners["request"][sid][0], "scheduled", "owns the request"
            else:
                trigger = "scheduled" if run["trigger_type"] == "subscription" else "manual"
        uid, name = person(user_id)
        ops.append({"source": "collection_run", "reference": run["run_id"], "feature": FEATURES.get(job, job),
                    "user_id": uid, "user": name, "trigger": trigger, "attributed_because": how,
                    "started_at": started, "status": run["status"], "cost_usd": round(run["spent_usd"], 6),
                    "basis": _status_basis(run["status"])})

    # Checks never applied: the cost the check reported (no ledger run holds it).
    applied = {r["check_id"] for r in runs if r["check_id"]}
    for check_id, e in by_kind["actor_check"].items():
        if check_id not in applied:
            uid, name = person(e["user_id"])
            ops.append({"source": "check_result", "reference": check_id, "feature": FEATURES["actor_update"],
                        "user_id": uid, "user": name, "trigger": "manual", "attributed_because": "ran the check",
                        "started_at": _when(e["occurred_at"]), "status": "not applied",
                        "cost_usd": round(e["cost_usd"] or 0, 6),
                        "basis": "recorded by the check" if e["cost_usd"] is not None else "unknown"})

    for run in store.datafeed_ledger():
        completion = by_kind["datafeed_completion"].get(run["run_id"])
        user_id = completion["user_id"] if completion else owners["import"].get(run["run_id"], (None,))[0]
        uid, name = person(user_id)
        ops.append({"source": "scrape_run", "reference": run["run_id"], "feature": FEATURES["datafeed"],
                    "user_id": uid, "user": name, "trigger": "manual",
                    "attributed_because": "started the completion" if completion else
                    ("owns the import" if uid else None),
                    "started_at": _when(run["started_at"]), "status": run["status"],
                    "cost_usd": round(run["cost_usd"], 6), "basis": _status_basis(run["status"])})

    if map_db is not None:
        children = dict(map_db.execute("SELECT run_id, parent_id FROM people_tasks").fetchall())
        for run_id, created, recorded, reserved_open, status in map_db.execute("""
                SELECT r.id, r.created,
                       COALESCE(SUM(c.cost), 0),
                       COALESCE(SUM(CASE WHEN c.cost IS NULL AND c.finished IS NULL THEN c.reserved END), 0),
                       r.status
                  FROM runs r JOIN calls c ON c.run_id = r.id
                 GROUP BY r.id""").fetchall():
            if run_id in children:
                e = by_kind["people_search"].get(run_id)
                uid, name = person(e["user_id"] if e else None)
                feature, because = FEATURES["people_search"], "started the search" if e else None
            else:
                owner = owners["map"].get(run_id)
                uid, name = person(owner[0] if owner else None)
                feature, because = FEATURES["map"], "owns the map" if owner else None
            basis = ("estimate (calls still running)" if reserved_open else
                     "in progress" if status in ("running", "planning", "verifying") else
                     "partial run" if status in ("error", "interrupted", "budget_stopped", "cancelled") else "final")
            ops.append({"source": "map_calls", "reference": run_id, "feature": feature, "user_id": uid, "user": name,
                        "trigger": "manual", "attributed_because": because, "started_at": _when(created),
                        "status": status, "cost_usd": round((recorded + reserved_open) / MICRO, 6), "basis": basis})

    for ref, e in by_kind["ask"].items():
        uid, name = person(e["user_id"])
        ops.append({"source": "ask_usage", "reference": ref, "feature": FEATURES["ask"], "user_id": uid, "user": name,
                    "trigger": "manual", "attributed_because": "asked", "started_at": _when(e["occurred_at"]),
                    "status": "answered", "cost_usd": round(e["cost_usd"] or 0, 6),
                    "basis": "priced from tokens" if e["cost_basis"] == "usage_priced" else "unknown (no price)",
                    "tokens": (e["input_tokens"] or 0) + (e["output_tokens"] or 0)})
    return ops


_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def newest_first(ops) -> list[dict]:
    return sorted(ops, key=lambda o: o.get("started_at") or _OLDEST, reverse=True)


def month_of(op) -> str:
    return op["started_at"].strftime("%Y-%m") if op.get("started_at") else "unknown"


def filtered(ops, *, user_id=None, feature=None, since=None, until=None, unattributed=False):
    out = []
    for op in ops:
        month = month_of(op)
        if user_id and op["user_id"] != user_id:
            continue
        if unattributed and op["user_id"] is not None:
            continue
        if feature and op["feature"] != feature:
            continue
        if since and month < since:
            continue
        if until and month > until:
            continue
        out.append(op)
    return out


def summary(ops) -> dict:
    """Totals, by month, by feature and by person; costs split final / not final."""
    def blank():
        return {"cost_usd": 0.0, "not_final_usd": 0.0, "operations": 0}

    total, by_month, by_feature, by_user = blank(), defaultdict(blank), defaultdict(blank), defaultdict(blank)
    by_user_month = defaultdict(lambda: defaultdict(float))
    for op in ops:
        for bucket in (total, by_month[month_of(op)], by_feature[op["feature"]], by_user[op["user"]]):
            bucket["cost_usd"] += op["cost_usd"]
            bucket["operations"] += 1
            if op["basis"] != "final" and op["basis"] != "recorded by the check" and op["basis"] != "priced from tokens":
                bucket["not_final_usd"] += op["cost_usd"]
        by_user_month[op["user"]][month_of(op)] += op["cost_usd"]
    rnd = lambda d: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}
    return {"total": rnd(total),
            "by_month": {m: rnd(v) for m, v in sorted(by_month.items())},
            "by_feature": {f: rnd(v) for f, v in sorted(by_feature.items())},
            "by_user": {u: rnd(v) for u, v in sorted(by_user.items())},
            "by_user_month": {u: {m: round(c, 6) for m, c in sorted(months.items())}
                              for u, months in sorted(by_user_month.items())}}


def reconcile(store, ops, map_db=None) -> list[dict]:
    """Each ledger's own total next to the attributed and unattributed sums taken from it."""
    def sums(source):
        part = [o for o in ops if o["source"] == source]
        return (round(sum(o["cost_usd"] for o in part if o["user_id"]), 6),
                round(sum(o["cost_usd"] for o in part if not o["user_id"]), 6))

    rows = []
    ledgers = [("collection_run", "Discovery, Update and check runs",
                round(sum(r["spent_usd"] for r in store.run_ledger()), 6)),
               ("scrape_run", "Data Feed runs", round(sum(r["cost_usd"] for r in store.datafeed_ledger()), 6))]
    if map_db is not None:
        recorded, open_reserved = map_db.execute(
            "SELECT COALESCE(SUM(cost),0), COALESCE(SUM(CASE WHEN cost IS NULL AND finished IS NULL THEN reserved END),0) "
            "FROM calls").fetchone()
        ledgers.append(("map_calls", "Map and people-search calls", round((recorded + open_reserved) / MICRO, 6)))
    for source, label, ledger_total in ledgers:
        attributed, unattributed = sums(source)
        rows.append({"ledger": label, "ledger_total_usd": ledger_total, "attributed_usd": attributed,
                     "not_recorded_usd": unattributed,
                     "difference_usd": round(ledger_total - attributed - unattributed, 6)})
    return rows


EXPORT_COLUMNS = ("month", "started_at", "feature", "user", "trigger", "attributed_because", "status",
                  "basis", "cost_usd", "source", "reference")


def export_rows(ops) -> list[list]:
    return [[month_of(o), o["started_at"].isoformat() if o.get("started_at") else "", o["feature"], o["user"],
             o["trigger"], o.get("attributed_because") or "", o["status"] or "", o["basis"], o["cost_usd"],
             o["source"], o["reference"]] for o in sorted(ops, key=lambda o: (month_of(o), o["feature"]))]


def to_csv(ops) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(export_rows(ops))
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(ops, summary_data: dict) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Operations"
    sheet.append(list(EXPORT_COLUMNS))
    for row in export_rows(ops):
        sheet.append(row)
    months = book.create_sheet("By person and month")
    all_months = sorted({m for per in summary_data["by_user_month"].values() for m in per})
    months.append(["Person", *all_months, "Total"])
    for person, per in summary_data["by_user_month"].items():
        months.append([person, *[round(per.get(m, 0), 2) for m in all_months], round(sum(per.values()), 2)])
    features = book.create_sheet("By feature")
    features.append(["Feature", "Cost (USD)", "Not final (USD)", "Operations"])
    for feature, v in summary_data["by_feature"].items():
        features.append([feature, v["cost_usd"], v["not_final_usd"], v["operations"]])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
