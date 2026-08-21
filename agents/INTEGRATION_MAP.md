# GHUS Agents Integration Map

Reconnaissance-only map for adding an agents layer to GHUS-Platform. No database connection was opened, no migrations were run, and no implementation code was written.

## 0. Assumptions and Unverified Items

- `AGENTS.md` was read first. Its non-negotiables require `staged_record`, a single `promote()` canonical write path, ingest-time ER, dry-run default, provenance per written fact, no automatic overwrites, and no production DB access (`AGENTS.md:23`, `AGENTS.md:24`, `AGENTS.md:26`, `AGENTS.md:30`, `AGENTS.md:37`, `AGENTS.md:40`, `AGENTS.md:51`).
- I inspected files only. I did not inspect `.env` values and did not connect to the database.
- The frozen model file exists at `models/er_combiner_v1.joblib`, but I could not deserialize it here. The project venv points to a missing Windows Store Python shim (`.venv/pyvenv.cfg:1`, `.venv/pyvenv.cfg:4`, `.venv/pyvenv.cfg:5`), and fallback Python interpreters lacked `joblib`. Bundle contents are therefore inferred from `config/er_production.json` and code, not verified from the serialized object.
- `staged_record`: does not exist.
- `promote()`: does not exist.
- `agents/sql/`: does not exist.

## 1. Entity Resolution Surface

### Frozen Combiner / Pair-Scoring Entry Point

Production ingest surface:

- Module path: `src.ML.entity_resolution.resolve_or_create`.
- Class: `EntityResolver`.
- Constructor signature: `__init__(self, session: Session, project_root: Optional[Path] = None, bundle_path: str = DEFAULT_BUNDLE, config_path: str = DEFAULT_CONFIG)` (`src/ML/entity_resolution/resolve_or_create.py:84`).
- Public routing entry point: `resolve_actor(self, record: dict, source_id, dry_run: bool = False) -> ResolutionResult` (`src/ML/entity_resolution/resolve_or_create.py:248`, `src/ML/entity_resolution/resolve_or_create.py:249`).
- Pair-scoring entry point used by `resolve_actor`: `_score(self, record: dict, cands: pd.DataFrame) -> pd.DataFrame` (`src/ML/entity_resolution/resolve_or_create.py:144`).
- The scorer calls the frozen bundle model with `self.bundle["model"].predict_proba(X)[:, 1]` (`src/ML/entity_resolution/resolve_or_create.py:187`, `src/ML/entity_resolution/resolve_or_create.py:189`).
- Default model/config paths are `models/er_combiner_v1.joblib` and `config/er_production.json` (`src/ML/entity_resolution/resolve_or_create.py:53`, `src/ML/entity_resolution/resolve_or_create.py:54`, `src/ML/entity_resolution/resolve_or_create.py:88`, `src/ML/entity_resolution/resolve_or_create.py:89`).

Batch sweep surface:

- Module/script: `scripts.run_er_sweep`.
- Bundle loader: `load_bundle(path)` (`scripts/run_er_sweep.py:62`).
- Candidate scoring uses `bundle["model"].predict_proba(X.to_numpy(float))[:, 1]` (`scripts/run_er_sweep.py:173`, `scripts/run_er_sweep.py:174`).

Training surface:

- Module/script: `src.ML.entity_resolution.Train_production_combiner`.
- Model trained as `make_pipeline(StandardScaler(), LogisticRegression(...))` (`src/ML/entity_resolution/Train_production_combiner.py:125`, `src/ML/entity_resolution/Train_production_combiner.py:127`).
- Bundle saved with `model`, `features`, `tfidf_vectorizer`, `sbert_model_name`, `high_threshold`, and `low_threshold` (`src/ML/entity_resolution/Train_production_combiner.py:145`, `src/ML/entity_resolution/Train_production_combiner.py:147`, `src/ML/entity_resolution/Train_production_combiner.py:149`).

### HIGH and LOW Thresholds

Production values:

- `HIGH = 0.96`.
- `LOW = 0.1889311318077817`.

Where they currently live:

- `config/er_production.json` defines `high_threshold: 0.96` and `low_threshold: 0.1889311318077817` (`config/er_production.json:23`, `config/er_production.json:24`).
- `EntityResolver.__init__` loads them into `self.HIGH` and `self.LOW` (`src/ML/entity_resolution/resolve_or_create.py:88`, `src/ML/entity_resolution/resolve_or_create.py:91`).
- `scripts/run_er_sweep.py` separately loads the same config into local variables `HIGH` and `LOW` (`scripts/run_er_sweep.py:148`, `scripts/run_er_sweep.py:150`).
- `Train_production_combiner.py` has `HIGH_THRESHOLD = 0.96` and computes LOW from the fit with `ec._low_threshold(...)` (`src/ML/entity_resolution/Train_production_combiner.py:69`, `src/ML/entity_resolution/Train_production_combiner.py:137`, `src/ML/entity_resolution/Train_production_combiner.py:158`).
- `er_common.py` has evaluation constants `MIN_PRECISION = 0.97` and `LOW_ZONE_MIN_RECALL = 0.98`, but these are not deployed HIGH/LOW values (`src/ML/entity_resolution/er_common.py:38`, `src/ML/entity_resolution/er_common.py:39`).

### Feature Extraction Entry Point and Active Features

Production ingest feature builder:

- Module path: `src.ML.entity_resolution.resolve_or_create`.
- Function: `EntityResolver._score(self, record: dict, cands: pd.DataFrame) -> pd.DataFrame` (`src/ML/entity_resolution/resolve_or_create.py:144`).
- It builds `name_a`, `name_b`, `hubs_a`, `hubs_b`, `desc_a`, and `desc_b` (`src/ML/entity_resolution/resolve_or_create.py:155`, `src/ML/entity_resolution/resolve_or_create.py:161`).
- It computes TF-IDF name similarity, SBERT name similarity, name features, hub feature, mismatch features, and description features (`src/ML/entity_resolution/resolve_or_create.py:164`, `src/ML/entity_resolution/resolve_or_create.py:176`, `src/ML/entity_resolution/resolve_or_create.py:181`).
- It then selects only `self.features` from the bundle (`src/ML/entity_resolution/resolve_or_create.py:183`, `src/ML/entity_resolution/resolve_or_create.py:187`).

Component feature functions:

- `src.ML.entity_resolution.er_common.name_features(p: pd.DataFrame) -> pd.DataFrame` builds `acronym_match`, `containment`, `jaccard`, and `length_ratio` (`src/ML/entity_resolution/er_common.py:177`, `src/ML/entity_resolution/er_common.py:183`).
- `src.ML.entity_resolution.er_common.hub_feature(p: pd.DataFrame) -> pd.DataFrame` builds `hub_overlap` (`src/ML/entity_resolution/er_common.py:187`, `src/ML/entity_resolution/er_common.py:189`).
- `src.ML.entity_resolution.er_mismatch_features.mismatch_features(pairs: pd.DataFrame) -> pd.DataFrame` builds mismatch feature columns (`src/ML/entity_resolution/er_mismatch_features.py:114`, `src/ML/entity_resolution/er_mismatch_features.py:120`, `src/ML/entity_resolution/er_mismatch_features.py:276`, `src/ML/entity_resolution/er_mismatch_features.py:294`).
- `src.ML.entity_resolution.er_description_features.description_features(pairs: pd.DataFrame, sbert_model=None) -> pd.DataFrame` builds description feature columns (`src/ML/entity_resolution/er_description_features.py:31`, `src/ML/entity_resolution/er_description_features.py:37`, `src/ML/entity_resolution/er_description_features.py:99`, `src/ML/entity_resolution/er_description_features.py:168`).

Full active production feature list from `config/er_production.json`:

1. `tfidf_name_sim` (`config/er_production.json:5`)
2. `sbert_name_sim` (`config/er_production.json:6`)
3. `acronym_match` (`config/er_production.json:7`)
4. `containment` (`config/er_production.json:8`)
5. `jaccard` (`config/er_production.json:9`)
6. `length_ratio` (`config/er_production.json:10`)
7. `qualifier_mismatch` (`config/er_production.json:11`)
8. `unique_tokens_both_sides` (`config/er_production.json:12`)
9. `unique_token_count` (`config/er_production.json:13`)
10. `place_mismatch` (`config/er_production.json:14`)
11. `hierarchy_signal` (`config/er_production.json:15`)
12. `desc_tfidf_sim` (`config/er_production.json:16`)
13. `desc_token_overlap` (`config/er_production.json:17`)
14. `desc_location_conflict` (`config/er_production.json:18`)

Explicitly excluded:

- `hub_overlap` (`config/er_production.json:20`, `config/er_production.json:21`).
- Training also drops `desc_both_present`, `desc_sbert_sim`, and `numeric_mismatch` from production `FEATURES` (`src/ML/entity_resolution/Train_production_combiner.py:63`, `src/ML/entity_resolution/Train_production_combiner.py:67`).

### Field Absorption Function

Ingest-time absorb equivalent:

- Module path: `src.ML.entity_resolution.resolve_or_create`.
- Function: `EntityResolver._absorb(self, actor_id: str, record: dict) -> list` (`src/ML/entity_resolution/resolve_or_create.py:194`).
- Inheritable fields are defined in `INHERITABLE_FIELDS` (`src/ML/entity_resolution/resolve_or_create.py:57`, `src/ML/entity_resolution/resolve_or_create.py:62`).
- It only updates fields where the current actor value is empty and incoming value is non-empty (`src/ML/entity_resolution/resolve_or_create.py:199`, `src/ML/entity_resolution/resolve_or_create.py:204`).
- It updates `actor`, sets `verification_status='needs_review'`, and bumps `updated_at` (`src/ML/entity_resolution/resolve_or_create.py:210`, `src/ML/entity_resolution/resolve_or_create.py:212`).

Merge-time inheritance equivalent:

- Script/module: `scripts.actor_merge`.
- Function: `merge_actors(SessionLocal, winner_id, loser_id, *, score, method, decided_by, inherit_fields: bool = True, recompute_aggregates: bool = True)` (`scripts/actor_merge.py:170`, `scripts/actor_merge.py:171`).
- It defines another `INHERITABLE_FIELDS` list (`scripts/actor_merge.py:72`, `scripts/actor_merge.py:76`).
- It fills only winner-empty fields from loser non-empty fields (`scripts/actor_merge.py:254`, `scripts/actor_merge.py:257`).
- It marks inherited changes as `needs_review` and records inherited field names in `pre_merge_state` (`scripts/actor_merge.py:259`, `scripts/actor_merge.py:265`).

### Review-Queue Write Path

- Ingest write path: `EntityResolver._queue(self, actor_id_a: str, actor_id_b: str, score: float) -> str` writes `review_queue` (`src/ML/entity_resolution/resolve_or_create.py:215`, `src/ML/entity_resolution/resolve_or_create.py:223`).
- It is called in the `LOW <= score < HIGH` branch after creating a new actor (`src/ML/entity_resolution/resolve_or_create.py:270`, `src/ML/entity_resolution/resolve_or_create.py:274`).
- Batch write path: `scripts.run_er_sweep` also writes `review_queue`, including `features` JSON (`scripts/run_er_sweep.py:204`, `scripts/run_er_sweep.py:214`).
- Table: `review_queue`; primary key `review_id` UUID; unique pair constraint `uq_review_pair` (`src/db/models.py:596`, `src/db/models.py:603`, `src/db/models.py:599`, `src/db/models.py:600`).

### Candidate Blocking / Generation Logic

- Ingest shortlist: `EntityResolver._candidates(self, name: str, top_k: int = 40) -> pd.DataFrame` (`src/ML/entity_resolution/resolve_or_create.py:126`). It scores the incoming name against cached canonical actor names with the frozen TF-IDF vectorizer, keeps top `top_k`, then requires `_lex > 0.15` (`src/ML/entity_resolution/resolve_or_create.py:130`, `src/ML/entity_resolution/resolve_or_create.py:142`). The actor pool excludes merged-away rows (`src/ML/entity_resolution/resolve_or_create.py:101`, `src/ML/entity_resolution/resolve_or_create.py:110`).
- Batch sweep: `candidate_pairs(actors, vec, cand_threshold, max_per_actor)` uses TF-IDF neighbor pairs plus acronym, containment, and Jaccard blocking (`scripts/run_er_sweep.py:68`, `scripts/run_er_sweep.py:80`, `scripts/run_er_sweep.py:82`, `scripts/run_er_sweep.py:97`).
- Label-mining: `duplicate_candidate_pairs(names, *, jaccard_min=0.6)` uses containment, acronym, and content-token Jaccard (`scripts/build_duplicate_candidates.py:58`, `scripts/build_duplicate_candidates.py:82`). `build_rows(...)` ranks and caps rows (`scripts/build_duplicate_candidates.py:86`, `scripts/build_duplicate_candidates.py:107`).

## 2. Canonical Schema

Current ORM schema is in `src/db/models.py`. Initial migration creates `source`, `actor`, `event`, `hub`, and `person` (`migrations/versions/890c436ee256_initial_v1_schema.py:39`, `migrations/versions/890c436ee256_initial_v1_schema.py:46`, `migrations/versions/890c436ee256_initial_v1_schema.py:72`, `migrations/versions/890c436ee256_initial_v1_schema.py:87`, `migrations/versions/890c436ee256_initial_v1_schema.py:115`).

### `actor`

- Exists: yes.
- ORM class/table: `Actor`, `actor` (`src/db/models.py:142`, `src/db/models.py:144`).
- Primary key: `actor_id`, `UUID(as_uuid=True)`, default `uuid.uuid4` (`src/db/models.py:146`).
- Ingest-relevant columns: `name String(255)`, `description Text`, `website String(500)`, `location_city String(120)`, `state String(80)`, `country String(80)`, `source_id UUID -> source.source_id`, `verification_status String(30)`, `confidence Numeric(3,2)`, `created_at DateTime`, `updated_at DateTime` (`src/db/models.py:147`, `src/db/models.py:151`, `src/db/models.py:170`).

### `event`

- Exists: yes.
- ORM class/table: `Event`, `event` (`src/db/models.py:193`, `src/db/models.py:195`).
- Primary key: `event_id`, `UUID(as_uuid=True)`, default `uuid.uuid4` (`src/db/models.py:197`).
- Ingest-relevant columns: `name String(255)`, `description Text`, `location String(255)`, `website String(500)`, `source_id UUID -> source.source_id`, `created_at DateTime` (`src/db/models.py:198`, `src/db/models.py:213`).
- `city`, `state`, `country`, `verification_status`, `confidence`, and `updated_at`: does not exist.

### `hub`

- Exists: yes.
- ORM class/table: `Hub`, `hub` (`src/db/models.py:103`, `src/db/models.py:106`).
- Primary key: `hub_id`, `UUID(as_uuid=True)`, default `uuid.uuid4` (`src/db/models.py:108`).
- Ingest-relevant columns: `name String(255)`, `description Text`, `official_websites Text`, `primary_city String(120)`, `state String(80)`, `country String(80)` default `USA`, `source_id UUID -> source.source_id`, `verification_status String(30)`, `confidence Numeric(3,2)`, `created_at DateTime`, `updated_at DateTime` (`src/db/models.py:109`, `src/db/models.py:139`).
- Singular `website`: does not exist.

### `person`

- Exists: yes.
- ORM class/table: `Person`, `person` (`src/db/models.py:173`, `src/db/models.py:175`).
- Primary key: `person_id`, `UUID(as_uuid=True)`, default `uuid.uuid4` (`src/db/models.py:177`).
- Ingest-relevant columns: `full_name String(255)`, `bio Text`, `country_code String(5)`, `linkedin_url String(500)`, `source_id UUID -> source.source_id`, `verification_status String(30)`, `confidence Numeric(3,2)`, `created_at DateTime`, `updated_at DateTime` (`src/db/models.py:178`, `src/db/models.py:190`).
- `name`, `description`, generic `website`, `country`, `state`, and `city`: does not exist.

### Provenance Table

- Table named `provenance`: does not exist.
- Actual table: `source`.
- ORM class/table: `Source`, `source` (`src/db/models.py:64`, `src/db/models.py:66`).
- Primary key: `source_id`, `UUID(as_uuid=True)`, default `uuid.uuid4` (`src/db/models.py:68`).
- Columns: `source_type String(40)`, `url String(1000)`, `retrieved_at DateTime`, `description Text`, `trust_tier String(20)`, `created_at DateTime` (`src/db/models.py:69`, `src/db/models.py:74`).
- `name`, `country`, `website`, `verification_status`, `confidence`, and `updated_at`: does not exist on `source`.

## 3. Provenance Mechanism

- Main mechanism: row-level `source` rows plus `source_id` FKs. `Source` is documented as provenance, and entity tables carry `source_id` (`src/db/models.py:64`, `src/db/models.py:66`, `src/db/models.py:166`, `src/db/models.py:135`, `src/db/models.py:186`, `src/db/models.py:212`).
- ETL translators create one source row and attach it to inserted/updated rows. Example: `ecosystem_mapping.py` creates a spreadsheet source, flushes it, assigns `source_id`, and commits (`src/etl/translators/ecosystem_mapping.py:196`, `src/etl/translators/ecosystem_mapping.py:205`, `src/etl/translators/ecosystem_mapping.py:319`, `src/etl/translators/ecosystem_mapping.py:346`, `src/etl/translators/ecosystem_mapping.py:449`).
- Actor enrichment creates/reuses `Source(source_type='ai_inference', url=source_url, retrieved_at=datetime.now(), description=..., trust_tier='candidate')`, flushes, then sets `actor.source_id` (`src/enrichment/actor_enrichment_candidates.py:2128`, `src/enrichment/actor_enrichment_candidates.py:2171`, `src/enrichment/actor_enrichment_candidates.py:2282`).
- Additional mechanism: `actor_capability_fact` has both `source_id` and `evidence_url` (`src/db/models.py:313`, `src/db/models.py:326`).
- Additional mechanism: `proposal` has `evidence_url` and `evidence_snippet`, but no `source_id` FK (`src/db/models.py:617`, `src/db/models.py:628`).
- Audit mechanism: actor enrichment writes `data/interim/actor_enrichment_candidates.csv` with match/confidence/review/source/action columns (`src/enrichment/actor_enrichment_candidates.py:38`, `src/enrichment/actor_enrichment_candidates.py:1957`, `src/enrichment/actor_enrichment_candidates.py:1963`, `src/enrichment/actor_enrichment_candidates.py:2126`).
- Important reality: provenance is mostly row-level, not truly fact-level. The AGENTS rule says every written fact has a provenance row in the same transaction; current canonical tables usually point a whole row to one `source_id`.

## 4. Existing Actor Enrichment Candidate Script

Main script and pipeline:

- CLI wrapper: `scripts/run_actor_enrichment_candidates.py`.
- Pipeline class: `src.enrichment.actor_enrichment_candidates.ActorEnrichmentCandidatePipeline`.
- Constructor signature: `__init__(self, project_root: Path, session: Session, *, limit: Optional[int] = None, apply: bool = False, apply_threshold: float = DEFAULT_APPLY_THRESHOLD, commit_every: int = 50, model: str = SONNET, use_wikidata: bool = False, use_openalex: bool = True, openalex_sleep_seconds: float = 2.0, use_web_search: bool = False, web_search_sleep_seconds: float = 0.5, web_search_result_limit: int = 3, include_unlinked: bool = False, deterministic_only: bool = False, revisit_missing: bool = False, use_claude: bool = False, max_claude_calls: Optional[int] = 25, max_claude_cost: Optional[float] = 0.50, min_claude_candidate_score: float = 0.72, missing_fields: Optional[list[str]] = None, stop_after_claude_budget: bool = False)` (`src/enrichment/actor_enrichment_candidates.py:1891`, `src/enrichment/actor_enrichment_candidates.py:1917`).

### How It Defines a Gap

- Default missing fields are `description`, `website`, `location_city`, and `country` (`src/enrichment/actor_enrichment_candidates.py:48`).
- Possible target fields are `description`, `website`, `location_city`, `state`, and `country` (`src/enrichment/actor_enrichment_candidates.py:49`).
- CLI `--missing-field` supports `any`, `description`, `website`, `city`, `location_city`, `state`, and `country` (`scripts/run_actor_enrichment_candidates.py:78`, `scripts/run_actor_enrichment_candidates.py:80`).
- `normalize_missing_fields(fields)` returns defaults for no fields or `any`, validates aliases, and rejects unsupported values (`src/enrichment/actor_enrichment_candidates.py:716`, `src/enrichment/actor_enrichment_candidates.py:728`).
- `_missing_target_field_condition(self)` ORs null/empty checks across selected missing fields (`src/enrichment/actor_enrichment_candidates.py:1999`, `src/enrichment/actor_enrichment_candidates.py:2004`).
- `_sparse_actor_query(self)` filters by missing fields, excludes already processed enrichment sources unless `revisit_missing=True`, and excludes unlinked actors unless `include_unlinked=True` (`src/enrichment/actor_enrichment_candidates.py:2006`, `src/enrichment/actor_enrichment_candidates.py:2028`, `src/enrichment/actor_enrichment_candidates.py:2030`, `src/enrichment/actor_enrichment_candidates.py:2034`).

### How Confidence Is Computed and Gated

Fixed confidence shortcuts:

- Curated official organization match returns `confidence: 0.96` (`src/enrichment/actor_enrichment_candidates.py:1015`, `src/enrichment/actor_enrichment_candidates.py:1021`).
- Exact official website listing returns `confidence: 0.9` (`src/enrichment/actor_enrichment_candidates.py:1084`, `src/enrichment/actor_enrichment_candidates.py:1112`).
- High-confidence structured API candidate returns `0.9` for SEC and `0.88` otherwise (`src/enrichment/actor_enrichment_candidates.py:1192`, `src/enrichment/actor_enrichment_candidates.py:1226`).
- High-confidence web candidate returns `confidence: 0.88` (`src/enrichment/actor_enrichment_candidates.py:1291`, `src/enrichment/actor_enrichment_candidates.py:1316`).
- Aggregate or hub-context fallback can return `0.86` or `0.88` without external API confirmation (`src/enrichment/actor_enrichment_candidates.py:913`, `src/enrichment/actor_enrichment_candidates.py:937`, `src/enrichment/actor_enrichment_candidates.py:973`, `src/enrichment/actor_enrichment_candidates.py:975`).

Candidate match score:

- `_candidate_match_score(actor: Actor, candidate: ApiCandidate) -> float` uses normalized name similarity, parenthetical-free similarity, direct official-label match, and acronym hints (`src/enrichment/actor_enrichment_candidates.py:1144`, `src/enrichment/actor_enrichment_candidates.py:1154`).
- `_candidate_can_fill_missing_field(...)` requires a candidate value for a field currently empty on the actor (`src/enrichment/actor_enrichment_candidates.py:1129`, `src/enrichment/actor_enrichment_candidates.py:1140`).
- Strict API auto-accept only allows providers `ror`, `openalex`, and `wikidata` (`src/enrichment/actor_enrichment_candidates.py:1167`, `src/enrichment/actor_enrichment_candidates.py:1168`).

Apply gate:

- Default apply threshold is `0.85` (`src/enrichment/actor_enrichment_candidates.py:40`).
- `_apply_decision` rejects unmatched, below-threshold, or human-review decisions before update (`src/enrichment/actor_enrichment_candidates.py:2252`, `src/enrichment/actor_enrichment_candidates.py:2261`).
- It only changes target fields where actor values are empty (`src/enrichment/actor_enrichment_candidates.py:2263`, `src/enrichment/actor_enrichment_candidates.py:2279`).
- It sets `actor.source_id`, `verification_status='ai_inferred'`, and `actor.confidence=AI_CONFIDENCE` after source creation (`src/enrichment/actor_enrichment_candidates.py:2282`, `src/enrichment/actor_enrichment_candidates.py:2285`).
- `AI_CONFIDENCE` is fixed at `0.7`, separate from decision confidence (`src/enrichment/actor_enrichment_candidates.py:39`).

### How It Records Provenance

- `_get_or_create_source(self, actor: Actor, decision: dict) -> Source` chooses source description from decision type and `source_url` (`src/enrichment/actor_enrichment_candidates.py:2128`, `src/enrichment/actor_enrichment_candidates.py:2152`).
- It de-duplicates by `Source.source_type == 'ai_inference'`, URL, and description (`src/enrichment/actor_enrichment_candidates.py:2153`, `src/enrichment/actor_enrichment_candidates.py:2159`).
- It inserts `Source(source_id, source_type='ai_inference', url, retrieved_at, description, trust_tier='candidate')`, flushes, then `_apply_decision` assigns `actor.source_id` (`src/enrichment/actor_enrichment_candidates.py:2162`, `src/enrichment/actor_enrichment_candidates.py:2171`, `src/enrichment/actor_enrichment_candidates.py:2282`, `src/enrichment/actor_enrichment_candidates.py:2283`).
- This is same-session transactional behavior, but it is not fact-level provenance.

### How It Tracks Cost

- Claude pricing constants live in `src.ai.client.PRICING` for `HAIKU`, `SONNET`, and `OPUS` (`src/ai/client.py:27`, `src/ai/client.py:35`).
- `UsageTracker` stores input tokens, output tokens, calls, failures, and model (`src/ai/client.py:50`, `src/ai/client.py:56`).
- `UsageTracker.record(...)` consumes response usage; `cost_estimate()` multiplies tokens by model pricing (`src/ai/client.py:58`, `src/ai/client.py:67`).
- Actor enrichment constructs `UsageTracker(model=model)` in the pipeline constructor (`src/enrichment/actor_enrichment_candidates.py:1938`, `src/enrichment/actor_enrichment_candidates.py:1939`).
- Claude preflight blocks calls when Claude is disabled, call budget is exhausted, cost budget is exhausted, no candidate fills a missing field, or best candidate score is below `min_claude_candidate_score` (`src/enrichment/actor_enrichment_candidates.py:2291`, `src/enrichment/actor_enrichment_candidates.py:2337`).
- CLI exposes `--allow-claude`, `--max-claude-calls`, `--max-claude-cost`, and `--min-claude-candidate-score` (`scripts/run_actor_enrichment_candidates.py:70`, `scripts/run_actor_enrichment_candidates.py:77`).
- Progress logs include Claude calls and estimated cost every 20 actors (`src/enrichment/actor_enrichment_candidates.py:2574`, `src/enrichment/actor_enrichment_candidates.py:2580`).
- Wrapper prints `pipeline.tracker.summary()` at the end (`scripts/run_actor_enrichment_candidates.py:124`, `scripts/run_actor_enrichment_candidates.py:126`).

### How It Logs an Audit Trail

- Audit path: `data/interim/actor_enrichment_candidates.csv` (`src/enrichment/actor_enrichment_candidates.py:38`).
- Constructor opens append mode only for apply runs with an existing file; otherwise it writes a new file (`src/enrichment/actor_enrichment_candidates.py:1951`, `src/enrichment/actor_enrichment_candidates.py:1955`).
- Header includes actor metadata, candidates, decision fields, source URL, evidence summary, and action (`src/enrichment/actor_enrichment_candidates.py:1957`, `src/enrichment/actor_enrichment_candidates.py:1963`).
- `_write_audit_row(...)` writes each decision and flushes immediately (`src/enrichment/actor_enrichment_candidates.py:2110`, `src/enrichment/actor_enrichment_candidates.py:2126`).
- `RunStats.summary()` reports processed actors, candidates, decisions, no-candidates, no-match, review flags, would-apply, applied, low-confidence skips, API failures, AI failures, and Claude skip buckets (`src/enrichment/actor_enrichment_candidates.py:672`, `src/enrichment/actor_enrichment_candidates.py:710`).

### Dry-Run / Apply Transaction Behavior

- CLI default is dry-run; `--apply` is required for updates (`scripts/run_actor_enrichment_candidates.py:43`, `scripts/run_actor_enrichment_candidates.py:44`).
- Pipeline commits checkpoints only when `self.apply` and `commit_every` are set (`src/enrichment/actor_enrichment_candidates.py:2550`, `src/enrichment/actor_enrichment_candidates.py:2553`).
- End-of-run commits if `apply=True`; otherwise rolls back (`src/enrichment/actor_enrichment_candidates.py:2583`, `src/enrichment/actor_enrichment_candidates.py:2586`).

### What Must Change to Accept an Entity Type Parameter

To make the existing enrichment pipeline accept `--entity-type`, actor-specific assumptions must be abstracted behind an entity config:

- SQLAlchemy model and primary key: currently hard-coded to `Actor.actor_id` and Actor queries (`src/enrichment/actor_enrichment_candidates.py:1977`, `src/enrichment/actor_enrichment_candidates.py:1982`).
- Name field: currently assumes `actor.name` in prompts, logs, matching, and decisions.
- Target field map: currently `ENRICHMENT_TARGET_FIELDS`, `MISSING_FIELD_ALIASES`, and `CANDIDATE_FIELD_BY_ACTOR_FIELD` are actor-shaped (`src/enrichment/actor_enrichment_candidates.py:48`, `src/enrichment/actor_enrichment_candidates.py:64`).
- Relationship/context loader: currently actor-to-hub through `HubActor` and `Hub` (`src/enrichment/actor_enrichment_candidates.py:2007`, `src/enrichment/actor_enrichment_candidates.py:2030`).
- Provenance text: currently all source descriptions say actor enrichment (`src/enrichment/actor_enrichment_candidates.py:2131`, `src/enrichment/actor_enrichment_candidates.py:2151`).
- Apply function: currently writes only actor fields and actor-level status/confidence/source (`src/enrichment/actor_enrichment_candidates.py:2263`, `src/enrichment/actor_enrichment_candidates.py:2285`).
- Searchers and deterministic shortcuts: currently optimized for organization actors using ROR/OpenAlex/Wikidata/SEC plus hub official website context (`src/enrichment/actor_enrichment_candidates.py:1192`, `src/enrichment/actor_enrichment_candidates.py:1223`, `src/enrichment/actor_enrichment_candidates.py:1291`, `src/enrichment/actor_enrichment_candidates.py:1327`).
- Audit columns: currently actor-specific (`src/enrichment/actor_enrichment_candidates.py:1957`, `src/enrichment/actor_enrichment_candidates.py:1963`).

Minimum clean design: `EntityEnrichmentSpec` per entity type with model class, id field, display-name field, supported target fields, missing-field aliases, candidate-to-field mapping, context loader, deterministic decision builders, provenance description builder, and apply function. Then CLI adds `--entity-type actor|hub|event|person`, defaulting to actor for backward compatibility.

## 5. DB Access Conventions

Primary DB session module:

- Module: `src.db.session`.
- Loads `.env` from project root (`src/db/session.py:23`, `src/db/session.py:25`).
- Requires `DATABASE_URL`; otherwise raises (`src/db/session.py:27`, `src/db/session.py:30`).
- Engine is created with `future=True`, `pool_pre_ping=True`, and custom `connect_args` (`src/db/session.py:98`, `src/db/session.py:103`).
- `connect_args` include `connect_timeout: 15` and try to resolve public IPv4 `hostaddr` for PostgreSQL URLs (`src/db/session.py:80`, `src/db/session.py:90`).
- Session factory: `SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)` (`src/db/session.py:104`, `src/db/session.py:108`).

Migration DB config:

- Alembic loads `.env` from project root and overrides `sqlalchemy.url` from `DATABASE_URL` (`migrations/env.py:27`, `migrations/env.py:39`).
- Offline migration mode can emit SQL without DB connection (`migrations/env.py:59`, `migrations/env.py:68`).
- Online migration mode exists and would connect if run normally (`migrations/env.py:71`, `migrations/env.py:77`).

Admin app DB config:

- Admin app reads `DATABASE_URL` with `load_dotenv()` and `create_engine(url, pool_pre_ping=True)` (`src/admin/app.py:40`, `src/admin/app.py:49`).
- It says it is read-only except verification status, but uses the same configured `DATABASE_URL`, not a separate DB role (`src/admin/app.py:10`, `src/admin/app.py:12`, `src/admin/app.py:141`, `src/admin/app.py:149`).

Read-only role:

- A configured read-only DB role: does not exist.
- The only read-only behavior found is application-level UI restriction in `src/admin/app.py`, not a separate connection string or role.

Secrets/config:

- `.env` and `.env.local` are ignored by git (`.gitignore:1`, `.gitignore:3`).
- No `.env.example` file was found, even though `src/db/session.py` tells users to copy `.env.example` (`src/db/session.py:29`, `src/db/session.py:30`).
- Claude API key is loaded from environment and not from code (`src/ai/client.py:20`, `src/ai/client.py:23`, `src/ai/client.py:44`, `src/ai/client.py:45`).

## 6. Test and Migration Conventions

Tests:

- Test runner: `pytest` (`pyproject.toml:19`, `pyproject.toml:20`, `Makefile:18`, `Makefile:19`).
- Test path: `tests` (`pyproject.toml:29`, `pyproject.toml:30`).
- Actual automated tests: does not exist. Only package marker files were found under `tests/`.
- DB smoke script exists outside pytest: `scripts/smoke_test_actor_merge.py` uses `SessionLocal` and exercises merge/revert against a real DB (`scripts/smoke_test_actor_merge.py:29`, `scripts/smoke_test_actor_merge.py:188`, `scripts/smoke_test_actor_merge.py:216`).

Migrations:

- Alembic script location: `migrations` (`alembic.ini:8`).
- Version files live under `migrations/versions` by Alembic default (`alembic.ini:45`).
- `Makefile` migration command is `alembic upgrade head` (`Makefile:12`, `Makefile:13`).
- Naming convention in practice: revision id plus slug, e.g. `890c436ee256_initial_v1_schema.py`, `a7c2e91f4b03_add_review_queue.py`, `f6b9a8c7d2e1_add_actor_profile_fact_evaluation.py`.

Observed migration order from actual `down_revision` fields:

1. `890c436ee256` -> root (`migrations/versions/890c436ee256_initial_v1_schema.py:15`, `migrations/versions/890c436ee256_initial_v1_schema.py:16`)
2. `18f57ec36d6e` -> `890c436ee256` (`migrations/versions/18f57ec36d6e_add_organization_hierarchy_and_.py:15`, `migrations/versions/18f57ec36d6e_add_organization_hierarchy_and_.py:16`)
3. `e6d2f504a3ee` -> `18f57ec36d6e` (`migrations/versions/e6d2f504a3ee_preserve_hub_narrative_columns_for_.py:15`, `migrations/versions/e6d2f504a3ee_preserve_hub_narrative_columns_for_.py:16`)
4. `ce38c06ed809` -> `e6d2f504a3ee` (`migrations/versions/ce38c06ed809_preserve_hub_narrative_columns_for_.py:15`, `migrations/versions/ce38c06ed809_preserve_hub_narrative_columns_for_.py:16`)
5. `e51c426bf42a` -> `ce38c06ed809` (`migrations/versions/e51c426bf42a_add_event_scoring_table_for_strategic_.py:15`, `migrations/versions/e51c426bf42a_add_event_scoring_table_for_strategic_.py:16`)
6. `f3a9c1b2d4e5` -> `e51c426bf42a` (`migrations/versions/F3a9c1b2d4e5_add_actor_merge_log_and_soft_delete.py:15`, `migrations/versions/F3a9c1b2d4e5_add_actor_merge_log_and_soft_delete.py:16`)
7. `a7c9d2e8f104` -> `f3a9c1b2d4e5` (`migrations/versions/a7c9d2e8f104_add_hub_spreadsheet_gap_fields.py:15`, `migrations/versions/a7c9d2e8f104_add_hub_spreadsheet_gap_fields.py:16`)
8. `b8d1e6f2a903` -> `a7c9d2e8f104` (`migrations/versions/b8d1e6f2a903_add_nutricrops_gap_fields.py:15`, `migrations/versions/b8d1e6f2a903_add_nutricrops_gap_fields.py:16`)
9. `a7c2e91f4b03` -> `b8d1e6f2a903` (`migrations/versions/a7c2e91f4b03_add_review_queue.py:15`, `migrations/versions/a7c2e91f4b03_add_review_queue.py:16`)
10. `c4e8a1d9f206` -> `a7c2e91f4b03` (`migrations/versions/c4e8a1d9f206_add_event_content_fields.py:21`, `migrations/versions/c4e8a1d9f206_add_event_content_fields.py:22`)
11. `d5f9b2e7a318` -> `c4e8a1d9f206` (`migrations/versions/d5f9b2e7a318_drop_strategic_positioning.py:20`, `migrations/versions/d5f9b2e7a318_drop_strategic_positioning.py:21`)
12. `f6b9a8c7d2e1` -> `d5f9b2e7a318` (`migrations/versions/f6b9a8c7d2e1_add_actor_profile_fact_evaluation.py:15`, `migrations/versions/f6b9a8c7d2e1_add_actor_profile_fact_evaluation.py:16`)

## 7. Gaps and Contradictions

1. `staged_record` does not exist, but `AGENTS.md` says scraped data must land in `staged_record` and only `promote()` may insert/update canonical entity tables (`AGENTS.md:23`, `AGENTS.md:25`). No table, ORM class, migration, or insert path was found.

2. `promote()` does not exist, but `AGENTS.md` says it is the only allowed canonical write path (`AGENTS.md:24`, `AGENTS.md:25`). Current ETL writes canonical tables directly. Example: `ecosystem_mapping.py` creates/updates `Hub` rows directly and commits (`src/etl/translators/ecosystem_mapping.py:319`, `src/etl/translators/ecosystem_mapping.py:323`, `src/etl/translators/ecosystem_mapping.py:327`, `src/etl/translators/ecosystem_mapping.py:347`, `src/etl/translators/ecosystem_mapping.py:449`).

3. ER exists only for actors. `EntityResolver.resolve_actor(...)` is actor-specific and creates/updates `actor` rows only (`src/ML/entity_resolution/resolve_or_create.py:248`, `src/ML/entity_resolution/resolve_or_create.py:243`). There is no equivalent resolver for `event`, `hub`, or `person`.

4. Thresholds do not live in exactly one Python module. `AGENTS.md` says thresholds live in exactly one module (`AGENTS.md:56`). In reality, deployed HIGH/LOW live in JSON config, are copied into resolver instance attributes, and are also loaded separately in `run_er_sweep.py` (`config/er_production.json:23`, `config/er_production.json:24`, `src/ML/entity_resolution/resolve_or_create.py:90`, `src/ML/entity_resolution/resolve_or_create.py:91`, `scripts/run_er_sweep.py:150`).

5. Threshold-related constants are split across files. `er_common.py` defines `MIN_PRECISION` and `LOW_ZONE_MIN_RECALL`; training defines `HIGH_THRESHOLD`; config defines deployed HIGH/LOW; k-fold computes fold thresholds (`src/ML/entity_resolution/er_common.py:38`, `src/ML/entity_resolution/er_common.py:39`, `src/ML/entity_resolution/Train_production_combiner.py:69`, `config/er_production.json:23`, `config/er_production.json:24`, `src/ML/entity_resolution/run_er_kfold.py:117`).

6. `hub_overlap` is excluded from production features but still computed and used in evaluation variants. Config excludes it (`config/er_production.json:20`, `config/er_production.json:21`), while resolver/sweep still build it before feature selection (`src/ML/entity_resolution/resolve_or_create.py:177`, `scripts/run_er_sweep.py:125`, `scripts/run_er_sweep.py:130`). Eval/k-fold explicitly run `combiner_name_hub` with `hub_overlap` (`src/ML/entity_resolution/run_er_eval.py:134`, `src/ML/entity_resolution/run_er_eval.py:136`, `src/ML/entity_resolution/run_er_kfold.py:224`). This is a copying hazard for agents.

7. `run_er_sweep.py` is post-hoc ER over canonical actors, not ingest-time ER. `AGENTS.md` says ER runs at ingest, before insert, never after (`AGENTS.md:26`, `AGENTS.md:27`). The sweep scores existing canonical actors and can write review rows or execute auto-merges after the fact (`scripts/run_er_sweep.py:153`, `scripts/run_er_sweep.py:174`, `scripts/run_er_sweep.py:179`, `scripts/run_er_sweep.py:216`, `scripts/run_er_sweep.py:230`).

8. Review queue writes are duplicated. `EntityResolver._queue(...)` writes `review_queue`, and `run_er_sweep.py` also writes `review_queue` with a different payload including `features` JSON (`src/ML/entity_resolution/resolve_or_create.py:215`, `src/ML/entity_resolution/resolve_or_create.py:223`, `scripts/run_er_sweep.py:208`, `scripts/run_er_sweep.py:214`).

9. Field inheritance logic is duplicated. `resolve_or_create.py` and `actor_merge.py` each define `INHERITABLE_FIELDS` (`src/ML/entity_resolution/resolve_or_create.py:57`, `src/ML/entity_resolution/resolve_or_create.py:62`, `scripts/actor_merge.py:72`, `scripts/actor_merge.py:76`).

10. Matching/blocking logic is duplicated across modules. `er_common.py`, `run_er_sweep.py`, `build_duplicate_candidates.py`, `backfill_confirmed_merges.py`, and `er_mismatch_features.py` all contain name/acronym/token/hierarchy logic (`src/ML/entity_resolution/er_common.py:143`, `src/ML/entity_resolution/er_common.py:157`, `scripts/run_er_sweep.py:82`, `scripts/build_duplicate_candidates.py:58`, `scripts/actor_merge.py:170`, `src/ML/entity_resolution/er_mismatch_features.py:276`). This is a real drift risk.

11. Provenance is not fact-level in canonical tables. The `source` table exists and rows point to `source_id`, but there is no general fact provenance table. Actor enrichment writes row-level `actor.source_id`, not one provenance row per filled field (`src/db/models.py:64`, `src/db/models.py:74`, `src/enrichment/actor_enrichment_candidates.py:2282`, `src/enrichment/actor_enrichment_candidates.py:2285`). This does not meet the literal AGENTS rule that every written fact has a provenance row (`AGENTS.md:37`, `AGENTS.md:38`).

12. The table named `provenance` does not exist. The schema uses `source` instead (`src/db/models.py:64`, `src/db/models.py:66`).

13. `Event` lacks the standard provenance/review columns that repo docs claim every entity has. `models.py` says every entity table has provenance fields and created/updated timestamps (`src/db/models.py:7`, `src/db/models.py:9`), but `Event` has `source_id` and `created_at` only; no `verification_status`, no `confidence`, no `updated_at` (`src/db/models.py:193`, `src/db/models.py:213`).

14. `Person` does not match the requested ingest field shape. It has `full_name`, `bio`, `country_code`, and `linkedin_url`, but no `name`, `description`, `website`, `country`, `state`, or `city` columns (`src/db/models.py:177`, `src/db/models.py:185`). Agents must use field mapping.

15. `Hub` uses `official_websites`, not `website`, and `primary_city`, not `location_city` (`src/db/models.py:111`, `src/db/models.py:118`). Agents must use field mapping.

16. RAG-owned tables are still present in this repo's ORM. `AGENTS.md` says sibling `um6p-rag` owns only `search_doc`, `query_log`, and `proposal` (`AGENTS.md:7`, `AGENTS.md:9`), but this repo defines `SearchDoc`, `SearchDoc2`, `Proposal`, and `QueryLog` (`src/db/models.py:445`, `src/db/models.py:462`, `src/db/models.py:617`, `src/db/models.py:636`). A maintenance script also targets `search_doc` and `search_doc_2` (`scripts/actor_enrichment_maintenance/ghus_refresh_search_docs_from_actor.py:1`, `scripts/actor_enrichment_maintenance/ghus_refresh_search_docs_from_actor.py:104`).

17. `search_doc_2` still exists in ORM. If the intended state is to drop `search_doc_2`, the repo has not fully reflected that (`src/db/models.py:460`, `src/db/models.py:462`).

18. `run_description_eval.py` appears stale/broken against current `er_common.py`. It references `ec.CONFIG`, `ec.load_gold`, `ec.attach_actor_fields`, `ec.lexical_features`, `ec.evaluate_model`, and `ec.reports_to_frame`, but current `er_common.py` exposes different names such as `load_gold_with_split`, `name_features`, `evaluate`, and `to_frame` (`scripts/run_description_eval.py:152`, `scripts/run_description_eval.py:168`, `scripts/run_description_eval.py:182`, `scripts/run_description_eval.py:227`, `src/ML/entity_resolution/er_common.py:67`, `src/ML/entity_resolution/er_common.py:177`, `src/ML/entity_resolution/er_common.py:258`, `src/ML/entity_resolution/er_common.py:285`).

19. `run_description_eval.py` includes `hub_overlap` in its combiner feature list, contrary to the protected production decision if copied into production (`scripts/run_description_eval.py:202`, `scripts/run_description_eval.py:205`, `AGENTS.md:57`, `AGENTS.md:59`).

20. Migration metadata has a stale docstring. `a7c2e91f4b03_add_review_queue.py` says `Revises: f3a9c1b2d4e5`, but actual `down_revision` is `b8d1e6f2a903` (`migrations/versions/a7c2e91f4b03_add_review_queue.py:3`, `migrations/versions/a7c2e91f4b03_add_review_queue.py:16`).

21. No actual pytest test files were found under `tests/`. The project is configured for pytest, but current automated test coverage for ER/agents integration does not exist (`pyproject.toml:29`, `pyproject.toml:30`, `Makefile:18`, `Makefile:19`).

22. `.env.example` is referenced but not present. `src/db/session.py` tells users to copy `.env.example`, but repository search found no such file (`src/db/session.py:29`, `src/db/session.py:30`).

23. The admin app describes itself as read-only except review status, but it writes `verification_status` on any reflected table with a single primary key, using normal `DATABASE_URL` (`src/admin/app.py:10`, `src/admin/app.py:12`, `src/admin/app.py:141`, `src/admin/app.py:149`, `src/admin/app.py:316`, `src/admin/app.py:320`). This is UI-limited, not DB-role-limited.

24. The project venv is broken in this environment. `.venv/pyvenv.cfg` points to a Windows Store Python path that did not execute here (`.venv/pyvenv.cfg:1`, `.venv/pyvenv.cfg:4`, `.venv/pyvenv.cfg:5`). This blocked direct verification of `models/er_combiner_v1.joblib`.

25. Import casing is risky. Files live under `src/ML/...`, while `resolve_or_create.py` imports `src.ml.entity_resolution` in two places (`src/ML/entity_resolution/resolve_or_create.py:132`, `src/ML/entity_resolution/resolve_or_create.py:145`). That may work on Windows, but is not portable to a case-sensitive filesystem.

26. `AGENTS.md` says dry-run must exercise the same code path as live except commit boundary (`AGENTS.md:30`, `AGENTS.md:32`). `EntityResolver.resolve_actor(..., dry_run=True)` returns before `_create`, `_absorb`, or `_queue`, so dry-run does not exercise the same DB write path up to commit boundary (`src/ML/entity_resolution/resolve_or_create.py:255`, `src/ML/entity_resolution/resolve_or_create.py:258`, `src/ML/entity_resolution/resolve_or_create.py:265`, `src/ML/entity_resolution/resolve_or_create.py:272`).

27. Actor enrichment can fill hub-context descriptions as matched decisions without external source confirmation. This may be useful as a fallback, but it is not the same quality level as verified website/API evidence (`src/enrichment/actor_enrichment_candidates.py:952`, `src/enrichment/actor_enrichment_candidates.py:982`, `src/enrichment/actor_enrichment_candidates.py:2523`, `src/enrichment/actor_enrichment_candidates.py:2531`).

28. Existing ETL still uses direct canonical schema writes and updates, so adding agents without first introducing `staged_record`, `promote()`, and a central provenance/fact write path would deepen the inconsistency rather than fix it.
