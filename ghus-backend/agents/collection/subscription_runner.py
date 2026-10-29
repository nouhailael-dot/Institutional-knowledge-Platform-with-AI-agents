"""Run the discovery and actor update requests that are due - and nothing else.

    python -m agents.collection.subscription_runner           # plan only (default)
    python -m agents.collection.subscription_runner --live    # run what is due

This replaces the weekly actor sweep. Actor discovery now happens only because
a person asked for it on the Discovery page, only within the period they set,
and only as often as they said.

The default is a plan: which requests are due, which are skipped and why, and
the exact queries each would search. It writes nothing and spends nothing.
``--live`` runs each due request through the open-web actor pipeline scoped to
that request, records the run, and moves the request to its next date - or
closes it when its period is over.

Actor update requests (Discovery page -> Actor updates, migration 570) are run
here too, so there is one scheduler: a due request re-reads its actors with the
most missing or out-of-date boxes first (``actor_updates.run_request``), within
its actor cap and spend ceiling, and writes through the Phase 11 fact writer.

One failed request does not stop the others, and a failed run does not move its
request forward: it is due again next time.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from agents.collection import subscription_store as store
from agents.collection.subscriptions import due_subscriptions
from agents.discovery.search.discovery_request import DiscoveryRequest, DiscoveryRequestError
from agents.discovery.search.query_generation import QueryGenerator

logger = logging.getLogger(__name__)

# Two runners at once would run the same request twice. One holds this lock.
_ADVISORY_LOCK = 550_001


@dataclass
class RequestOutcome:
    subscription_id: str
    title: str
    queries: list[str]
    status: str = "planned"
    status_reason: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    collection_run_id: str | None = None
    next_status: str | None = None
    kind: str = "discovery"
    entity: str = "actor"
    # The request's own Light Pull choice; None for requests saved before it.
    pull_depth: str | None = None
    # Who asked (an email address), told when a run has findings (notify.py).
    notify_to: str | None = None
    notified: dict | None = None


@dataclass
class RunnerReport:
    live: bool
    today: date
    outcomes: list[RequestOutcome] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    invalid: dict[str, str] = field(default_factory=dict)
    expired: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(o.status == "failed" for o in self.outcomes):
            return "failed"
        if self.invalid or any(o.status == "attention" for o in self.outcomes):
            return "attention"
        return "succeeded"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _open_web_config(root: Path) -> dict[str, object]:
    from agents.discovery.search.run import load_open_web_config

    return load_open_web_config(root)


def _default_discover(session, root: Path, runs_dir: Path) -> Callable:
    from agents.discovery.search.run import run_search_triage

    def discover(request: DiscoveryRequest) -> dict[str, object]:
        stem = f"discovery-request-{request.subscription_id[:8]}"
        args = SimpleNamespace(
            # What the request finds: organizations, events or people. Each
            # runs the same open-web pipeline as its automatic counterpart.
            entity=request.entity,
            live=True,
            offline=False,
            discovery_request=request,
            report_out=str(runs_dir / f"{stem}-report.md"),
            audit_out=str(runs_dir / f"{stem}-audit.csv"),
            rejection_report_out=None,
            spreadsheet_out=str(runs_dir / f"{stem}-candidates.xlsx"),
            preview_person_create=False,
            enable_people_for_run=False,
        )
        return run_search_triage(args, session=session, root=root)

    return discover


def outcome_counts(result: dict[str, object]) -> dict[str, int]:
    """What a run found, in the four numbers the run record keeps."""

    stats = dict(result.get("stats") or {})
    candidates = list(result.get("candidates") or [])
    return {
        "found": int(stats.get("search_results_unique") or 0),
        "deduplicated": int(stats.get("search_results_deduplicated") or 0)
        + int(stats.get("actor_domain_duplicates_collapsed") or 0)
        + sum(1 for c in candidates if getattr(c, "triage_verdict", None) == "duplicate"),
        "staged": sum(1 for c in candidates if getattr(c, "score_band", None) == "auto_high"),
        "review": sum(1 for c in candidates if getattr(c, "score_band", None) == "review"),
        "rejected": sum(1 for c in candidates if getattr(c, "score_band", None) == "auto_low"),
        "capped": sum(1 for c in candidates if getattr(c, "triage_verdict", None) == "capped"),
    }


def run_due_requests(
    session,
    *,
    live: bool = False,
    today: date | None = None,
    root: Path | None = None,
    runs_dir: Path | None = None,
    config: dict[str, object] | None = None,
    discover: Callable[[DiscoveryRequest], dict[str, object]] | None = None,
    request_id: str | None = None,
    update: Callable | None = None,
) -> RunnerReport:
    """Run what is due; or, with ``request_id``, run that one request now.

    "Run now" is a person's explicit request, so it ignores the cadence - but
    never the request's status or period: a paused, cancelled, finished or
    not-yet-started request does not run.
    """
    root = root or _project_root()
    today = today or datetime.now(UTC).date()
    runs_dir = runs_dir or (root / "agents" / "runs")
    config = config if config is not None else _open_web_config(root)
    report = RunnerReport(live=live, today=today)

    subscriptions = []
    rows = store.load_discovery_requests(session, include_finished=False)
    rows += store.load_actor_update_requests(session, include_finished=False)
    for row in rows:
        try:
            subscriptions.append(store.subscription_from_row(row))
        except ValueError as exc:
            report.invalid[str(row.get("subscription_id"))] = str(exc)
    if request_id is not None:
        subscriptions = [s for s in subscriptions if s.subscription_id == request_id]
        if not subscriptions:
            report.invalid[request_id] = "no active or paused request with this id"
    due, report.skipped = due_subscriptions(subscriptions, today=today)
    if request_id is not None and report.skipped.get(request_id) == "not_due":
        due = tuple(subscriptions)
        report.skipped.pop(request_id)
    report.expired = [sid for sid, why in report.skipped.items() if why == "expired"]
    codes = store.topic_codes(session)
    topic_by_code = {code: topic_id for topic_id, code in codes.items()}

    generator = QueryGenerator(None, config, today=today)
    requests: list[tuple[object, DiscoveryRequest]] = []
    updates: list[object] = []
    for subscription in due:
        if subscription.is_actor_update_request:
            from agents.collection import actor_updates

            try:
                plan = actor_updates.plan_subscription(session, subscription, config=config)
            except (actor_updates.ActorUpdateError, ValueError) as exc:
                report.invalid[subscription.subscription_id] = str(exc)
                continue
            updates.append(subscription)
            report.outcomes.append(RequestOutcome(
                subscription_id=subscription.subscription_id,
                title=subscription.title or "Actor update request",
                queries=[f"{a['name']}: {a['boxes']} box(es) to read" for a in plan["chosen"]],
                kind="actor_update",
            ))
            continue
        try:
            request = DiscoveryRequest.from_subscription(subscription, topic_codes=codes)
            bundle = generator.generate(request.entity, session=session, project_root=root,
                                        request=request)
        except (DiscoveryRequestError, RuntimeError, ValueError) as exc:
            report.invalid[subscription.subscription_id] = str(exc)
            continue
        requests.append((subscription, request))
        report.outcomes.append(RequestOutcome(
            subscription_id=subscription.subscription_id,
            title=request.title,
            queries=list(bundle.queries),
            entity=request.entity,
            pull_depth=(subscription.discovery_options or {}).get("pull_depth"),
            notify_to=subscription.requested_by,
        ))

    if not live:
        return report

    locked = session.execute(text("SELECT pg_try_advisory_lock(:k)"),
                             {"k": _ADVISORY_LOCK}).scalar()
    if not locked:
        raise RuntimeError("another discovery-request runner is already running")
    try:
        store.expire_finished(session, subscriptions, today=today)
        session.commit()
        runs_dir.mkdir(parents=True, exist_ok=True)
        discover = discover or _default_discover(session, root, runs_dir)
        by_id = {o.subscription_id: o for o in report.outcomes}
        for subscription, request in requests:
            outcome = by_id[subscription.subscription_id]
            _run_one(session, subscription, request, outcome, discover=discover,
                     config=config, topic_id=topic_by_code.get(request.sector_codes[0]),
                     today=today)
        for subscription in updates:
            topic = (subscription.update_options.get("topic")
                     or (subscription.sector_codes or (None,))[0])
            _run_update(session, subscription, by_id[subscription.subscription_id],
                        config=config, topic_id=topic_by_code.get(topic) if topic else None,
                        today=today, update=update)
    finally:
        # A failed statement leaves the transaction aborted; clear it first so
        # the unlock runs and the original error is the one that surfaces.
        session.rollback()
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK})
        session.commit()
    return report


def _run_one(session, subscription, request, outcome, *, discover, config, topic_id, today):
    request_id = store.ensure_collection_request(session, subscription, topic_id)
    run_id = store.start_run(
        session,
        collection_request_id=request_id,
        subscription=subscription,
        fetch_budget=int(config.get("max_pages_fetched", 30)),
        max_usd=float(config.get("max_usd_per_run", 5.0)),
        config_snapshot={"discovery_request": request.describe(), "queries": outcome.queries},
    )
    session.commit()
    outcome.collection_run_id = run_id
    started = datetime.now(UTC)
    try:
        result = discover(request)
    except Exception as exc:  # one request must not stop the others
        logger.exception("discovery request %s failed", subscription.subscription_id)
        session.rollback()
        outcome.status, outcome.status_reason = "failed", str(exc)[:500]
        # A failed run still spent money; record what its search run logged.
        search_run_id, spent = store.search_run_since(session, started, request.entity)
        store.finish_run(session, collection_run_id=run_id, subscription=subscription,
                         status="failed", status_reason=outcome.status_reason, counts={},
                         fetch_count=0, spent_usd=spent, search_run_id=search_run_id)
        session.commit()
        return
    stats = dict(result.get("stats") or {})
    outcome.counts = outcome_counts(result)
    outcome.status = str(result.get("status") or "failed")
    outcome.status_reason = str(result.get("status_reason") or "")
    budget = int(config.get("max_pages_fetched", 30))
    store.finish_run(
        session,
        collection_run_id=run_id,
        subscription=subscription,
        status=outcome.status if outcome.status in ("succeeded", "attention") else "failed",
        status_reason=outcome.status_reason,
        counts=outcome.counts,
        # The pipeline never loads more pages than the budget, so this is exact.
        fetch_count=min(int(stats.get("pages_fetched") or 0), budget),
        spent_usd=float(stats.get("cost_usd") or 0.0),
        search_run_id=str(result["run_id"]) if result.get("run_id") else None,
    )
    if outcome.status in ("succeeded", "attention"):
        outcome.next_status = store.advance_schedule(session, subscription, ran_on=today)
    session.commit()


def _run_update(session, subscription, outcome, *, config, topic_id, today, update=None):
    """One live run of an actor update request, recorded like a discovery run."""
    from agents.collection import actor_updates

    update = update or actor_updates.run_request
    per_run = int(subscription.update_options.get("max_actors_per_run") or 1)
    request_id = store.ensure_collection_request(session, subscription, topic_id)
    run_id = store.start_run(
        session,
        collection_request_id=request_id,
        subscription=subscription,
        fetch_budget=per_run * store.ACTOR_UPDATE_FETCH_BUDGET,
        max_usd=float(subscription.max_usd_per_run),
        config_snapshot={"update_request": dict(subscription.update_options),
                         "planned": outcome.queries},
    )
    session.commit()
    outcome.collection_run_id = run_id
    try:
        result = update(session, subscription, ledger=(request_id, run_id), config=config)
    except Exception as exc:  # one request must not stop the others
        logger.exception("actor update request %s failed", subscription.subscription_id)
        session.rollback()
        outcome.status, outcome.status_reason = "failed", str(exc)[:500]
        store.finish_run(session, collection_run_id=run_id, subscription=subscription,
                         status="failed", status_reason=outcome.status_reason, counts={},
                         fetch_count=0, spent_usd=0.0)
        session.commit()
        return
    results = result["actor_results"]
    reached = [r for r in results if r.get("ok")]
    if results and not reached:
        outcome.status = "failed"
    elif result["failed"] or result["stopped"]:
        outcome.status = "attention"
    else:
        outcome.status = "succeeded"
    reasons = [result["stopped"]] if result["stopped"] else []
    if result["failed"]:
        reasons.append(f"{result['failed']} actor(s) could not be updated")
    if not results:
        reasons.append("no actor had anything missing or out of date")
    outcome.status_reason = "; ".join(reasons)
    outcome.counts = {"found": result["found"], "review": result["review_items"],
                      "actors": len(reached)}
    store.finish_run(
        session,
        collection_run_id=run_id,
        subscription=subscription,
        status=outcome.status,
        status_reason=outcome.status_reason or None,
        counts={"found": result["found"], "review": result["review_items"]},
        fetch_count=min(result["pages"], per_run * store.ACTOR_UPDATE_FETCH_BUDGET),
        spent_usd=result["spent_usd"],
        snapshot_extra={"actor_results": results, "stopped": result["stopped"]},
    )
    if outcome.status in ("succeeded", "attention"):
        outcome.next_status = store.advance_schedule(session, subscription, ran_on=today)
    session.commit()


def render_report(report: RunnerReport) -> str:
    mode = "live" if report.live else "plan only - nothing searched, nothing written"
    lines = [
        "# Discovery and actor update requests",
        "",
        f"**Status:** {report.status}",
        f"Date: {report.today.isoformat()} ({mode})",
        "",
        (f"Due: {len(report.outcomes)}  Skipped: {len(report.skipped)}  "
         f"Invalid: {len(report.invalid)}"),
        "",
    ]
    for outcome in report.outcomes:
        lines.append(f"## {outcome.title}  (`{outcome.subscription_id}`)")
        lines.append(f"Run: {outcome.status}" + (f" - {outcome.status_reason}"
                                                  if outcome.status_reason else ""))
        if outcome.counts:
            lines.append(", ".join(f"{k}: {v}" for k, v in outcome.counts.items()))
        if outcome.next_status:
            lines.append(f"Request is now: {outcome.next_status}")
        if outcome.notified:
            lines.append(f"Email: sent to {outcome.notified['to']}" if outcome.notified.get("sent")
                         else f"Email: not sent - {outcome.notified.get('reason')}")
        label = "Actors" if outcome.kind == "actor_update" else "Queries"
        lines.append(f"{label} ({len(outcome.queries)}):")
        lines.extend(f"- {query}" for query in outcome.queries)
        lines.append("")
    if report.skipped:
        lines.append("## Skipped")
        lines.extend(f"- `{sid}`: {why}" for sid, why in sorted(report.skipped.items()))
        lines.append("")
    if report.invalid:
        lines.append("## Could not run")
        lines.extend(f"- `{sid}`: {why}" for sid, why in sorted(report.invalid.items()))
        lines.append("")
    return "\n".join(lines)


def _notify_after(report: RunnerReport, *, environ=None, smtp_factory=None) -> None:
    """Email whoever asked, for each discovery run that sent findings to Review.

    After Light Pull, so the findings are ready to verify when the email lands.
    """
    from agents.collection.notify import findings, notify_findings

    for outcome in report.outcomes:
        if (outcome.kind != "discovery" or outcome.status not in ("succeeded", "attention")
                or not findings(outcome)):
            continue
        outcome.notified = notify_findings(outcome, outcome.notify_to, environ=environ,
                                           smtp_factory=smtp_factory)


def _light_pull_after(report: RunnerReport, *, everything: bool = False) -> None:
    """Read the kept candidates of each discovery request that just ran.

    A discovery run scores pages; the Light Pull read - the organisation's own
    homepage, About page and one topic page - is what fills its boxes, the
    location among them. Without it, a reviewer saw most boxes empty. Uses
    light_pull_candidates as is: its own spend cap, and its refusal of any
    database but a local *_test one unless an operator allows it.
    """
    from agents.collection import light_pull_candidates

    for outcome in report.outcomes:
        if outcome.kind != "discovery" or outcome.status not in ("succeeded", "attention"):
            continue
        if outcome.entity != "actor":
            # Events and people are read in full by their own run (with a
            # bounded official-page follow-up); the Light Pull here reads
            # organizations' own sites.
            continue
        # The request's own choice decides; requests saved before it had one
        # are read only when the operator asks (--light-pull), as before.
        if outcome.pull_depth == "none" or (outcome.pull_depth is None and not everything):
            continue
        try:
            # A second pass reads only the candidates the first could not (a
            # model timeout leaves a candidate unread); it costs nothing when
            # every candidate was read.
            for _ in range(2):
                light_pull_candidates.main(["--request-id", outcome.subscription_id, "--live"])
            outcome.status_reason = "; ".join(filter(None, [
                outcome.status_reason, "candidates' own pages read (Light Pull)"]))
        except SystemExit as exc:  # the guard refuses a shared database: say so
            outcome.status_reason = "; ".join(filter(None, [
                outcome.status_reason, f"Light Pull not run: {exc}"[:300]]))
        except Exception as exc:  # noqa: BLE001 - the discovery run itself stands
            logger.exception("Light Pull after request %s failed", outcome.subscription_id)
            outcome.status_reason = "; ".join(filter(None, [
                outcome.status_reason, f"Light Pull failed: {type(exc).__name__}"]))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run due Discovery-page requests.")
    parser.add_argument("--live", action="store_true",
                        help="Search, score and record. Without it: plan only.")
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    parser.add_argument("--report-out", default="agents/runs/discovery-requests-report.md")
    parser.add_argument("--request-id", default=None,
                        help="Run this one request now, whatever its cadence says.")
    parser.add_argument("--light-pull", action="store_true",
                        help="After a live discovery request, read every kept candidate's own "
                             "pages so Review shows its boxes filled (capped).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    from agents.collection.discovery_requests import open_session

    with open_session() as session:
        target = session.execute(text(
            "SELECT current_database() || ' on ' || COALESCE(inet_server_addr()::text, 'local')"
        )).scalar()
        print(f"database: {target}", file=sys.stderr)
        report = run_due_requests(session, live=args.live, today=args.today,
                                  request_id=args.request_id)
    if args.live:
        _light_pull_after(report, everything=args.light_pull)
        _notify_after(report)
    text_report = render_report(report)
    out = Path(args.report_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text_report, encoding="utf-8", newline="\n")
    print(text_report)
    return 1 if report.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
