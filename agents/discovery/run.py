"""Manual and scheduled CLI for the discovery vertical slice."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional

from agents.common.cost import CostMeter
from agents.common.digest import write_digest
from agents.common.llm import ClaudeToolClient, FixtureToolClient
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import load_event_candidates, route_event
from agents.common.run_log import InMemoryRunLog, SQLRunLog, write_audit_csv
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.normalize import normalize_event_record
from agents.discovery.promote import promote
from agents.discovery.relevance import filter_relevant_records
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.climate_week import ClimateWeekAdapter
from agents.discovery.stage import InMemoryStageStore, SQLStageStore, mark_routed, stage_record

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(root: Optional[Path] = None) -> dict[str, object]:
    root = root or project_root()
    return json.loads((root / "agents" / "config" / "sources.yaml").read_text(encoding="utf-8"))


def build_source(name: str, config: dict[str, object], root: Path, *, live: bool):
    sources = dict(config.get("sources", {}))
    source_config = dict(sources.get(name, {}))
    if not source_config:
        raise ValueError(f"unknown source {name!r}")
    if name != "climate_week":
        raise NotImplementedError("Phase 1 supports only source='climate_week'")
    return ClimateWeekAdapter(source_config, project_root=root, offline=not live), source_config


def build_extractor(entity_type: str, source_config: dict[str, object], root: Path, *, live: bool, cost_meter: CostMeter):
    if entity_type != "event":
        raise NotImplementedError("Phase 1 supports only entity='event'")
    fixture_response = source_config.get("llm_fixture_response")
    if fixture_response and not live:
        llm_client = FixtureToolClient.from_path(_resolve_path(root, str(fixture_response)))
    else:
        pricing = dict(source_config.get("llm_pricing", {}))
        llm_client = ClaudeToolClient(
            str(source_config.get("claude_model", "claude-haiku-4-5")),
            cost_meter=cost_meter,
            input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
            output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
        )
    return EventExtractor(llm_client)


def run_pipeline(
    args,
    *,
    session=None,
    root: Optional[Path] = None,
    run_log=None,
    stage_store=None,
    source=None,
    extractor=None,
    raw_store: Optional[RawContentStore] = None,
) -> dict[str, object]:
    root = root or project_root()
    config = load_config(root)
    replay_run_id = getattr(args, "replay", None)
    live = bool(getattr(args, "live", False))
    owned_session = False

    if (live or (replay_run_id and run_log is None)) and session is None:
        from src.db.session import SessionLocal

        session = SessionLocal()
        owned_session = True

    history_log = run_log if replay_run_id else None
    if replay_run_id and history_log is None:
        history_log = SQLRunLog(session)

    source_name = getattr(args, "source", None)
    entity_type = getattr(args, "entity", None)
    if replay_run_id:
        prior_run = history_log.get_run(replay_run_id)
        source_name = source_name or str(prior_run.get("source_name") or "")
        entity_type = entity_type or str(prior_run.get("entity_type") or "")
    if not source_name or not entity_type:
        raise ValueError("--source and --entity are required unless --replay can resolve them from scrape_run")

    if replay_run_id:
        sources = dict(config.get("sources", {}))
        source_config = dict(sources.get(source_name, {}))
        if not source_config:
            raise ValueError(f"unknown source {source_name!r}")
    else:
        source, source_config = (source, None) if source is not None else build_source(source_name, config, root, live=live)
        if source_config is None:
            source_config = dict(dict(config.get("sources", {})).get(source_name, {}))
        if entity_type not in source.entity_types:
            raise ValueError(f"source {source_name!r} does not support entity {entity_type!r}")

    cost_meter = CostMeter(max_usd=float(dict(config.get("cost", {})).get("max_usd_per_run", 0.0)))
    raw_store = raw_store or RawContentStore.from_config(root, source_config)
    run_log = run_log or (SQLRunLog(session) if live else InMemoryRunLog())
    stage_store = stage_store or (SQLStageStore(session) if live else InMemoryStageStore())
    extractor = extractor or build_extractor(entity_type, source_config, root, live=live, cost_meter=cost_meter)

    run_config = dict(source_config)
    if replay_run_id:
        run_config["replay_of_run_id"] = replay_run_id
    run_id = run_log.start_run(source_name=source_name, entity_type=entity_type, live=live, config=run_config)

    stats = _empty_stats()
    audit_rows: list[dict[str, object]] = []
    out_path = _output_path(root, getattr(args, "out", None), run_id, suffix=".csv")
    digest_path = _output_path(root, getattr(args, "digest_out", None), run_id, suffix=".md")

    try:
        candidates = load_event_candidates(session) if live else []
        if replay_run_id:
            raw_rows = history_log.raw_documents_for_run(replay_run_id)
            if not raw_rows:
                raise RuntimeError(f"replay run {replay_run_id} has no raw_document rows")
            stats["documents_fetched"] = len(raw_rows)
            for raw in raw_rows:
                doc = _doc_from_raw(raw, raw_store)
                raw_document_id = run_log.write_raw_document(
                    run_id=run_id,
                    doc=doc,
                    storage_path=str(raw.get("storage_path") or ""),
                )
                _extract_stage_route_promote(
                    doc=doc,
                    raw_document_id=raw_document_id,
                    run_id=run_id,
                    source_name=source_name,
                    entity_type=entity_type,
                    extractor=extractor,
                    stage_store=stage_store,
                    session=session,
                    live=live,
                    candidates=candidates,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                )
        else:
            urls = list(source.discover())
            stats["urls_discovered"] = len(urls)
            if getattr(args, "limit", None) is not None:
                urls = urls[: args.limit]
            if not urls:
                logger.warning("source %s discovered zero URLs", source_name)

            for url in urls:
                doc = source.fetch(url)
                stats["documents_fetched"] += 1
                prior_raw = run_log.find_raw_document(url=doc.url, content_hash=doc.content_hash)
                storage_path = _storage_path_for_doc(raw_store, run_id=run_id, doc=doc, prior_raw=prior_raw)
                raw_document_id = run_log.write_raw_document(run_id=run_id, doc=doc, storage_path=storage_path)
                if prior_raw is not None:
                    stats["skipped_unchanged"] += 1
                    audit_rows.append(_skip_audit_row(run_id, source_name, entity_type, doc))
                    continue
                _extract_stage_route_promote(
                    doc=doc,
                    raw_document_id=raw_document_id,
                    run_id=run_id,
                    source_name=source_name,
                    entity_type=entity_type,
                    extractor=extractor,
                    stage_store=stage_store,
                    session=session,
                    live=live,
                    candidates=candidates,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                )
                cost_meter.enforce()

        logger.info("skipped unchanged documents: %d", stats["skipped_unchanged"])
        _finalize_cost(stats, extractor, cost_meter)
        stats["audit_csv"] = str(out_path)
        stats["digest_md"] = str(digest_path)
        stats["cost_usd"] = cost_meter.spent_usd
        write_audit_csv(out_path, audit_rows)
        write_digest(digest_path, run_id=run_id, source=source_name, entity_type=entity_type, status="succeeded", stats=stats)
        run_log.close_run(run_id, status="succeeded", stats=stats, cost_usd=cost_meter.spent_usd)
        return {"run_id": run_id, "status": "succeeded", "stats": stats, "audit_rows": audit_rows, "digest_path": str(digest_path)}
    except Exception as exc:
        stats["failures"] += 1
        _finalize_cost(stats, extractor, cost_meter)
        stats["audit_csv"] = str(out_path)
        stats["digest_md"] = str(digest_path)
        stats["cost_usd"] = cost_meter.spent_usd
        write_audit_csv(out_path, audit_rows)
        write_digest(digest_path, run_id=run_id, source=source_name, entity_type=entity_type, status="failed", stats=stats)
        run_log.fail_run(run_id, error=str(exc), stats=stats, cost_usd=cost_meter.spent_usd)
        if live and session is not None:
            session.rollback()
        raise
    finally:
        if owned_session:
            session.close()


def _extract_stage_route_promote(
    *,
    doc: FetchedDoc,
    raw_document_id: str,
    run_id: str,
    source_name: str,
    entity_type: str,
    extractor,
    stage_store,
    session,
    live: bool,
    candidates: list[dict[str, object]],
    root: Path,
    stats: dict[str, int],
    audit_rows: list[dict[str, object]],
) -> None:
    extracted = extractor.extract(doc)
    stats["records_extracted"] += len(extracted)
    normalized = [normalize_event_record(record) for record in extracted]
    relevant = filter_relevant_records(normalized, project_root=root)
    stats["records_relevant"] += len(relevant)
    for record in relevant:
        staged = stage_record(
            stage_store,
            run_id=run_id,
            raw_document_id=raw_document_id,
            entity_type=entity_type,
            record=record,
            prompt_version=extractor.prompt_version,
        )
        stats["records_staged"] += 1
        decision = route_event(record, candidates)
        staged = mark_routed(stage_store, staged, decision)
        result = promote(staged, decision, session=session, live=live)
        stats["records_promoted"] += 0 if result.dry_run else 1
        _count_zone(stats, decision.zone)
        audit_rows.append(
            {
                "run_id": run_id,
                "source": source_name,
                "entity_type": entity_type,
                "source_url": record.get("source_url"),
                "content_hash": doc.content_hash,
                "natural_key": record.get("natural_key"),
                "zone": decision.zone,
                "score": decision.score,
                "target_entity_id": decision.target_entity_id,
                "candidate_ids": decision.candidate_ids,
                "status": result.action,
                "error": "",
            }
        )


def _storage_path_for_doc(raw_store: RawContentStore, *, run_id: str, doc: FetchedDoc, prior_raw: Optional[dict[str, object]]) -> str:
    prior_path = str((prior_raw or {}).get("storage_path") or "")
    if raw_store.exists(prior_path):
        return prior_path
    return raw_store.write(run_id=run_id, doc=doc)


def _doc_from_raw(raw: dict[str, object], raw_store: RawContentStore) -> FetchedDoc:
    storage_path = str(raw.get("storage_path") or "")
    if raw_store.exists(storage_path):
        content = raw_store.read(storage_path)
    elif raw.get("content") is not None:
        content = str(raw["content"])
    else:
        raise RuntimeError(f"raw_document {raw.get('raw_document_id')} has no stored content")
    doc = FetchedDoc.from_content(
        url=str(raw["url"]),
        content=content,
        content_type=str(raw.get("content_type") or "text/html"),
        fetched_at=str(raw.get("fetched_at") or ""),
        meta=dict(raw.get("meta") or {}),
    )
    expected_hash = str(raw.get("content_hash") or "")
    if expected_hash and doc.content_hash != expected_hash:
        raise RuntimeError(f"stored content hash mismatch for {raw.get('raw_document_id')}")
    return doc


def _skip_audit_row(run_id: str, source_name: str, entity_type: str, doc: FetchedDoc) -> dict[str, object]:
    return {
        "run_id": run_id,
        "source": source_name,
        "entity_type": entity_type,
        "source_url": doc.url,
        "content_hash": doc.content_hash,
        "natural_key": "",
        "zone": "skipped",
        "score": "",
        "target_entity_id": "",
        "candidate_ids": [],
        "status": "skipped_unchanged",
        "error": "",
    }


def _count_zone(stats: dict[str, int], zone: str) -> None:
    if zone == "absorb":
        stats["absorbed"] += 1
    elif zone == "review":
        stats["queued_for_review"] += 1
    elif zone == "create":
        stats["created"] += 1


def _finalize_cost(stats: dict[str, object], extractor, cost_meter: CostMeter) -> None:
    llm_client = getattr(extractor, "llm_client", None)
    usage = getattr(llm_client, "usage", None)
    stats["llm"] = usage.snapshot() if usage is not None else {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if float(stats["llm"].get("cost_usd", 0.0) or 0.0) > cost_meter.spent_usd:
        cost_meter.spent_usd = float(stats["llm"].get("cost_usd", 0.0) or 0.0)
    stats["cost"] = cost_meter.snapshot()


def _empty_stats() -> dict[str, int]:
    return {
        "urls_discovered": 0,
        "documents_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_relevant": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "absorbed": 0,
        "queued_for_review": 0,
        "created": 0,
        "failures": 0,
    }


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--entity")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true", help="commit writes; absent means dry-run")
    parser.add_argument("--out", help="audit CSV output path")
    parser.add_argument("--digest-out", help="weekly digest markdown output path")
    parser.add_argument("--replay", help="existing scrape_run id whose stored raw content should be re-extracted")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_pipeline(parse_args(argv))
    stats = result["stats"]
    print(
        "status={status} run_id={run_id} documents={documents} skipped_unchanged={skipped} "
        "extracted={extracted} relevant={relevant} staged={staged} audit={audit} digest={digest}".format(
            status=result["status"],
            run_id=result["run_id"],
            documents=stats["documents_fetched"],
            skipped=stats["skipped_unchanged"],
            extracted=stats["records_extracted"],
            relevant=stats["records_relevant"],
            staged=stats["records_staged"],
            audit=stats["audit_csv"],
            digest=stats["digest_md"],
        )
    )


def _output_path(root: Path, value: Optional[str], run_id: str, *, suffix: str) -> Path:
    path = Path(value) if value else root / "agents" / "runs" / f"{run_id}{suffix}"
    return path if path.is_absolute() else root / path


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


if __name__ == "__main__":
    main()
