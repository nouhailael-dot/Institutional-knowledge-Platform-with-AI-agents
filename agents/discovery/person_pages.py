"""Bounded person capture and stored-profile re-verification."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from agents.common.raw_storage import RawContentStore
from agents.common.resolve_route import RouteDecision, load_person_candidates
from agents.discovery.normalize import normalize_person_record
from agents.discovery.promote import promote
from agents.discovery.run import _extract_stage_route_promote, _storage_path_for_doc
from agents.discovery.search.models import CandidateRecord, SearchResult
from agents.discovery.search.phase2 import OpenWebEventSource, fetch_score_stage_people
from agents.discovery.search.query_generation import (
    load_actor_query_hubs,
    load_seeded_sectors,
)
from agents.discovery.search.triage import normalized_domain
from agents.discovery.stage import InMemoryStageStore, SQLStageStore, mark_routed, stage_record

CAPTURE_QUERY_LABEL = "bounded held-actor page capture"


def load_actor_page_capture_candidates(session, *, run_id: str) -> list[CandidateRecord]:
    """Turn held actor home pages into pre-admitted, one-level capture candidates."""
    rows = (
        session.execute(
            text(
                "SELECT actor_id::text AS actor_id, name, website FROM actor "
                "WHERE merged_into_actor_id IS NULL "
                "AND website IS NOT NULL AND btrim(website) <> '' "
                "AND lower(COALESCE(to_jsonb(actor)->>'actor_category',to_jsonb(actor)->>'actor_type','')) <> 'aggregate' "
                "ORDER BY name"
            )
        )
        .mappings()
        .all()
    )
    candidates: list[CandidateRecord] = []
    for row in rows:
        url = str(row.get("website") or "").strip()
        domain = normalized_domain(url)
        if not domain:
            continue
        candidates.append(
            CandidateRecord.from_result(
                run_id=run_id,
                entity_type="person",
                result=SearchResult(
                    url=url,
                    title=str(row.get("name") or "").strip(),
                    snippet="",
                    provider="database",
                    query=CAPTURE_QUERY_LABEL,
                ),
                domain=domain,
                triage_verdict="accepted",
                triage_reason="bounded by a held actor page",
                fit_score=1.0,
            )
        )
    return candidates


def capture_people_from_actor_pages(
    *,
    people_enabled: bool,
    **kwargs,
) -> list[str]:
    """Feed held actor pages into the same fetch/extract/stage/route pipeline."""
    _require_people_enabled(people_enabled)
    session = kwargs.get("session")
    if session is None and "candidates" not in kwargs:
        raise RuntimeError("actor-page capture requires a session or injected candidates")
    candidates = kwargs.pop("candidates", None)
    if candidates is None:
        candidates = load_actor_page_capture_candidates(
            session,
            run_id=str(kwargs.get("run_id") or ""),
        )
    config = {**dict(kwargs.pop("config")), "people_enabled": True}
    root = Path(kwargs["root"])
    sectors = load_seeded_sectors(root)
    hubs = load_actor_query_hubs(session) if session is not None else []
    outcome = fetch_score_stage_people(
        candidates=candidates,
        config=config,
        sector_codes=[str(sector.get("code") or "").upper() for sector in sectors],
        hub_names=[str(hub.get("name") or "").strip() for hub in hubs],
        **kwargs,
    )
    return outcome.attention_reasons


def load_person_profile_targets(session) -> list[dict[str, object]]:
    rows = (
        session.execute(
            text(
                "SELECT p.person_id::text AS person_id, p.full_name AS name, p.title AS role, "
                "COALESCE(NULLIF(btrim(p.linkedin_url), ''), pdp.public_profile_url) "
                "AS public_profile_url, a.name AS affiliation "
                "FROM person p "
                "LEFT JOIN actor_person ap ON ap.person_id = p.person_id "
                "AND ap.is_current IS NOT FALSE "
                "LEFT JOIN actor a ON a.actor_id = ap.actor_id "
                "LEFT JOIN LATERAL ("
                "SELECT profile.public_profile_url FROM person_discovery_profile profile "
                "WHERE profile.person_id = p.person_id "
                "AND profile.public_profile_url IS NOT NULL "
                "AND btrim(profile.public_profile_url) <> '' "
                "ORDER BY profile.fetched_at DESC, profile.created_at DESC LIMIT 1"
                ") pdp ON TRUE "
                "WHERE COALESCE(NULLIF(btrim(p.linkedin_url), ''), "
                "pdp.public_profile_url) IS NOT NULL "
                "ORDER BY p.full_name"
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def reverify_person_profiles(
    *,
    run_id: str,
    config: dict[str, object],
    root: Path,
    session,
    live: bool,
    run_log,
    stats: dict[str, object],
    audit_rows: list[dict[str, object]],
    people_enabled: bool,
    person_create_preview: bool = False,
    profiles: list[dict[str, object]] | None = None,
    source=None,
    extractor=None,
    raw_store=None,
    stage_store=None,
    person_candidates=None,
    actor_resolver=None,
    cost_meter=None,
) -> list[str]:
    """Re-extract changed profiles and send missing profiles to person review."""
    _require_people_enabled(people_enabled)
    if person_create_preview and live:
        raise RuntimeError("person create preview cannot be combined with live writes")
    profiles = list(profiles) if profiles is not None else load_person_profile_targets(session)
    source = source or OpenWebEventSource({**config, "people_enabled": True})
    raw_store = raw_store or RawContentStore.from_config(root, config)
    stage_store = stage_store or (
        InMemoryStageStore() if session is None else SQLStageStore(session)
    )
    canonical_candidates = (
        list(person_candidates)
        if person_candidates is not None
        else ([] if session is None else load_person_candidates(session))
    )
    _ensure_person_stats(stats)
    attention_reasons: list[str] = []

    for profile in profiles:
        url = str(profile.get("public_profile_url") or "").strip()
        if not url:
            continue
        try:
            doc = source.fetch(url)
        except Exception as exc:  # noqa: BLE001 - status is supplied by the HTTP client.
            if _status_code(exc) == 404:
                _flag_profile_404(
                    profile=profile,
                    run_id=run_id,
                    stage_store=stage_store,
                    session=session,
                    live=live,
                    person_create_preview=person_create_preview,
                    audit_rows=audit_rows,
                )
                stats["profiles_404_review"] = int(stats["profiles_404_review"]) + 1
                stats["queued_for_review"] = int(stats["queued_for_review"]) + 1
                continue
            stats["fetch_failures"] = int(stats["fetch_failures"]) + 1
            attention_reasons.append(f"profile re-verification failed for {url}: {exc}")
            continue

        stats["pages_fetched"] = int(stats["pages_fetched"]) + 1
        prior_raw = run_log.find_raw_document(url=doc.url, content_hash=doc.content_hash)
        storage_path = _storage_path_for_doc(
            raw_store,
            run_id=run_id,
            doc=doc,
            prior_raw=prior_raw,
        )
        raw_document_id = run_log.write_raw_document(
            run_id=run_id,
            doc=doc,
            storage_path=storage_path,
        )
        if prior_raw is not None:
            stats["skipped_unchanged"] = int(stats["skipped_unchanged"]) + 1
            audit_rows.append(
                _profile_audit_row(
                    run_id,
                    profile,
                    status="skipped_unchanged",
                    content_hash=doc.content_hash,
                )
            )
            continue
        if extractor is None:
            raise RuntimeError("changed profile re-verification requires a person extractor")
        _extract_stage_route_promote(
            doc=doc,
            raw_document_id=raw_document_id,
            run_id=run_id,
            source_name="person_reverification",
            entity_type="person",
            extractor=extractor,
            stage_store=stage_store,
            session=session,
            live=live,
            candidates=canonical_candidates,
            root=root,
            stats=stats,
            audit_rows=audit_rows,
            actor_resolver=actor_resolver,
            people_enabled=True,
            person_create_preview=person_create_preview,
        )
        if cost_meter is not None:
            cost_meter.enforce()
    return attention_reasons


def _flag_profile_404(
    *,
    profile: dict[str, object],
    run_id: str,
    stage_store,
    session,
    live: bool,
    person_create_preview: bool,
    audit_rows: list[dict[str, object]],
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    record = normalize_person_record(
        {
            "name": profile.get("name"),
            "affiliation": profile.get("affiliation"),
            "role": profile.get("role"),
            "public_profile_url": profile.get("public_profile_url"),
            "research_area": None,
            "source_url": profile.get("public_profile_url"),
            "extracted_at": now,
            "sector_match": "in_sector",
        }
    )
    staged = stage_record(
        stage_store,
        run_id=run_id,
        raw_document_id=None,
        entity_type="person",
        record=record,
        prompt_version="person_reverification_v1",
    )
    person_id = str(profile.get("person_id") or "").strip() or None
    route = RouteDecision(
        zone="review",
        score=1.0,
        target_entity_id=person_id,
        candidate_ids=[person_id] if person_id else [],
        metadata={
            "candidate_name": str(profile.get("name") or "").strip(),
            "review_kind": "profile_404",
            "identity_outcome": "probable_move",
            "identity_reason": "stored professional profile returned 404; probable move",
        },
    )
    mark_routed(stage_store, staged, route)
    result = promote(
        staged,
        route,
        session=session,
        live=live,
        person_create_preview=person_create_preview,
        people_enabled=True,
    )
    audit_rows.append(
        _profile_audit_row(
            run_id,
            profile,
            status=result.action,
            zone="review",
            target_entity_id=person_id,
            error="stored professional profile returned 404; probable move",
        )
    )


def _profile_audit_row(
    run_id: str,
    profile: dict[str, object],
    *,
    status: str,
    content_hash: str = "",
    zone: str = "",
    target_entity_id: str | None = None,
    error: str = "",
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "source": "person_reverification",
        "entity_type": "person",
        "source_url": profile.get("public_profile_url"),
        "content_hash": content_hash,
        "natural_key": "",
        "zone": zone,
        "score": "",
        "target_entity_id": target_entity_id or "",
        "candidate_ids": [target_entity_id] if target_entity_id else [],
        "status": status,
        "error": error,
    }


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _ensure_person_stats(stats: dict[str, object]) -> None:
    for key in (
        "pages_fetched",
        "skipped_unchanged",
        "fetch_failures",
        "profiles_404_review",
        "records_extracted",
        "records_in_sector",
        "records_out_of_sector",
        "records_relevant",
        "records_staged",
        "records_promoted",
        "absorbed",
        "queued_for_review",
        "created",
        "already_held",
    ):
        stats.setdefault(key, 0)


def _require_people_enabled(enabled: bool) -> None:
    if not enabled:
        raise RuntimeError(
            "person discovery is disabled pending TARGETING_POLICY.md section 6 approval"
        )
