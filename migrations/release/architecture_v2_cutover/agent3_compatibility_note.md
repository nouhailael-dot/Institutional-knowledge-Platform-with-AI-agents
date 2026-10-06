# Build the Map (Agent 3) — compatibility note for its owner

`src/map_agent/` in the shared repository was not edited.

**What 500 removes:** the `actor_v1_compat`, `staged_record_agent3_compat` and
`actor_profile_current` views; actor columns `actor_type`, `actor_type_raw`,
`verification_status`, `record_status`, `state`, the eight narrative fields;
renames `location_city`→`city`, `alternate_names`→`alt_names`; tables
`organization_hierarchy`, `actor_profile`, `actor_capability_fact`.

**What Agent 3 reads from the canonical database: nothing.** A search of
`src/map_agent/` finds no SQL against `actor`, the compatibility views or the
removed tables. It keeps its runs in its own SQLite store (`run_store.py`) and
works on in-memory payloads.

**Where it still uses legacy names (payload level only):** `actor_type`,
`location_city`, `state`, `record_status` in `entity_schemas.py`,
`actor_profile.py`, `export.py`, `select.py`, `rankings.py`,
`people_research.py`. These are field names inside its own JSON and CSV exports,
not database columns, so 500 does not break Agent 3.

**What changes for its owner later (not a cutover blocker):**

1. If Agent 3 output is ever imported into the canonical database, map
   `actor_type` → `actor_category` (one of the 12 controlled codes, plus
   `category_type`), `location_city` → `city`, `state` → `state_code`; status
   comes from the GHUS verification service, never from the payload.
2. If it starts reading canonical actors, read `actor_read` (migration 488), which
   exposes the final names and the migrated narrative fields before and after 500.

Verified: the shared Python suite (which includes the map tests) and the map UI
Node tests pass after the shared-repo cutover changes (145 passed / 1 skipped;
Node 24 passed with `--experimental-vm-modules`).
