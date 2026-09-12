"""Manual and scheduled CLI for the discovery vertical slice."""

from __future__ import annotations

import argparse
import importlib
import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from agents.common.config import load_sources_config
from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.digest import write_digest
from agents.common.llm import ClaudeToolClient, FixtureToolClient
from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import (
    RouteDecision,
    load_actor_resolver_class,
    load_event_candidates,
    load_person_candidates,
    route_actor,
    route_event,
    route_person,
)
from agents.common.run_log import InMemoryRunLog, SQLRunLog, write_audit_csv
from agents.discovery.event_qualification import (
    actor_person_relation_record,
    participant_actor_records,
    participant_person_records,
    qualify_event,
    structured_page_date_rejection,
)
from agents.discovery.extractors.actor import ActorExtractor
from agents.discovery.extractors.climate_week import ClimateWeekExtractor
from agents.discovery.extractors.event import EventExtractor
from agents.discovery.extractors.person import PersonExtractor
from agents.discovery.extractors.unga_guide import UngaGuideExtractor
from agents.discovery.extractors.unga_programme import UngaProgrammeExtractor
from agents.discovery.normalize import (
    normalize_actor_record,
    normalize_event_record,
    normalize_person_record,
)
from agents.discovery.promote import (
    DISCOVERED_DOMAIN_PAYLOAD_KEY,
    guard_actor_absorb_route,
    promote,
)
from agents.discovery.relevance import IN_SECTOR, OUT_OF_SECTOR, classify_sector_matches
from agents.discovery.sources.base import FetchedDoc
from agents.discovery.sources.climate_week import ClimateWeekAdapter
from agents.discovery.sources.unga_guide import UngaGuideAdapter
from agents.discovery.sources.unga_programme import UngaProgrammeAdapter
from agents.discovery.stage import InMemoryStageStore, SQLStageStore, mark_routed, stage_record

logger = logging.getLogger(__name__)

SOURCE_ADAPTERS = {
    "climate_week": ClimateWeekAdapter,
    "unga_programme": UngaProgrammeAdapter,
    "unga_guide": UngaGuideAdapter,
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(root: Path | None = None) -> dict[str, object]:
    return load_sources_config(root or project_root())


def build_source(name: str, config: dict[str, object], root: Path, *, offline: bool = False):
    sources = dict(config.get("sources", {}))
    source_config = dict(sources.get(name, {}))
    if not source_config:
        raise ValueError(f"unknown source {name!r}")
    _raise_if_source_disabled(name, source_config)
    source_config.setdefault("source_name", name)
    adapter_cls = _source_adapter_class(name, source_config)
    return adapter_cls(source_config, project_root=root, offline=offline), source_config


def _source_adapter_class(name: str, source_config: dict[str, object]):
    adapter_path = str(source_config.get("adapter") or "").strip()
    if adapter_path:
        return _import_adapter_class(adapter_path)
    adapter_cls = SOURCE_ADAPTERS.get(name)
    if adapter_cls is None:
        raise NotImplementedError(f"source {name!r} is not implemented")
    return adapter_cls


def _import_adapter_class(adapter_path: str):
    module_path, sep, class_name = adapter_path.partition(":")
    if not sep:
        module_path, _, class_name = adapter_path.rpartition(".")
    if not module_path or not class_name:
        raise ValueError(
            "source adapter must be a Python path like "
            "'agents.discovery.sources.configured_pages:ConfiguredPagesAdapter'"
        )
    module = importlib.import_module(module_path)
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise ValueError(
            f"source adapter class {class_name!r} not found in {module_path!r}"
        ) from exc


def _raise_if_source_disabled(name: str, source_config: dict[str, object]) -> None:
    if not bool(source_config.get("disabled", False)):
        return
    reason = str(source_config.get("disabled_reason") or "no reason configured").strip()
    raise RuntimeError(f"source {name!r} is disabled: {reason}")


def build_extractor(
    entity_type: str,
    source_config: dict[str, object],
    root: Path,
    *,
    offline: bool = False,
    cost_meter: CostMeter,
):
    if entity_type not in {"event", "actor", "person"}:
        raise NotImplementedError(
            "discovery supports entity='event', entity='actor', or entity='person'"
        )
    if entity_type == "event" and source_config.get("extractor") == "climate_week":
        theme_mapping = source_config.get("theme_to_sector_codes")
        if not isinstance(theme_mapping, dict):
            raise ValueError("climate_week requires a theme_to_sector_codes mapping")
        return ClimateWeekExtractor(
            theme_to_sector_codes=theme_mapping,
            base_url=str(source_config.get("listing_url") or ""),
            min_row_count=int(source_config.get("min_event_row_count", 0) or 0),
        )
    fixture_response = source_config.get("llm_fixture_response")
    if fixture_response and offline:
        llm_client = FixtureToolClient.from_path(_resolve_path(root, str(fixture_response)))
    else:
        pricing = dict(source_config.get("llm_pricing", {}))
        llm_client = ClaudeToolClient(
            str(source_config.get("claude_model", "claude-haiku-4-5")),
            cost_meter=cost_meter,
            input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
            output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
        )
    if entity_type == "actor":
        return ActorExtractor(
            llm_client,
            max_tokens=int(source_config.get("max_tokens", 2048)),
        )
    if entity_type == "person":
        return PersonExtractor(
            llm_client,
            max_tokens=int(source_config.get("max_tokens", 2048)),
            people_enabled=bool(source_config.get("people_enabled", False)),
        )
    if source_config.get("extractor") == "unga_guide":
        return UngaGuideExtractor(
            llm_client,
            max_tokens=int(source_config.get("max_tokens", 2048)),
            coming_soon_markers=[
                str(value) for value in source_config.get("coming_soon_markers", [])
            ],
            people_enabled=bool(source_config.get("people_enabled", False)),
        )
    if source_config.get("extractor") == "unga_programme":
        return UngaProgrammeExtractor(
            llm_client, max_tokens=int(source_config.get("max_tokens", 2048))
        )
    return EventExtractor(
        llm_client,
        max_tokens=int(source_config.get("max_tokens", 2048)),
        row_batch_size=int(source_config.get("event_row_batch_size", 25)),
        min_row_count=int(source_config.get("min_event_row_count", 0) or 0),
        untrusted_content=bool(source_config.get("untrusted_content", False)),
        people_enabled=bool(source_config.get("people_enabled", False)),
    )


def run_pipeline(
    args,
    *,
    session=None,
    root: Path | None = None,
    run_log=None,
    stage_store=None,
    source=None,
    extractor=None,
    raw_store: RawContentStore | None = None,
    actor_resolver=None,
    run_date: date | None = None,
) -> dict[str, object]:
    root = root or project_root()
    config = load_config(root)
    replay_run_id = getattr(args, "replay", None)
    live = bool(getattr(args, "live", False))
    offline = bool(getattr(args, "offline", False))
    run_date = run_date or datetime.now(UTC).date()
    if live and offline:
        raise ValueError("--offline cannot be combined with --live")
    owned_session = False

    if session is None and not offline:
        from src.db.session import SessionLocal

        session = SessionLocal()
        owned_session = True

    history_log = run_log if replay_run_id else None
    if replay_run_id and history_log is None:
        if session is None:
            raise RuntimeError("--replay in offline mode requires an injected run_log")
        history_log = SQLRunLog(session)

    source_name = getattr(args, "source", None)
    entity_type = getattr(args, "entity", None)
    if replay_run_id:
        prior_run = history_log.get_run(replay_run_id)
        source_name = source_name or str(prior_run.get("source_name") or "")
        entity_type = entity_type or str(prior_run.get("entity_type") or "")
    if not source_name or not entity_type:
        raise ValueError(
            "--source and --entity are required unless --replay can resolve them from scrape_run"
        )

    if replay_run_id:
        sources = dict(config.get("sources", {}))
        source_config = dict(sources.get(source_name, {}))
        if not source_config and source_name == "open_web_search":
            source_config = _open_web_replay_config(config)
        if not source_config:
            raise ValueError(f"unknown source {source_name!r}")
        _raise_if_source_disabled(source_name, source_config)
    else:
        source, source_config = (
            (source, None)
            if source is not None
            else build_source(
                source_name,
                config,
                root,
                offline=offline,
            )
        )
        if source_config is None:
            source_config = dict(dict(config.get("sources", {})).get(source_name, {}))
        if entity_type not in source.entity_types:
            raise ValueError(f"source {source_name!r} does not support entity {entity_type!r}")

    people_enabled = bool(
        dict(config.get("open_web_discovery", {})).get("people_enabled", False)
    )
    people_enabled_for_run = bool(getattr(args, "enable_people_for_run", False))
    if people_enabled_for_run and live:
        raise RuntimeError("--enable-people-for-run cannot be combined with --live")
    people_enabled = people_enabled or people_enabled_for_run
    person_create_preview = bool(getattr(args, "preview_person_create", False))
    if entity_type == "person" and not people_enabled:
        raise RuntimeError(
            "person discovery is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    if person_create_preview and live:
        raise RuntimeError("--preview-person-create cannot be combined with --live")
    source_config["people_enabled"] = people_enabled
    qualification_config = dict(config.get("event_qualification", {}))

    cost_meter = CostMeter(max_usd=float(dict(config.get("cost", {})).get("max_usd_per_run", 0.0)))
    raw_store = raw_store or RawContentStore.from_config(root, source_config)
    run_log = run_log or (InMemoryRunLog() if offline else SQLRunLog(session))
    stage_store = stage_store or (InMemoryStageStore() if offline else SQLStageStore(session))
    extractor = extractor or build_extractor(
        entity_type,
        source_config,
        root,
        offline=offline,
        cost_meter=cost_meter,
    )

    run_config = dict(source_config)
    if replay_run_id:
        run_config["replay_of_run_id"] = replay_run_id
    run_id = run_log.start_run(
        source_name=source_name, entity_type=entity_type, live=live, config=run_config
    )

    stats = _empty_stats()
    audit_rows: list[dict[str, object]] = []
    out_path = _output_path(root, getattr(args, "out", None), run_id, suffix=".csv")
    digest_path = _output_path(root, getattr(args, "digest_out", None), run_id, suffix=".md")

    try:
        if offline:
            candidates = []
        elif entity_type == "event":
            candidates = load_event_candidates(session)
        elif entity_type == "person":
            candidates = load_person_candidates(session)
        else:
            candidates = []
        if not offline and entity_type == "actor" and actor_resolver is None:
            actor_resolver = load_actor_resolver_class()(session, project_root=root)
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
                    actor_resolver=actor_resolver,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                    discovered_domain=_discovered_domain(source_name, doc.url),
                    qualification_config=qualification_config,
                    people_enabled=people_enabled,
                    person_create_preview=person_create_preview,
                    run_date=run_date,
                )
                cost_meter.enforce()
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
                storage_path = _storage_path_for_doc(
                    raw_store, run_id=run_id, doc=doc, prior_raw=prior_raw
                )
                raw_document_id = run_log.write_raw_document(
                    run_id=run_id, doc=doc, storage_path=storage_path
                )
                if prior_raw is not None:
                    stats["skipped_unchanged"] += 1
                    _record_unchanged_skip(stats, prior_raw)
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
                    actor_resolver=actor_resolver,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                    qualification_config=qualification_config,
                    people_enabled=people_enabled,
                    person_create_preview=person_create_preview,
                    run_date=run_date,
                )
                cost_meter.enforce()

        logger.info("skipped unchanged documents: %d", stats["skipped_unchanged"])
        _finalize_cost(stats, extractor, cost_meter)
        _finalize_attention_reasons(stats, extractor)
        stats["audit_csv"] = str(out_path)
        stats["digest_md"] = str(digest_path)
        stats["cost_usd"] = cost_meter.spent_usd
        status, status_reason = _determine_run_status(stats, source=source)
        stats["status_reason"] = status_reason
        if status_reason:
            log = logger.info if status == "succeeded" else logger.warning
            log("run %s closed with status=%s reason=%s", run_id, status, status_reason)
        write_audit_csv(out_path, audit_rows)
        write_digest(
            digest_path,
            run_id=run_id,
            source=source_name,
            entity_type=entity_type,
            status=status,
            stats=stats,
        )
        run_log.close_run(
            run_id,
            status=status,
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        return {
            "run_id": run_id,
            "status": status,
            "stats": stats,
            "audit_rows": audit_rows,
            "digest_path": str(digest_path),
            "exit_code": 0,
        }
    except CostLimitExceeded as exc:
        _finalize_cost(stats, extractor, cost_meter)
        _finalize_attention_reasons(stats, extractor)
        stats["audit_csv"] = str(out_path)
        stats["digest_md"] = str(digest_path)
        stats["cost_usd"] = cost_meter.spent_usd
        status_reason = _cost_limit_status_reason(exc, cost_meter)
        stats["status_reason"] = status_reason
        logger.warning("run %s stopped at cost ceiling: %s", run_id, status_reason)
        write_audit_csv(out_path, audit_rows)
        write_digest(
            digest_path,
            run_id=run_id,
            source=source_name,
            entity_type=entity_type,
            status="attention",
            stats=stats,
        )
        run_log.close_run(
            run_id,
            status="attention",
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=status_reason,
        )
        return {
            "run_id": run_id,
            "status": "attention",
            "stats": stats,
            "audit_rows": audit_rows,
            "digest_path": str(digest_path),
            "exit_code": 1,
        }
    except Exception as exc:
        stats["failures"] += 1
        _finalize_cost(stats, extractor, cost_meter)
        _finalize_attention_reasons(stats, extractor)
        stats["audit_csv"] = str(out_path)
        stats["digest_md"] = str(digest_path)
        stats["cost_usd"] = cost_meter.spent_usd
        stats["status_reason"] = str(exc)
        write_audit_csv(out_path, audit_rows)
        write_digest(
            digest_path,
            run_id=run_id,
            source=source_name,
            entity_type=entity_type,
            status="failed",
            stats=stats,
        )
        run_log.fail_run(
            run_id,
            error=str(exc),
            stats=stats,
            cost_usd=cost_meter.spent_usd,
            status_reason=str(exc),
        )
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
    actor_resolver=None,
    discovered_domain: str | None = None,
    qualification_config: dict[str, object] | None = None,
    people_enabled: bool = False,
    person_create_preview: bool = False,
    run_date: date | None = None,
) -> None:
    if entity_type == "person" and not people_enabled:
        raise RuntimeError(
            "person discovery is disabled pending TARGETING_POLICY.md section 6 approval"
        )
    if person_create_preview and live:
        raise RuntimeError("person create preview cannot be combined with live writes")
    if entity_type == "event" and bool((qualification_config or {}).get("enabled", False)):
        preflight_reason = structured_page_date_rejection(
            doc.content,
            run_date=run_date or datetime.now(UTC).date(),
            config=qualification_config or {},
        )
        if preflight_reason:
            stats["events_qualification_evaluated"] = int(
                stats.get("events_qualification_evaluated", 0) or 0
            ) + 1
            stats["events_rejected_unqualified"] = int(
                stats.get("events_rejected_unqualified", 0) or 0
            ) + 1
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": source_name,
                    "entity_type": entity_type,
                    "source_url": doc.url,
                    "content_hash": doc.content_hash,
                    "natural_key": "",
                    "zone": "rejected",
                    "score": "",
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "rejected_date_window",
                    "error": preflight_reason,
                }
            )
            return
    extracted = extractor.extract(doc)
    if entity_type == "event":
        normalized = [normalize_event_record(record) for record in extracted]
    elif entity_type == "actor":
        normalized = [normalize_actor_record(record) for record in extracted]
    elif entity_type == "person":
        normalized = [normalize_person_record(record) for record in extracted]
    else:
        raise NotImplementedError(f"discovery does not support entity_type={entity_type!r}")
    normalized = _dedupe_by_natural_key(normalized)
    if entity_type == "event" and bool((qualification_config or {}).get("enabled", False)):
        for record in normalized:
            qualification = qualify_event(
                record,
                run_date=run_date or datetime.now(UTC).date(),
                config=qualification_config or {},
            )
            record.update(qualification.payload())
            _count_event_qualification(stats, qualification)
    if discovered_domain:
        normalized = [
            {**record, DISCOVERED_DOMAIN_PAYLOAD_KEY: discovered_domain}
            for record in normalized
        ]
    stats["records_extracted"] += len(normalized)
    if entity_type == "person":
        classified = [{**record, "sector_match": IN_SECTOR} for record in normalized]
    else:
        classified = classify_sector_matches(normalized, project_root=root)
    in_sector_count = sum(1 for record in classified if record.get("sector_match") == IN_SECTOR)
    out_of_sector_count = sum(
        1 for record in classified if record.get("sector_match") == OUT_OF_SECTOR
    )
    stats["records_in_sector"] += in_sector_count
    stats["records_out_of_sector"] += out_of_sector_count
    stats["records_relevant"] += in_sector_count
    participant_actor_resolver = actor_resolver
    for record in classified:
        if entity_type == "event" and record.get("sector_match") != OUT_OF_SECTOR:
            if (
                record.get("qualification_minable") is True
                and bool(
                    (qualification_config or {}).get(
                        "participant_extraction_enabled", False
                    )
                )
            ):
                participant_actor_resolver = _stage_event_participants(
                    event=record,
                    doc=doc,
                    raw_document_id=raw_document_id,
                    run_id=run_id,
                    source_name=source_name,
                    stage_store=stage_store,
                    session=session,
                    live=live,
                    actor_resolver=participant_actor_resolver,
                    people_enabled=people_enabled,
                    root=root,
                    stats=stats,
                    audit_rows=audit_rows,
                    discovered_domain=discovered_domain,
                )
            if record.get("qualification_mined_not_stored") is True:
                audit_rows.append(
                    {
                        "run_id": run_id,
                        "source": source_name,
                        "entity_type": entity_type,
                        "source_url": record.get("source_url"),
                        "content_hash": doc.content_hash,
                        "natural_key": record.get("natural_key"),
                        "zone": "mined",
                        "score": "",
                        "target_entity_id": "",
                        "candidate_ids": [],
                        "status": "mined_not_stored",
                        "error": "",
                    }
                )
                continue
        staged = stage_record(
            stage_store,
            run_id=run_id,
            raw_document_id=raw_document_id,
            entity_type=entity_type,
            record=record,
            prompt_version=extractor.prompt_version,
        )
        stats["records_staged"] += 1
        if staged.sector_match == OUT_OF_SECTOR:
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": source_name,
                    "entity_type": entity_type,
                    "source_url": record.get("source_url"),
                    "content_hash": doc.content_hash,
                    "natural_key": record.get("natural_key"),
                    "zone": OUT_OF_SECTOR,
                    "score": "",
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "out_of_sector",
                    "error": "",
                }
            )
            continue
        if entity_type == "event" and record.get("qualification_accepted") is False:
            staged.status = "rejected_unqualified"
            stage_store.upsert(staged)
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source": source_name,
                    "entity_type": entity_type,
                    "source_url": record.get("source_url"),
                    "content_hash": doc.content_hash,
                    "natural_key": record.get("natural_key"),
                    "zone": "rejected",
                    "score": "",
                    "target_entity_id": "",
                    "candidate_ids": [],
                    "status": "rejected_unqualified",
                    "error": record.get("qualification_reason"),
                }
            )
            continue
        if entity_type == "event":
            decision = route_event(record, candidates)
            decision = _review_discovered_event_absorb(
                record,
                decision,
                candidates,
                discovered_domain=discovered_domain,
            )
        elif entity_type == "actor":
            if actor_resolver is None:
                raise RuntimeError("actor routing requires an EntityResolver")
            decision = route_actor(record, actor_resolver)
            decision = guard_actor_absorb_route(staged, decision)
        elif entity_type == "person":
            decision = route_person(
                record,
                candidates,
                preview_create=person_create_preview,
            )
        else:
            raise NotImplementedError(f"discovery does not support entity_type={entity_type!r}")
        staged = mark_routed(stage_store, staged, decision)
        if entity_type == "person":
            result = promote(
                staged,
                decision,
                session=session,
                live=live,
                person_create_preview=person_create_preview,
            )
        else:
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


def _review_discovered_event_absorb(
    record: dict[str, object],
    route: RouteDecision,
    candidates: list[dict[str, object]],
    *,
    discovered_domain: str | None,
) -> RouteDecision:
    if not discovered_domain or route.zone != "absorb":
        return route
    target = next(
        (
            candidate
            for candidate in candidates
            if str(candidate.get("event_id") or candidate.get("entity_id") or candidate.get("id") or "")
            == str(route.target_entity_id or "")
        ),
        None,
    )
    if target is None:
        raise RuntimeError(
            "discovered-domain absorb override could not find its target event candidate"
        )
    staged_title = str(record.get("name") or record.get("title") or "").strip()
    candidate_title = str(target.get("name") or target.get("title") or "").strip()
    shared_start_date = str(
        record.get("start_date")
        or record.get("next_date")
        or target.get("start_date")
        or target.get("next_date")
        or ""
    ).split("T", 1)[0]
    if not staged_title or not candidate_title or not shared_start_date:
        raise RuntimeError(
            "discovered-domain event review requires staged title, candidate title, and shared date"
        )
    return replace(
        route,
        zone="review",
        metadata={
            **dict(route.metadata or {}),
            "staged_title": staged_title,
            "candidate_title": candidate_title,
            "shared_start_date": shared_start_date,
            "discovered_domain": discovered_domain,
            "route_policy": "discovered domains never auto-absorb",
        },
    )


def _count_event_qualification(stats: dict[str, object], qualification) -> None:
    stats["events_qualification_evaluated"] = int(
        stats.get("events_qualification_evaluated", 0) or 0
    ) + 1
    if qualification.attendable:
        stats["events_qualified_attendable"] = int(
            stats.get("events_qualified_attendable", 0) or 0
        ) + 1
    if qualification.minable:
        stats["events_qualified_minable"] = int(
            stats.get("events_qualified_minable", 0) or 0
        ) + 1
    if qualification.attendable and qualification.minable:
        stats["events_qualified_both"] = int(
            stats.get("events_qualified_both", 0) or 0
        ) + 1
    if qualification.mined_not_stored:
        stats["events_mined_not_stored"] = int(
            stats.get("events_mined_not_stored", 0) or 0
        ) + 1
    if not qualification.accepted:
        stats["events_rejected_unqualified"] = int(
            stats.get("events_rejected_unqualified", 0) or 0
        ) + 1


def _stage_event_participants(
    *,
    event: dict[str, object],
    doc: FetchedDoc,
    raw_document_id: str,
    run_id: str,
    source_name: str,
    stage_store,
    session,
    live: bool,
    actor_resolver,
    people_enabled: bool,
    root: Path,
    stats: dict[str, object],
    audit_rows: list[dict[str, object]],
    discovered_domain: str | None,
):
    actors = participant_actor_records(event)
    people = participant_person_records(event, people_enabled=people_enabled)
    stats["participant_actors_extracted"] = int(
        stats.get("participant_actors_extracted", 0) or 0
    ) + len(actors)
    stats["participant_people_extracted"] = int(
        stats.get("participant_people_extracted", 0) or 0
    ) + len(people)

    if actors and actor_resolver is None:
        if session is None:
            raise RuntimeError(
                "event participant actor routing requires an EntityResolver or database session"
            )
        actor_resolver = load_actor_resolver_class()(session, project_root=root)

    for actor in actors:
        normalized = normalize_actor_record(actor)
        if discovered_domain:
            normalized[DISCOVERED_DOMAIN_PAYLOAD_KEY] = discovered_domain
        classified = classify_sector_matches([normalized], project_root=root)[0]
        staged = stage_record(
            stage_store,
            run_id=run_id,
            raw_document_id=raw_document_id,
            entity_type="actor",
            record=classified,
            prompt_version=str(actor.get("prompt_version") or "event_participant_v1"),
        )
        stats["records_staged"] = int(stats.get("records_staged", 0) or 0) + 1
        stats["participant_actors_staged"] = int(
            stats.get("participant_actors_staged", 0) or 0
        ) + 1
        if staged.sector_match == OUT_OF_SECTOR:
            audit_rows.append(
                _participant_audit_row(
                    run_id=run_id,
                    source_name=source_name,
                    entity_type="actor",
                    doc=doc,
                    record=classified,
                    status="out_of_sector",
                    zone=OUT_OF_SECTOR,
                )
            )
            continue
        route = guard_actor_absorb_route(staged, route_actor(classified, actor_resolver))
        if discovered_domain and route.zone == "absorb":
            route = replace(
                route,
                zone="review",
                metadata={
                    **dict(route.metadata or {}),
                    "discovered_domain": discovered_domain,
                    "route_policy": "discovered domains never auto-absorb",
                },
            )
        staged = mark_routed(stage_store, staged, route)
        result = promote(staged, route, session=session, live=live)
        stats["records_promoted"] = int(stats.get("records_promoted", 0) or 0) + (
            0 if result.dry_run else 1
        )
        _count_zone(stats, route.zone)
        audit_rows.append(
            _participant_audit_row(
                run_id=run_id,
                source_name=source_name,
                entity_type="actor",
                doc=doc,
                record=classified,
                status=result.action,
                zone=route.zone,
                score=route.score,
                target_entity_id=route.target_entity_id,
                candidate_ids=route.candidate_ids,
            )
        )

    person_candidates = []
    if people and session is not None:
        person_candidates = load_person_candidates(session)
    for person in people:
        normalized = normalize_person_record(person)
        if discovered_domain:
            normalized[DISCOVERED_DOMAIN_PAYLOAD_KEY] = discovered_domain
        normalized["sector_match"] = IN_SECTOR
        staged = stage_record(
            stage_store,
            run_id=run_id,
            raw_document_id=raw_document_id,
            entity_type="person",
            record=normalized,
            prompt_version=str(person.get("prompt_version") or "event_participant_v1"),
        )
        stats["records_staged"] = int(stats.get("records_staged", 0) or 0) + 1
        stats["participant_people_staged"] = int(
            stats.get("participant_people_staged", 0) or 0
        ) + 1
        route = route_person(normalized, person_candidates)
        staged = mark_routed(stage_store, staged, route)
        result = promote(staged, route, session=session, live=live)
        stats["records_promoted"] = int(stats.get("records_promoted", 0) or 0) + (
            0 if result.dry_run else 1
        )
        _count_zone(stats, route.zone)
        audit_rows.append(
            _participant_audit_row(
                run_id=run_id,
                source_name=source_name,
                entity_type="person",
                doc=doc,
                record=normalized,
                status=result.action,
                zone=route.zone,
                score=route.score,
                target_entity_id=route.target_entity_id,
                candidate_ids=route.candidate_ids,
            )
        )

        relation = actor_person_relation_record(person, event=event)
        if relation is None:
            continue
        relation["sector_match"] = IN_SECTOR
        relation_staged = stage_record(
            stage_store,
            run_id=run_id,
            raw_document_id=raw_document_id,
            entity_type="actor_person",
            record=relation,
            prompt_version="event_participant_v1",
        )
        relation_staged.status = "awaiting_person_review"
        stage_store.upsert(relation_staged)
        stats["records_staged"] = int(stats.get("records_staged", 0) or 0) + 1
        stats["actor_person_relations_staged"] = int(
            stats.get("actor_person_relations_staged", 0) or 0
        ) + 1

    return actor_resolver


def _participant_audit_row(
    *,
    run_id: str,
    source_name: str,
    entity_type: str,
    doc: FetchedDoc,
    record: dict[str, object],
    status: str,
    zone: str,
    score: object = "",
    target_entity_id: object = "",
    candidate_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "source": source_name,
        "entity_type": entity_type,
        "source_url": record.get("source_url"),
        "content_hash": doc.content_hash,
        "natural_key": record.get("natural_key"),
        "zone": zone,
        "score": score,
        "target_entity_id": target_entity_id,
        "candidate_ids": candidate_ids or [],
        "status": status,
        "error": "",
    }


def _storage_path_for_doc(
    raw_store: RawContentStore,
    *,
    run_id: str,
    doc: FetchedDoc,
    prior_raw: dict[str, object] | None,
) -> str:
    prior_path = str((prior_raw or {}).get("storage_path") or "")
    if raw_store.exists(prior_path):
        return prior_path
    return raw_store.write(run_id=run_id, doc=doc)


def _open_web_replay_config(config: dict[str, object]) -> dict[str, object]:
    source_config = dict(config.get("open_web_discovery", {}))
    if not source_config:
        raise RuntimeError("open-web replay requires open_web_discovery configuration")
    source_config["claude_model"] = source_config.get("extraction_model") or source_config.get(
        "triage_model", "claude-sonnet-5"
    )
    source_config["llm_pricing"] = source_config.get("extraction_llm_pricing") or source_config.get(
        "triage_llm_pricing", {}
    )
    source_config["max_tokens"] = int(source_config.get("extraction_max_tokens", 2048))
    source_config["untrusted_content"] = True
    return source_config


def _discovered_domain(source_name: str, url: str) -> str | None:
    if source_name != "open_web_search":
        return None
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        raise RuntimeError(f"open-web raw document has invalid source URL {url!r}")
    return host


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


def _skip_audit_row(
    run_id: str, source_name: str, entity_type: str, doc: FetchedDoc
) -> dict[str, object]:
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
    elif zone == "skip":
        stats["already_held"] = int(stats.get("already_held", 0) or 0) + 1


def _dedupe_by_natural_key(records: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for record in records:
        natural_key = str(record.get("natural_key") or "").strip()
        if natural_key and natural_key in seen:
            continue
        if natural_key:
            seen.add(natural_key)
        deduped.append(record)
    return deduped


def _determine_run_status(stats: dict[str, object], *, source=None) -> tuple[str, str]:
    attention_reasons = [
        str(reason) for reason in stats.get("attention_reasons", []) or [] if str(reason).strip()
    ]
    if attention_reasons:
        return "attention", "; ".join(attention_reasons)
    documents_fetched = int(stats.get("documents_fetched", 0) or 0)
    skipped_unchanged = int(stats.get("skipped_unchanged", 0) or 0)
    records_extracted = int(stats.get("records_extracted", 0) or 0)
    records_staged = int(stats.get("records_staged", 0) or 0)
    records_in_sector = int(stats.get("records_in_sector", 0) or 0)
    urls_discovered = int(stats.get("urls_discovered", 0) or 0)

    if documents_fetched > 0 and skipped_unchanged == documents_fetched:
        return "succeeded", _unchanged_status_reason(stats)
    if records_extracted > 0 and records_in_sector == 0:
        return (
            "succeeded",
            (
                f"extracted {records_extracted} record(s); 0 matched seeded sectors; "
                "staged as out_of_sector"
            ),
        )
    if records_staged > 0:
        records_out_of_sector = int(stats.get("records_out_of_sector", 0) or 0)
        return (
            "succeeded",
            (
                f"staged {records_staged} record(s): {records_in_sector} in-sector, "
                f"{records_out_of_sector} out-of-sector"
            ),
        )
    rejected_unqualified = int(stats.get("events_rejected_unqualified", 0) or 0)
    if rejected_unqualified > 0:
        return (
            "succeeded",
            f"rejected {rejected_unqualified} event(s) that failed both qualification paths",
        )
    if documents_fetched > skipped_unchanged and records_extracted == 0:
        return "attention", "documents fetched but zero records extracted"
    if documents_fetched == 0 and urls_discovered == 0:
        reason = str(getattr(source, "last_discovery_reason", "") or "source yielded zero URLs")
        return "attention", reason
    if documents_fetched == 0:
        return "attention", "source yielded zero fetched documents"
    return "succeeded", ""


def _record_unchanged_skip(stats: dict[str, object], prior_raw: dict[str, object]) -> None:
    prior_run_id = str(prior_raw.get("run_id") or "").strip()
    if not prior_run_id:
        return
    run_ids = list(stats.get("unchanged_since_run_ids", []) or [])
    if prior_run_id not in run_ids:
        run_ids.append(prior_run_id)
    stats["unchanged_since_run_ids"] = run_ids


def _unchanged_status_reason(stats: dict[str, object]) -> str:
    skipped = int(stats.get("skipped_unchanged", 0) or 0)
    run_ids = [str(value) for value in stats.get("unchanged_since_run_ids", []) or []]
    if len(run_ids) == 1:
        return f"{skipped} document(s) unchanged since run {run_ids[0]}, no extraction needed"
    if run_ids:
        return (
            f"{skipped} document(s) unchanged since prior runs {', '.join(run_ids)}, "
            "no extraction needed"
        )
    return f"{skipped} document(s) unchanged, no extraction needed"


def _cost_limit_status_reason(exc: CostLimitExceeded, cost_meter: CostMeter) -> str:
    ceiling = cost_meter.max_usd
    ceiling_text = "unconfigured" if ceiling is None else f"${float(ceiling):.6f}"
    return (
        f"cost ceiling exceeded: spent ${float(cost_meter.spent_usd):.6f} "
        f"against ceiling {ceiling_text}; partial staged records retained ({exc})"
    )


def _finalize_attention_reasons(stats: dict[str, object], extractor) -> None:
    reasons = [
        str(reason) for reason in getattr(extractor, "attention_reasons", []) if str(reason).strip()
    ]
    if reasons:
        stats["attention_reasons"] = reasons


def _finalize_cost(stats: dict[str, object], extractor, cost_meter: CostMeter) -> None:
    llm_client = getattr(extractor, "llm_client", None)
    usage = getattr(llm_client, "usage", None)
    stats["llm"] = (
        usage.snapshot()
        if usage is not None
        else {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    cost_meter.spent_usd = max(
        cost_meter.spent_usd, float(stats["llm"].get("cost_usd", 0.0) or 0.0)
    )
    stats["cost"] = cost_meter.snapshot()


def _empty_stats() -> dict[str, int]:
    return {
        "urls_discovered": 0,
        "documents_fetched": 0,
        "skipped_unchanged": 0,
        "records_extracted": 0,
        "records_relevant": 0,
        "records_in_sector": 0,
        "records_out_of_sector": 0,
        "records_staged": 0,
        "records_promoted": 0,
        "absorbed": 0,
        "queued_for_review": 0,
        "created": 0,
        "already_held": 0,
        "failures": 0,
    }


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--entity")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--live", action="store_true", help="commit writes; absent means dry-run")
    parser.add_argument(
        "--preview-person-create",
        action="store_true",
        help="dry-run person identity routes using create/skip/review; never permits writes",
    )
    parser.add_argument(
        "--enable-people-for-run",
        action="store_true",
        help="enable person extraction for this dry run only; never permits live writes",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="test/fixture mode with no database or network access",
    )
    parser.add_argument("--out", help="audit CSV output path")
    parser.add_argument("--digest-out", help="weekly digest markdown output path")
    parser.add_argument(
        "--replay", help="existing scrape_run id whose stored raw content should be re-extracted"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_pipeline(parse_args(argv))
    stats = result["stats"]
    print(
        "status={status} run_id={run_id} documents={documents} skipped_unchanged={skipped} "
        "extracted={extracted} in_sector={in_sector} out_of_sector={out_of_sector} "
        "staged={staged} audit={audit} digest={digest}".format(
            status=result["status"],
            run_id=result["run_id"],
            documents=stats["documents_fetched"],
            skipped=stats["skipped_unchanged"],
            extracted=stats["records_extracted"],
            in_sector=stats["records_in_sector"],
            out_of_sector=stats["records_out_of_sector"],
            staged=stats["records_staged"],
            audit=stats["audit_csv"],
            digest=stats["digest_md"],
        )
    )
    exit_code = int(result.get("exit_code", 0) or 0)
    if exit_code:
        raise SystemExit(exit_code)


def _output_path(root: Path, value: str | None, run_id: str, *, suffix: str) -> Path:
    path = Path(value) if value else root / "agents" / "runs" / f"{run_id}{suffix}"
    return path if path.is_absolute() else root / path


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


if __name__ == "__main__":
    main()
