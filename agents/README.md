# GHUS Agents Layer

Phase 1 started as a single vertical slice: one source adapter (`climate_week`), one entity type (`event`), and deterministic event routing. Discovery now supports three event sources: `climate_week`, `unga_programme`, and `unga_guide`. Phase 2 adds weekly unattended execution, content-hash change detection, replay from stored raw content, and a short weekly digest. Phase 4 adds the generalized enrichment policy layer and incremental `search_doc` refresh.

The reporting agent is out of scope. Agent 3 is new-sector discovery, owned by a teammate. Reporting code is preserved on branch `shelved/reporting-agent`.

## Open-Web Search Triage

Open-web Phase 1 runs before configured-source fetching. It searches for
candidate pages, rejects obvious bad/known results deterministically, sends only
the survivors to Claude for fit triage, writes every candidate to
`search_candidate`, and produces a complete markdown report plus a rejection-only
report grouped by reason:

```powershell
python -m agents.discovery.search.run --entity event --report-out agents/runs/open-web-events.md
python -m agents.discovery.search.run --entity actor --report-out agents/runs/open-web-actors.md
```

The rejection report is written beside the complete report with
`-rejections.md` appended to its stem. `--rejection-report-out` can set a
different path. Report generation never deletes candidates.

For events and enabled person expertise runs, Phase 2 fetches accepted candidate
pages and sends them through the existing extract, normalize, stage, and
deterministic route path. Actor runs still stop after Phase 1 triage. Claude
native web search is the default provider because its
server-side search spend is added to the same `CostMeter` as query generation
and triage, so `max_usd_per_run` aborts runaway searches cleanly. Brave Search
is retained as a fallback and reads its key from `BRAVE_SEARCH_API_KEY` only
when `provider: brave` is configured. Search providers are selected in
`agents/config/sources.yaml` under `open_web_discovery`.

Events use database events, seeded sectors, and the configured event sources as
query-generation context. Actors use database actors only, excluding
`actor_type = 'aggregate'` and merged-away actors. People remain disabled until
`TARGETING_POLICY.md` section 6 is approved.

Caps are hard stops: `max_searches`, `max_candidates_triaged`, and
`max_usd_per_run` close the run as `attention` with a visible reason rather than
silently truncating. Phase 1-only paths reject URLs already seen in
`raw_document` by URL. Phase 2 event and person runs re-fetch accepted URLs and
compare the new content hash, so changed pages can be extracted while unchanged
pages skip the extraction call.

Phase 2 fetches at most 30 accepted pages and admits at most 10 previously unseen
domains per run. Both are hard, config-driven caps; hitting either closes the run
as `attention` and names the cap in `status_reason`. Fetches use the same
contactable User-Agent, rate limiting, and robots-aware HTTP layer as configured
sources. Redirect destinations are robots-checked before their page content is
requested. The `discovered_domain` table records domain status and cumulative
fetch, extraction, and promotion counts; apply
`agents/sql/120_discovered_domain.sql` before running Phase 2 against a database.

Claude web search widens the prompt-injection surface because the model has
already read searched pages before candidates reach this pipeline. The provider
therefore converts only `web_search_tool_result` / `web_search_result` blocks
into `(url, title, snippet, provider, query)` and discards free-form assistant
text. Triage and extraction never receive model commentary from the search
response.

Fetched open-web pages are also untrusted model input. Their raw content is stored
and content-hashed before extraction, the prompt labels the page body as
untrusted data, and the extractor can return only the forced event tool schema.
No free-form model text is routed or staged, and no extraction tool has database
write access. Records from discovered domains may route to create or review, but
never absorb. Exact canonical matches are forced to event review, and
`agents/discovery/promote.py` raises if an absorb route reaches it anyway.

## Run

Dry-run is the default:

```powershell
python -m agents.discovery.run --source climate_week --entity event
```

Other event sources:

```powershell
python -m agents.discovery.run --source unga_programme --entity event
python -m agents.discovery.run --source unga_guide --entity event
```

Use `--out path/to/audit.csv` to choose the audit CSV path and `--digest-out path/to/digest.md` to choose the weekly digest path. Use `--limit N` to cap discovered URLs. `--live` is the only flag that enables database writes.

## What Dry-Run Does

Normal dry-run uses the configured database for run logging, raw-document storage, staging, and candidate loading. That is intentional: dry-run must route against real candidates and exercise the same promotion statements as live. Canonical promotion and `search_doc` refresh differ from live only at the final boundary: dry-run rolls back and live commits.

Use `--offline` only for tests and local fixture runs. Offline mode uses fixture URLs, fixture extraction responses, in-memory run/stage stores, and no database session.

## Replay

Replay re-extracts from `raw_document.storage_path` and does not call the source adapter or network:

```powershell
python -m agents.discovery.run --replay <run_id>
```

`--source` and `--entity` are optional in replay mode when the original `scrape_run` row is available. Replay is dry-run unless `--live` is explicitly supplied.

## Change Detection

Before extraction, the runner checks whether `(url, content_hash)` already exists in `raw_document`. If it does, extraction is skipped and the run increments `skipped_unchanged`. This is the weekly cost control path: unchanged pages should produce zero LLM calls.

Fetched content is written under the configured `raw_storage_dir` and the path is stored in `raw_document.storage_path`, so extraction can be replayed without refetching.

## Run Status

Discovery closes runs honestly:

- `succeeded`: documents fetched and records staged, all fetched documents were skipped unchanged, or records were extracted but all were out of the seeded sectors.
- `attention`: a source yields zero URLs, zero documents are fetched, or fetched documents produce zero extracted records.
- `failed`: an exception aborts the run.

Every run writes `scrape_run.status_reason`, including successful cheap-week runs where all fetched documents were unchanged and extraction was skipped. The weekly digest prints the reason at the top so a no-op success is visibly different from a broken zero-output run. Apply `agents/sql/070_scrape_run_status_reason.sql` before running this version against a database.

`agents/config/sources.yaml` is parsed as YAML, not JSON. Keep using the `.yaml` file name; the shipped-config test loads this exact file so syntax errors fail before the Monday workflow.

The default run cost ceiling is `$0.50`, which leaves headroom for a full Climate Week extraction that has measured around `$0.14`. If the ceiling is exceeded, discovery closes the run as `attention`, writes audit and digest artifacts for the partial staged work, and exits nonzero for CI.

## Claude SDK Compatibility

The agents pin `anthropic==1.0.0`. That SDK no longer accepts `temperature`, `top_p`, or `top_k` on `messages.create`, and Anthropic's migration notes say current models do not use those sampling parameters. Discovery therefore does not send sampling controls. Extraction remains constrained through stable prompts, tool schemas, and forced `tool_choice`, but exact repeat-token determinism is not guaranteed by a temperature setting.

## Actor Discovery

E1 actor discovery has a tool-schema extractor and promotion branch, but no active configured source. Actor routing uses the existing frozen `EntityResolver` blocking and combiner scoring through `agents.common.resolve_route.route_actor`; all canonical actor writes still happen only in `agents/discovery/promote.py`. Before allowing actor auto-absorb on a new source, run:

```powershell
python -m agents.evals.score_distribution --limit 100
```

The score distribution script reports mean, median, share above HIGH, and the saved OOF reference metrics. It does not adjust thresholds.

Actor sources must be built around organisation profiles with enough evidence to support ER: at minimum name plus context such as description, country, website, or other profile fields. Event-listing organiser strings are not actor discovery sources.

Actor triage serves eight use cases: research collaboration, learning
expeditions, executive education, mentorship, student and faculty mobility,
open innovation, corporate engagement, and opportunity development. An actor is
rejected for fit only when sector relevance, engagement route, and strategic
ecosystem value all fall below their configured thresholds. Engagement routes
include memberships, leadership networks, ecosystem platforms, hosted visits,
executive programmes, event participation, and introductions as well as formal
partnerships. The former `complementarity` signal is intentionally absent because
the system has no evidence of UM6P capability gaps; it may return only after a
reviewed UM6P capability document is supplied as explicit triage context.

## Person Discovery

E2 person discovery extracts only public professional fields: name, affiliation, role, public profile URL, and research area. It intentionally excludes contact details and biographical detail beyond professional role.

The two acquisition modes share the same staged ingestion path. Expertise mode
builds deterministic queries from seeded sectors and hub themes, never from held
person names. Capture mode accepts only pages bounded by held actors; qualified
event pages already feed their published participants into the same person
staging and review path. Stored profile re-verification compares content hashes,
skips unchanged pages, and sends a 404 to review as a probable move without
deleting the person.

Production handling remains review-only. No discovered person is auto-created
or auto-absorbed into the canonical `person` table. The
`--enable-people-for-run --preview-person-create` exposes deterministic
create/skip/review outcomes for one dry run only; either override raises if
combined with `--live`. Person review
rows go to `person_review_queue` with provenance. Reviewer-approved affiliation
changes retain current state in `actor_person` and write history to
`person_change_log`; apply `agents/sql/130_person_change_log.sql` before using
that approval action.

```powershell
python -m agents.discovery.search.run --entity person --enable-people-for-run --preview-person-create
```

Person records may appear in exports and demos. This widens disclosure beyond
the internal database: `TARGETING_POLICY.md` section 6 approval must explicitly
cover expertise discovery, UM6P faculty, and named-person exports and demos.
The shipped switch remains `people_enabled: false`, and `sci_people` remains
disabled until that approval and its lawful basis are recorded.

## Event Sources

The three enabled discovery sources are event-only. `climate_week`, `unga_programme`, and `unga_guide` exist to populate the event table, not to derive actors from event organisers.

- `climate_week`: fetches only `https://www.climateweeknyc.org/event-search` and configured pagination URLs. It slices the `hubdb-listing` event cards into row batches before calling Claude, so it no longer sends the full multi-megabyte page at once.
- `unga_programme`: fetches the official UN General Assembly high-level meetings page at `https://www.un.org/en/ga/81/meetings/` using a browser-like, contactable User-Agent.
- `unga_guide`: fetches `https://ungaguide.com/`, follows minimal same-site pagination links, and treats a coming-soon page as an attention run rather than an extraction failure.

Network source adapters check `robots.txt`, use `GHUS_AGENT_CONTACT_EMAIL` in the User-Agent, and fail loudly if that contact address is missing.

## Weekly Schedule

`.github/workflows/weekly-discovery.yml` runs every Monday at 06:00 UTC and can also be started manually. Scheduled runs are dry-run. Live writes require manual `workflow_dispatch` with the `live` input set to true. The workflow first runs the Anthropic SDK compatibility test, then runs each discovery source independently, then deterministic actor profile enrichment, then incremental `search_doc` refresh. One source failure does not stop the remaining sources or downstream maintenance; the workflow writes `agents/runs/source-outcomes.md`, uploads all available artifacts, and exits nonzero at the end if any source or downstream step failed.

## Sector-Discovery Handoff

Discovery stages every extracted record. Records whose `sector_codes` match the seeded sector list continue to routing with `sector_match = 'in_sector'`. Records with no seeded-sector match are staged with `sector_match = 'out_of_sector'`; they are never routed or promoted. `sector_match` is the source-of-truth classification for the teammate handoff; `status` remains the staged-record lifecycle state.

The teammate-owned sector-discovery agent reads `staged_record WHERE sector_match = 'out_of_sector'`. It does not write to any table owned by this pipeline.

## Enrichment

Generalized enrichment entry point:

```powershell
python -m agents.enrichment.run --entity actor --field-set profile --limit 10
```

`agents/config/fields.yaml` defines enrichable fields and per-field auto-apply floors. Fields without a floor are proposal-only. Person fields are proposal-only. Low-confidence or human-review candidates with a `source_url` become `field_proposal` rows in live mode.

The actor adapter preserves the existing `ActorEnrichmentCandidatePipeline` candidate generation and cost tracking. Other entity types currently have field policies and sparse-row gap detection, but no candidate adapter yet, so the CLI logs counts and attempts no writes for them.

## Search Index

Incremental refresh targets `search_doc` only:

```powershell
python -m agents.index.refresh --entity all --limit 500
```

Rows are selected when their canonical `updated_at` is newer than the visible `search_doc.updated_at`/`indexed_at` column, or when no `search_doc` entry exists. If the current `search_doc` table has no timestamp column, the refresh logs a warning and selects missing entries only. Zero candidates is a logged no-op and never deletes rows.

TEMPORARY: `index_dirty` exists because `event` currently has no `updated_at`, so successful agent creates/absorbs need a safe way to become visible to the incremental `search_doc` refresh without changing upstream canonical tables. Promotion marks `(entity_type, entity_id)` in `index_dirty` in the same transaction as the canonical write; refresh unions those rows into its candidates and clears each marker only after that row is successfully upserted into `search_doc`. Remove this table and fallback once the upstream `event.updated_at` column exists and the normal stale-row comparison covers event changes.

## Do Not Change Without Discussion

1. Scraped data lands in `staged_record`; canonical entity writes under `agents/` belong only in `agents/discovery/promote.py` and `agents/enrichment/decisions.py`. Both enforce gap-guarded automatic updates, rowcount assertions, and provenance in the same transaction. No other module may write canonical entity tables.
2. Entity resolution/routing runs at ingest before any canonical insert.
3. Dry-run is the default; live writes require explicit `--live`.
4. Empty result sets are no-ops, never deletes or replacements.
5. Entity writes and provenance writes happen in one transaction; provenance failure aborts the entity write.
6. Never overwrite a non-null value automatically; fill gaps only and propose suspected corrections for humans.
7. Event routing deliberately does not use the frozen ER combiner. That combiner was trained on actor name/profile features; applying it to events would be a training/deployment distribution mismatch, the same class of failure that previously forced `desc_both_present` out of the actor model when production null patterns diverged from the gold set.
8. `search_doc` is a derived index rather than a fact store. Its rows are reconstructable from canonical rows that already carry provenance, so it deliberately does not get its own `source` rows. Every `search_doc` row must store `entity_type` and `entity_id` so the trail back to provenance stays explicit.
9. `climate_week`, `unga_programme`, and `unga_guide` are protected as event-only sources. They must not derive actors from organiser strings: replay `3aeb1d49-677b-435f-8453-138ed889818c` staged 121 such actors with a median ER score of 0.029 because the source yielded bare names without description, country, or website. Adding actor discovery requires a source built around organisation profiles, not event listings.
10. Open-web discovery is search-results only in Phase 1. Phase 2 may fetch only
    accepted event candidates, one level deep, through the bounded robots-aware
    path; it does not crawl links from those pages.
11. Open-web actor and person reference examples come from the database only.
    Aggregate actors and merged-away actors must not appear in the actor
    reference set.
12. Records from a discovered domain never auto-absorb until a human promotes
    that domain to trusted in a later phase.

## Phase 1/2 Notes

- The existing frozen combiner is trained on actors, so event routing does not use it. Events exact-match on `natural_key = normalized title + start date`; same-date fuzzy title matches go to the agent-owned `event_review_queue`.
- The existing `review_queue` table is actor-pair specific. Event review rows go to `event_review_queue` instead of extending that upstream table.
- The canonical `event` table has no `verification_status`, `confidence`, or `updated_at` columns, so Phase 1 cannot set `needs_review` on event rows without changing upstream schema.
- The agent SQL files are emitted under `agents/sql/`; the CLI does not run them.
