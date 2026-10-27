"""Replay the actor pipeline on a past run's search results, for a fair comparison.

    python -m scripts.evaluate_actor_pipeline --baseline-run RUN_ID --subscription ID \
        --out report.json [--max-usd 1.00]

Same evaluation candidates as the baseline: the baseline run's stored search
results are served back instead of searching again, and the "already seen" set
is what the baseline itself saw. Everything after search runs for real with
today's code and configuration - triage, page reads, scoring, gates, official-
site reads, leads - with a COLD analysis cache, so every page read is paid for.

Nothing is written: in-memory run log, candidate store, stage and domain
stores; promotion runs as a dry run. Reads only, from a local *_test database
(refused otherwise). It spends model money up to --max-usd.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def _guard_database() -> None:
    url = os.environ.get("DATABASE_URL", "")
    parts = urlsplit(url.replace("postgresql+psycopg", "postgresql"))
    if parts.hostname not in {"127.0.0.1", "localhost"} or not parts.path.endswith("_test"):
        raise SystemExit("evaluate_actor_pipeline only reads a local *_test database")


class ReplayProvider:
    """Serves the baseline run's stored results for each of its queries."""

    name = "replay"

    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.calls: list[str] = []

    def search(self, query, *, count=10):
        self.calls.append(query)
        return list(self.results_by_query.get(query, []))[:count]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-usd", type=float, default=1.00)
    parser.add_argument("--search-usd", type=float, default=None,
                        help="the baseline's measured search cost, charged up front")
    args = parser.parse_args(argv)
    _guard_database()
    sys.path.insert(0, str(ROOT))
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # API key only; DATABASE_URL from the caller wins
    _guard_database()

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from agents.collection import subscription_store as store
    from agents.common.cost import CostMeter
    from agents.discovery.search import run as search_run
    from agents.discovery.search.discovery_request import DiscoveryRequest
    from agents.discovery.search.models import SearchResult
    from agents.discovery.search.phase2 import InMemoryDiscoveredDomainStore
    from agents.discovery.search.query_generation import QueryBundle, QueryGenerator
    from agents.discovery.search.store import InMemorySearchCandidateStore
    from agents.discovery.stage import InMemoryStageStore

    class ReplaySession(Session):
        """Promotion opens its own transaction; in a write-free replay the read
        transaction is still open, so promotion gets a savepoint instead - and
        its dry run rolls that back."""

        def begin(self, nested=False):
            if self.in_transaction():
                return self.begin_nested()
            return super().begin(nested=nested)

    with ReplaySession(create_engine(os.environ["DATABASE_URL"])) as session:
        base = session.execute(text(
            "SELECT started_at, stats FROM scrape_run WHERE run_id = CAST(:r AS uuid)"
        ), {"r": args.baseline_run}).mappings().one()
        rows = session.execute(text(
            "SELECT url, title, snippet, provider, query FROM search_candidate "
            "WHERE run_id = CAST(:r AS uuid) ORDER BY created_at"
        ), {"r": args.baseline_run}).mappings().all()
        seen = {row[0] for row in session.execute(text(
            "SELECT url FROM raw_document WHERE fetched_at < :t"), {"t": base["started_at"]})}
        sub_row = next(r for r in store.load_discovery_requests(session)
                       if r["subscription_id"] == args.subscription)
        request = DiscoveryRequest.from_subscription(
            store.subscription_from_row(sub_row), topic_codes=store.topic_codes(session))

        results_by_query: dict[str, list[SearchResult]] = defaultdict(list)
        query_order: list[str] = []
        for row in rows:
            for query in str(row["query"] or "").split(" | "):
                if query not in query_order:
                    query_order.append(query)
                results_by_query[query].append(SearchResult(
                    url=row["url"], title=row["title"] or "", snippet=row["snippet"] or "",
                    provider=row["provider"] or "claude", query=query))
        baseline_cost = {}
        for entry in (base["stats"].get("cost") or {}).get("entries", []):
            baseline_cost[entry["label"]] = baseline_cost.get(entry["label"], 0) + entry["amount_usd"]
        search_usd = args.search_usd if args.search_usd is not None else round(sum(
            v for k, v in baseline_cost.items()
            if "web_search" in k or "haiku" in k), 4)

        class ReplayQueries:
            def generate(self, entity_type, *, session=None, project_root=None, request=None):
                real = QueryGenerator(None, search_run.load_open_web_config(ROOT)).generate(
                    entity_type, session=session, project_root=project_root, request=request)
                return QueryBundle(entity_type=entity_type, queries=query_order,
                                   deterministic_queries=query_order, llm_queries=[],
                                   reference_count=0, metadata=real.metadata)

        meter = CostMeter(max_usd=args.max_usd)
        meter.add(search_usd, "search (baseline, replayed)")
        cache_dir = Path(tempfile.mkdtemp(prefix="ghus-eval-"))
        config = search_run.load_open_web_config(ROOT)
        config["raw_storage_dir"] = str(cache_dir)
        original = search_run.load_open_web_config
        search_run.load_open_web_config = lambda root=None: config
        original_sources = search_run.load_sources_config

        def sources(root=None):
            full = original_sources(root)
            return {**full, "open_web_discovery": config}

        search_run.load_sources_config = sources
        try:
            result = search_run.run_search_triage(
                SimpleNamespace(entity="actor", live=False, offline=True,
                                discovery_request=request,
                                report_out=str(cache_dir / "report.md"),
                                rejection_report_out=str(cache_dir / "rejections.md"),
                                audit_out=str(cache_dir / "audit.csv"),
                                spreadsheet_out=str(cache_dir / "candidates.xlsx")),
                session=session, root=ROOT, cost_meter=meter,
                store=InMemorySearchCandidateStore(seen_raw_urls=seen),
                search_provider=ReplayProvider(results_by_query),
                query_generator=ReplayQueries(),
                # In-memory: the evaluation writes nothing to the database.
                stage_store=InMemoryStageStore(),
                domain_store=InMemoryDiscoveredDomainStore(),
            )
        finally:
            search_run.load_open_web_config = original
            search_run.load_sources_config = original_sources
            session.rollback()

    candidates = result["candidates"]
    stats = result["stats"]
    by_label = Counter()
    for entry in meter.snapshot().get("entries", []):
        by_label[entry["label"]] += entry["amount_usd"]
    out = {
        "baseline_run": args.baseline_run,
        "status": result["status"], "status_reason": result["status_reason"],
        "cost_total_usd": round(meter.spent_usd, 4),
        "cost_by_label": {k: round(v, 4) for k, v in by_label.items()},
        "cost_stages": {k: v for k, v in stats.items() if k.startswith("cost_stage_")},
        "stats": {k: v for k, v in stats.items() if not isinstance(v, (dict, list))},
        "candidates": [{
            "url": c.url, "title": c.title, "provider": c.provider, "query": c.query,
            "verdict": c.triage_verdict, "band": c.score_band,
            "relevance": c.fit_score,
            "priority": (c.score_breakdown or {}).get("priority_score"),
            "name": (c.record_preview or {}).get("name"),
            "website": (c.record_preview or {}).get("website"),
            "reason": c.triage_reason,
        } for c in candidates],
    }
    Path(args.out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    bands = Counter(c["band"] for c in out["candidates"])
    print(json.dumps({"cost_total_usd": out["cost_total_usd"], "bands": bands,
                      "cost_stages": out["cost_stages"]}, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
