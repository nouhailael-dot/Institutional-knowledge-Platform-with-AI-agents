# Architecture V2 additive schema preparation

This package adds new V2 reference tables, evidence/history tables, nullable compatibility columns, indexes, and compatibility views. It does not remove or rename any existing column, add constraints or `NOT NULL` requirements to populated legacy tables, change permissions on legacy tables, modify existing business rows, or deploy hub-proposal migration 310.

`actor.actor_type` and `actor.verification_status` remain present and work as before. New nullable `actor_category` and `record_status` columns are backfilled from them and kept synchronized in both directions during the compatibility period. Existing applications may continue reading and writing the legacy columns.

The package must be run only after schema-owner approval, after its full production dump and checksum complete successfully. The post-apply step verifies every pre-existing table row count, lists all new objects, and runs backend and frontend smoke queries in read-only transactions.

Deployment note: the schema package is safe for the currently deployed legacy application, but it is not sufficient for the current Phase 3 backend test contract. Do not deploy that backend with this package alone. Phase 3 migration 017/350 and the final V2 column cutover remain separately controlled changes.
