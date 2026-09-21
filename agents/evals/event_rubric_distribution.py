"""Evaluate stored open-web event pages with the current rubric, without DB access."""

from __future__ import annotations

import argparse
import html
import re
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl
from dotenv import load_dotenv

from agents.common.cost import CostLimitExceeded, CostMeter
from agents.common.llm import ClaudeToolClient
from agents.discovery.event_qualification import qualify_event
from agents.discovery.extractors.event import EVENT_TOOL_SCHEMA
from agents.discovery.search.event_scoring import (
    PROMPT_VERSION,
    EventListwiseReranker,
    EventRubricExtractor,
    event_score_band,
    read_analysis_cache,
    rerank_top_event_candidates,
    score_event_rubric,
    write_analysis_cache,
)
from agents.discovery.search.models import CandidateRecord
from agents.discovery.sources.base import FetchedDoc
from src.etl.common.header_resolver import HeaderMap, find_header_row
from src.etl.common.text_cleaning import is_section_header


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def evaluate_stored_run(
    *,
    root: Path,
    run_id: str,
    run_date: date,
    config: dict[str, object],
) -> dict[str, object]:
    if bool(config.get("people_enabled", False)):
        raise RuntimeError("stored event replay requires people_enabled=false")
    raw_dir = root / str(config.get("raw_storage_dir", "agents/raw_documents")) / run_id
    pages = sorted(raw_dir.glob("*"))
    pages = [page for page in pages if page.is_file()]
    if not pages:
        raise RuntimeError(f"stored run {run_id!r} has no raw pages under {raw_dir}")
    load_dotenv(root / ".env")
    meter = CostMeter(max_usd=float(config.get("max_usd_per_run", 5.0)))
    pricing = dict(config.get("extraction_llm_pricing", {}) or {})
    model = str(config.get("extraction_model", "claude-sonnet-5"))
    client = ClaudeToolClient(
        model,
        cost_meter=meter,
        input_usd_per_million=float(pricing.get("input_usd_per_million", 0.0)),
        output_usd_per_million=float(pricing.get("output_usd_per_million", 0.0)),
    )
    extractor = EventRubricExtractor(
        client, max_tokens=int(config.get("event_rubric_max_tokens", 4096))
    )
    reranker = EventListwiseReranker(
        client, max_tokens=int(config.get("event_rerank_max_tokens", 2048))
    )
    sector_codes = list(
        EVENT_TOOL_SCHEMA["properties"]["events"]["items"]["properties"][
            "sector_codes"
        ]["items"]["enum"]
    )
    hub_names = _load_hub_names(root)
    candidates: list[CandidateRecord] = []
    cache_hits = 0
    for page in pages:
        content = page.read_text(encoding="utf-8", errors="replace")
        doc = FetchedDoc.from_content(
            url=_source_url(content, fallback=f"stored://{run_id}/{page.name}"),
            content=content,
            content_type="text/html",
        )
        cache_path = (
            root
            / str(config.get("raw_storage_dir", "agents/raw_documents"))
            / "event_analysis"
            / f"{doc.content_hash}.{PROMPT_VERSION}.json"
        )
        try:
            analysis = read_analysis_cache(
                cache_path,
                sector_codes=sector_codes,
                run_date=run_date,
            )
            if analysis is None:
                analysis = extractor.extract(
                    doc,
                    sector_codes=sector_codes,
                    hub_names=hub_names,
                    run_date=run_date,
                )
                write_analysis_cache(cache_path, analysis)
            else:
                cache_hits += 1
        except CostLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - retain every failed page in the evaluation.
            candidates.append(
                CandidateRecord(
                    candidate_id=str(uuid.uuid4()),
                    run_id=run_id,
                    entity_type="event",
                    query="stored-page replay",
                    provider="stored",
                    url=doc.url,
                    title=None,
                    snippet=None,
                    domain="stored",
                    triage_verdict="analysis_failed",
                    triage_reason=f"event rubric analysis failed: {exc}",
                    fit_score=None,
                    page_fetched=True,
                    score_band="analysis_failed",
                )
            )
            continue
        score = score_event_rubric(analysis.rubric, config=config)
        qualification = qualify_event(
            analysis.record,
            run_date=run_date,
            config={"forward_window_months": 12},
            rubric=analysis.rubric,
        )
        band = event_score_band(score.total, config)
        if band != "auto_low" and not analysis.record.get("title"):
            band = "auto_low"
        elif band == "auto_high" and not qualification.paths:
            band = "review"
        candidates.append(
            CandidateRecord(
                candidate_id=str(uuid.uuid4()),
                run_id=run_id,
                entity_type="event",
                query="stored-page replay",
                provider="stored",
                url=doc.url,
                title=str(analysis.record.get("title") or "") or None,
                snippet=None,
                domain="stored",
                triage_verdict=(
                    "accepted" if band == "auto_high" else "rejected" if band == "auto_low" else "review"
                ),
                triage_reason="stored-page event rubric evaluation",
                fit_score=score.total,
                page_fetched=True,
                rubric=analysis.rubric,
                record_preview=analysis.record,
                score_breakdown=score.contributions,
                score_band=band,
                sector_codes=tuple(analysis.record.get("sector_codes") or []),
                qualification_paths=qualification.paths,
            )
        )
        meter.enforce()
    scored = [candidate for candidate in candidates if candidate.rubric is not None]
    reranked, rerank_attention = rerank_top_event_candidates(
        scored,
        reranker=reranker,
        config=config,
    )
    reranked_by_id = {candidate.candidate_id: candidate for candidate in reranked}
    candidates = [
        reranked_by_id.get(candidate.candidate_id, candidate) for candidate in candidates
    ]
    meter.enforce()
    return {
        "run_id": run_id,
        "run_date": run_date.isoformat(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "pages": len(pages),
        "cache_hits": cache_hits,
        "analysis_failures": sum(
            candidate.score_band == "analysis_failed" for candidate in candidates
        ),
        "cost_usd": meter.spent_usd,
        "bands": Counter(candidate.score_band for candidate in candidates),
        "qualifications": Counter(
            path for candidate in candidates for path in candidate.qualification_paths
        ),
        "rerank_attention": rerank_attention,
        "candidates": candidates,
    }


def to_markdown(summary: dict[str, object]) -> str:
    candidates = list(summary["candidates"])
    bands = Counter(summary["bands"])
    qualifications = Counter(summary["qualifications"])
    page_count = int(summary["pages"])
    complete = not summary["analysis_failures"] and not summary["rerank_attention"]
    lines = [
        "# Event Rubric Stored-Page Evaluation",
        "",
        f"Status: {'complete' if complete else 'incomplete'}",
        f"Run: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Model: `{summary['model']}`",
        f"Prompt version: `{summary['prompt_version']}`",
        f"Pages: {page_count}",
        f"Analysis cache hits: {summary['cache_hits']}",
        f"Analysis failures: {summary['analysis_failures']}",
        f"Evaluation cost: ${float(summary['cost_usd']):.6f}",
        "",
        "| Outcome | Count | Proportion |",
        "| --- | ---: | ---: |",
    ]
    for band in ("auto_high", "review", "auto_low", "analysis_failed"):
        count = bands[band]
        lines.append(f"| {band} | {count} | {count / page_count:.1%} |")
    for path in ("attendable", "minable"):
        count = qualifications[path]
        lines.append(f"| {path} | {count} | {count / page_count:.1%} |")
    lines.extend(
        [
            "",
            "| Score | Band | Qualification | Rerank | Event | URL | Reason |",
            "| ---: | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.rerank_position is None,
            item.rerank_position or 10_000,
            -float(item.fit_score or 0.0),
        ),
    ):
        title = str((candidate.record_preview or {}).get("title") or "missing title")
        lines.append(
            f"| {'' if candidate.fit_score is None else f'{candidate.fit_score:.3f}'} | "
            f"{candidate.score_band} | "
            f"{', '.join(candidate.qualification_paths) or 'none'} | "
            f"{candidate.rerank_position or ''} | {_escape(title)} | {_escape(candidate.url)} | "
            f"{_escape(candidate.triage_reason or '')} |"
        )
    if summary["rerank_attention"]:
        lines.extend(["", "Rerank attention: " + "; ".join(summary["rerank_attention"])])
    return "\n".join(lines) + "\n"


def _load_hub_names(root: Path) -> list[str]:
    workbook_path = root / "data" / "raw" / "Ecosystem_Mapping_The_Final_UpV.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = workbook["Ecosystem Mapping"]
    header, data_start = find_header_row(sheet, ["Actor Name", "Actor Category"])
    header_map = HeaderMap(header)
    names: list[str] = []
    for values in sheet.iter_rows(min_row=data_start, values_only=True):
        row = list(values)
        name = str(header_map.get(row, "Actor Name") or "").strip()
        if name and not is_section_header(row) and name not in names:
            names.append(name)
    workbook.close()
    return names


def _source_url(content: str, *, fallback: str) -> str:
    patterns = (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
    )
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return fallback


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--out")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from agents.common.config import load_sources_config

    args = parse_args(argv)
    root = project_root()
    config = dict(load_sources_config(root)["open_web_discovery"])
    summary = evaluate_stored_run(
        root=root,
        run_id=args.run_id,
        run_date=args.run_date,
        config=config,
    )
    markdown = to_markdown(summary)
    if args.out:
        path = Path(args.out)
        if not path.is_absolute():
            path = root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 1 if summary["analysis_failures"] or summary["rerank_attention"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
