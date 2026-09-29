# Architecture V2 detached migration proposals

These files are proposals for the schema owner. They must never be executed on
shared Supabase by an agent.

The 18 logical migrations are ordered in `manifest.json` and use two ownership
tracks:

- `versions/v2a*.py` contains canonical-table Alembic proposals. This directory
  is not listed in `alembic.ini`, every proposal has `down_revision = None`, and
  `migrations/env.py` does not import V2 metadata. After approval, the schema
  owner sets the live `down_revision`, moves each revision into
  `migrations/versions/`, and validates the associated backfill.
- `agents/sql/190_v2_*.sql` through `360_v2_*.sql` contain platform-owned
  tables, guards, and compatibility views. Matching rollback scripts live under
  `agents/sql/rollback/`.

Constraints added to populated canonical tables are `NOT VALID`. They are not
validated until Phase 12 produces and applies an owner-approved backfill.

Phase 3 adds `350_v2_record_creation.sql`. It extends the unified review-kind
constraint with `verify_actor` and adds the three actor source-origin codes
required by the specification. Its check constraint is deliberately `NOT
VALID`; the matching rollback refuses to discard live `verify_actor` history.

Phase 4 adds the wholly additive `360_v2_city_gazetteer.sql` proposal. It adds
only the static `us_city_coord` lookup table and its index. It is deliberately
not folded into the already validated 180–350 production apply package.
After the schema owner applies proposal 360 in an isolated environment, validate
the checksummed archive with the dry-run loader before explicitly loading it:

```powershell
python -m scripts.load_us_city_gazetteer
python -m scripts.load_us_city_gazetteer --live
```

The loader refuses non-local or non-test databases. It is never an authorized
production apply path.

Only the isolated test helper may exercise the detached set:

```powershell
$env:V2_TEST_DATABASE_URL = 'postgresql+psycopg2://ghus_test@127.0.0.1:55432/ghus_v2_test'
python scripts/architecture_v2_migrate.py up-down-up
```

The helper refuses non-local hosts, ports other than 55432, and database names
that do not end in `_test`. It never reads `DATABASE_URL`.
