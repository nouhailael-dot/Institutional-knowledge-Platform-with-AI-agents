"""Build migration 800 (organization -> actor names, back again) and its package.

    python migrations/proposed/actor_800/generate.py --database ghus_prod800_test

Reads, from a LOCAL copy of production (restored from the backup taken just before;
never Supabase): every public relation named organization, their columns named
organization, the constraint/index/trigger/policy names on them, the actor_* stand-in
views 720 left, and the functions 720 (and 790) rewrote with organization names.
Writes:
    ../deferred/800_actor_names.sql
    ../deferred/rollback/800_actor_names.sql
    preflight.sql, verify.sql, ledger.sql, catalog.json (this folder)

GHUS decision of 25 Nov 2026 (Ismail, with Nouhaila's database work paused): the
database says actor again, as the code does. Nothing Nouhaila built is undone:
730 (the template view), 740 (event fields), 750/770 (the organization details
columns) and 790 (one organization table) keep every change; only the names change.
The user-facing category label "Company / Corporate Organization" stays (the
platform says Organization to people).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DEFERRED = HERE.parent / "deferred"
ID = "800"
NAME = "800_actor_names.sql"

# The functions whose bodies 720 (and later 790) wrote with organization names. Others
# that mention "organization" (legacy reports, category mappings) predate 720 and keep
# their text.
REWRITTEN = ("ghus_guard_organization_status", "ghus_organization_details_on_pointer",
             "ghus_organization_details_on_topicless_fact", "ghus_organization_details_refresh",
             "ghus_prevent_organization_family_cycle", "ghus_project_organization_verification_status",
             "ghus_guard_ranking_is_university", "ghus_guard_subscription_run_append_only",
             "ghus_validate_entity_edge")
# Text inside those bodies that must keep saying organization (people read it, or it
# names something that is not renamed).
KEEP = ("Corporate Organization",)


def back(name: str) -> str:
    return name.replace("organization", "actor")


def q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def arr(items) -> str:
    return q("{" + ",".join(items) + "}") + "::text[]"


def read_catalog(database: str) -> dict:
    url = f"postgresql://ghus_test@127.0.0.1:55432/{database}"
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.relname, c.relkind::text FROM pg_class c
                       WHERE c.relnamespace = 'public'::regnamespace AND c.relname LIKE '%organization%'
                         AND c.relkind IN ('r','v','m','p') ORDER BY c.relkind, c.relname""")
        relations = cur.fetchall()
        columns = {}
        for rel, _ in relations:
            cur.execute("""SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass
                           AND attnum > 0 AND NOT attisdropped ORDER BY attnum""", (f"public.{rel}",))
            columns[rel] = [r[0] for r in cur.fetchall()]
        # The stand-ins: an actor_* view per renamed relation, over exactly that relation.
        cur.execute("""SELECT v.relname, pg_get_viewdef(v.oid), obj_description(v.oid, 'pg_class'),
                              coalesce(array_to_string(v.reloptions, ','), '')
                         FROM pg_class v WHERE v.relnamespace = 'public'::regnamespace AND v.relkind = 'v'
                          AND v.relname = ANY(%s) ORDER BY v.relname""", ([back(r) for r, _ in relations],))
        stand_ins = [{"name": n, "definition": d, "comment": c, "options": o} for n, d, c, o in cur.fetchall()]
        cur.execute("""SELECT DISTINCT v.relname FROM pg_rewrite r JOIN pg_depend d ON d.objid = r.oid
                         JOIN pg_class ref ON ref.oid = d.refobjid JOIN pg_class v ON v.oid = r.ev_class
                        WHERE ref.relname = ANY(%s) AND ref.relnamespace = 'public'::regnamespace
                          AND v.oid <> ref.oid AND NOT (v.relname = ANY(%s))""",
                    ([s["name"] for s in stand_ins], [s["name"] for s in stand_ins]))
        built_on = [r[0] for r in cur.fetchall()]
        if built_on:
            raise SystemExit(f"objects are built on the stand-ins (would be dropped): {built_on}")
        cur.execute("""SELECT grantee, table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type)
                         FROM information_schema.role_table_grants
                        WHERE table_schema = 'public' AND table_name = ANY(%s) AND grantee <> current_user
                        GROUP BY 1, 2 ORDER BY 2, 1""", ([s["name"] for s in stand_ins],))
        grants = cur.fetchall()
        cur.execute("""SELECT p.proname, pg_get_function_identity_arguments(p.oid), pg_get_functiondef(p.oid),
                              md5(replace(p.prosrc, chr(13) || chr(10), chr(10)))
                         FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname = ANY(%s)
                        ORDER BY 1""", (list(REWRITTEN),))
        functions = {n: {"args": a, "def": d, "md5": m} for n, a, d, m in cur.fetchall()}
        missing = set(REWRITTEN) - set(functions)
        if missing:
            raise SystemExit(f"functions not found: {sorted(missing)}")
        cur.execute("""SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relkind IN ('r','v','m','p') AND relname = ANY(%s)
                        AND NOT (relname = ANY(%s))""",
                    ([back(r) for r, _ in relations], [s["name"] for s in stand_ins]))
        taken = [r[0] for r in cur.fetchall()]
        if taken:
            raise SystemExit(f"actor names already taken by something that is not a stand-in: {taken}")
        cur.execute("SELECT migration_id FROM public.architecture_v2_migration_ledger ORDER BY applied_at DESC LIMIT 1")
        last = cur.fetchone()[0]
    return {"relations": relations, "columns": columns, "stand_ins": stand_ins, "grants": grants,
            "functions": functions, "last_ledger": last}


def rewrite(definition: str) -> str:
    """A function definition with the organization names back to actor."""
    hold = {k: f"\x00{i}\x00" for i, k in enumerate(KEEP)}
    for k, token in hold.items():
        definition = definition.replace(k, token)
    definition = definition.replace("organization", "actor")
    for k, token in hold.items():
        definition = definition.replace(token, k)
    return definition


def build(cat: dict) -> dict[str, str]:
    relations = cat["relations"]
    tables = [r for r, k in relations if k in ("r", "p")]
    views = [r for r, k in relations if k in ("v", "m")]
    expected = ", ".join(f"{r}:{k}" for r, k in relations)
    stand_in_names = [s["name"] for s in cat["stand_ins"]]
    fn_expect = " ".join(f"{n}={cat['functions'][n]['md5']}" for n in sorted(cat["functions"]))
    renamed_cols = {rel: [c for c in cols if "organization" in c] for rel, cols in cat["columns"].items()}
    n_cols = sum(len(v) for v in renamed_cols.values())
    renamed_fns = {n: back(n) for n in cat["functions"] if "organization" in n}

    m = [f"""-- {ID}: organization -> actor in the database's own names, back again (GHUS, 25 Nov 2026).
--
-- Generated by migrations/proposed/actor_800/generate.py from a local copy of production
-- taken just before; see that folder's README for the apply sequence.
--
--   * The {len(stand_in_names)} actor_* stand-in views that 720 left are dropped (views only: no data).
--   * {len(tables)} tables and {len(views)} views named organization take the actor names again, with
--     their {n_cols} columns named organization, and the constraint, index, trigger and policy
--     names on them. organization_template (730) becomes actor_template.
--   * The {len(cat['functions'])} functions 720/790 wrote with organization names are rewritten with
--     the actor names (and renamed where their name says organization).
--   * Everything built since 720 stays: the one organization table of 790 (now actor), the
--     columns 750/770 removed stay removed, the event fields of 740, the template view of 730.
--   * Not changed: the category label people read ("Company / Corporate Organization"),
--     column comments, and data.
--
-- One transaction: any failure changes nothing. Refuses unless the catalog is exactly the
-- one this was generated from.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
DECLARE found text; fns text; stand text;
BEGIN
    IF to_regclass('compass.migration_snapshot') IS NULL THEN
        RAISE EXCEPTION '{ID} refused: compass.migration_snapshot is missing';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '{ID}') THEN
        RAISE EXCEPTION '{ID} refused: already in the ledger';
    END IF;
    IF (SELECT migration_id FROM public.architecture_v2_migration_ledger ORDER BY applied_at DESC LIMIT 1)
       IS DISTINCT FROM {q(cat['last_ledger'])} THEN
        RAISE EXCEPTION '{ID} refused: a migration was applied after {cat['last_ledger']}; regenerate {ID}';
    END IF;
    SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) INTO found
      FROM pg_class WHERE relnamespace = 'public'::regnamespace
       AND relname LIKE '%organization%' AND relkind IN ('r','v','m','p');
    IF found IS DISTINCT FROM {q(expected)} THEN
        RAISE EXCEPTION '{ID} refused: the relations named organization differ from the reviewed ones: %', found;
    END IF;
    SELECT string_agg(relname, ',' ORDER BY relname) INTO stand
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'
       AND relname = ANY ({arr(back(r) for r, _ in relations)});
    IF stand IS DISTINCT FROM {q(','.join(sorted(stand_in_names)))} THEN
        RAISE EXCEPTION '{ID} refused: the actor stand-ins differ from the reviewed ones: %', stand;
    END IF;
    SELECT string_agg(proname || '=' || md5(replace(prosrc, chr(13) || chr(10), chr(10))), ' ' ORDER BY proname) INTO fns
      FROM pg_proc WHERE pronamespace = 'public'::regnamespace
       AND proname = ANY ({arr(sorted(cat['functions']))});
    IF fns IS DISTINCT FROM {q(fn_expect)} THEN
        RAISE EXCEPTION '{ID} refused: functions differ from the reviewed ones: %', fns;
    END IF;
END $guard$;

-- Saved for the rollback: the functions as they are, and the stand-ins.
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '{ID}', 'function:' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       pg_get_functiondef(p.oid)
  FROM pg_proc p
 WHERE p.pronamespace = 'public'::regnamespace AND p.proname = ANY ({arr(sorted(cat['functions']))});
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '{ID}', 'standin:' || c.relname, pg_get_viewdef(c.oid)
  FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v'
   AND c.relname = ANY ({arr(stand_in_names)});

CREATE TEMP TABLE _renames (kind text, rel text, old text, new text) ON COMMIT DROP;
"""]
    m.append("-- 1. The stand-ins go: their names are needed for the real relations.")
    for name in sorted(stand_in_names, reverse=True):
        m.append(f"DROP VIEW public.{name};")
    m.append("\n-- 2. Tables and views.")
    for rel in tables:
        m.append(f"ALTER TABLE public.{rel} RENAME TO {back(rel)};")
    for rel in views:
        m.append(f"ALTER VIEW public.{rel} RENAME TO {back(rel)};")
    m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(
        f"('relation', NULL, {q(r)}, {q(back(r))})" for r, _ in relations) + ";")
    m.append("\n-- 3. Their columns named organization (a view's own column names too).")
    pairs = []
    for rel, cols in renamed_cols.items():
        for col in cols:
            m.append(f"ALTER TABLE public.{back(rel)} RENAME COLUMN {col} TO {back(col)};")
            pairs.append(f"('column', {q(back(rel))}, {q(col)}, {q(back(col))})")
    if pairs:
        m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(pairs) + ";")
    new_tables = [back(r) for r in tables]
    m.append(f"""
-- 4. Constraint, index, trigger and policy names on them that say organization.
DO $names$
DECLARE r record; target text;
BEGIN
    FOR r IN SELECT c.conname AS old, cl.relname AS rel
               FROM pg_constraint c JOIN pg_class cl ON cl.oid = c.conrelid
              WHERE c.connamespace = 'public'::regnamespace AND c.conname LIKE '%organization%'
                AND cl.relname = ANY ({arr(new_tables)}) LOOP
        target := replace(r.old, 'organization', 'actor');
        EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', r.rel, r.old, target);
        INSERT INTO _renames VALUES ('constraint', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT i.relname AS old, t.relname AS rel
               FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid
              WHERE t.relnamespace = 'public'::regnamespace AND i.relname LIKE '%organization%'
                AND t.relname = ANY ({arr(new_tables)}) LOOP
        target := replace(r.old, 'organization', 'actor');
        EXECUTE format('ALTER INDEX public.%I RENAME TO %I', r.old, target);
        INSERT INTO _renames VALUES ('index', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT tg.tgname AS old, c.relname AS rel
               FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
              WHERE NOT tg.tgisinternal AND c.relnamespace = 'public'::regnamespace
                AND tg.tgname LIKE '%organization%' AND c.relname = ANY ({arr(new_tables)}) LOOP
        target := replace(r.old, 'organization', 'actor');
        EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', r.old, r.rel, target);
        INSERT INTO _renames VALUES ('trigger', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT p.policyname AS old, p.tablename AS rel FROM pg_policies p
              WHERE p.schemaname = 'public' AND p.policyname LIKE '%organization%'
                AND p.tablename = ANY ({arr(new_tables)}) LOOP
        target := replace(r.old, 'organization', 'actor');
        EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', r.old, r.rel, target);
        INSERT INTO _renames VALUES ('policy', r.rel, r.old, target);
    END LOOP;
END $names$;
""")
    m.append("-- 5. Functions: the ones named organization are dropped and created again under the actor")
    m.append("--    name (a parameter name cannot change in place); the others get their new body.")
    m.append("--    Triggers call them by name inside their bodies, so the order does not matter here.")
    trigger_fns = []
    for name, f in sorted(cat["functions"].items()):
        if name in renamed_fns:
            trigger_fns.append(name)
    # Triggers reference trigger functions by OID: re-point them after re-creating.
    m.append(f"""CREATE TEMP TABLE _fn_triggers ON COMMIT DROP AS
SELECT tg.tgname, c.relname, p.proname,
       pg_get_triggerdef(tg.oid) AS def
  FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_proc p ON p.oid = tg.tgfoid
 WHERE NOT tg.tgisinternal AND p.pronamespace = 'public'::regnamespace AND p.proname = ANY ({arr(sorted(renamed_fns))});
DO $drop_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        EXECUTE format('DROP TRIGGER %I ON public.%I', t.tgname, t.relname);
    END LOOP;
END $drop_triggers$;""")
    for name in sorted(renamed_fns):
        m.append(f"DROP FUNCTION public.{name}({cat['functions'][name]['args']});")
    for name, f in sorted(cat["functions"].items()):
        body = rewrite(f["def"]).rstrip()
        m.append(body + ";" if not body.endswith(";") else body)
    m.append(f"""DO $make_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        EXECUTE replace(t.def, 'organization', 'actor');
    END LOOP;
END $make_triggers$;""")
    m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(
        f"('function', NULL, {q(o)}, {q(n)})" for o, n in sorted(renamed_fns.items())) + ";")
    m.append(f"""
-- 6. Keep the renames for the rollback; tell the API to read the new names.
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '{ID}', 'rename:' || kind || ':' || COALESCE(rel, '') || ':' || old, new FROM _renames;
NOTIFY pgrst, 'reload schema';

COMMIT;
""")
    migration = "\n".join(m)

    # ---------------------------------------------------------------- rollback
    r = [f"""-- Rollback {ID}: the organization names and the actor stand-ins come back exactly as they were.
-- Run in the SQL editor, then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '{ID}';
-- The data is untouched; only names, functions and the stand-in views change.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM compass.migration_snapshot WHERE migration_id = '{ID}') THEN
        RAISE EXCEPTION 'rollback {ID} refused: no snapshot of {ID} (it was not applied here)';
    END IF;
END $guard$;

-- Functions: the actor-named ones (and their triggers) go; the saved definitions return.
CREATE TEMP TABLE _fn_triggers ON COMMIT DROP AS
SELECT tg.tgname, c.relname, pg_get_triggerdef(tg.oid) AS def
  FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_proc p ON p.oid = tg.tgfoid
 WHERE NOT tg.tgisinternal AND p.pronamespace = 'public'::regnamespace AND p.proname = ANY ({arr(sorted(renamed_fns.values()))});
DO $drop_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        EXECUTE format('DROP TRIGGER %I ON public.%I', t.tgname, t.relname);
    END LOOP;
END $drop_triggers$;"""]
    for old, new in sorted(renamed_fns.items()):
        r.append(f"DROP FUNCTION public.{new}({cat['functions'][old]['args']});")
    r.append(f"""
-- Names back first (the saved function bodies use them).
DO $names$
DECLARE x record; parts text[];
BEGIN
    FOR x IN SELECT object_name, definition FROM compass.migration_snapshot
              WHERE migration_id = '{ID}'
                AND split_part(object_name, ':', 2) IN ('constraint', 'index', 'trigger', 'policy') LOOP
        parts := string_to_array(x.object_name, ':');
        CASE parts[2]
            WHEN 'constraint' THEN EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', parts[3], x.definition, parts[4]);
            WHEN 'index' THEN EXECUTE format('ALTER INDEX public.%I RENAME TO %I', x.definition, parts[4]);
            WHEN 'trigger' THEN
                -- Triggers on the re-created functions were dropped above; they return below.
                IF EXISTS (SELECT 1 FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
                            WHERE c.relnamespace = 'public'::regnamespace AND c.relname = parts[3]
                              AND tg.tgname = x.definition) THEN
                    EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
                END IF;
            WHEN 'policy' THEN EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
        END CASE;
    END LOOP;
END $names$;
""")
    for rel, cols in renamed_cols.items():
        for col in cols:
            r.append(f"ALTER TABLE public.{back(rel)} RENAME COLUMN {back(col)} TO {col};")
    for rel in views:
        r.append(f"ALTER VIEW public.{back(rel)} RENAME TO {rel};")
    for rel in tables:
        r.append(f"ALTER TABLE public.{back(rel)} RENAME TO {rel};")
    r.append(f"""
DO $restore$
DECLARE d record;
BEGIN
    FOR d IN SELECT definition FROM compass.migration_snapshot
              WHERE migration_id = '{ID}' AND object_name LIKE 'function:%' LOOP
        EXECUTE d.definition;
    END LOOP;
END $restore$;
DO $make_triggers$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM _fn_triggers LOOP
        -- Trigger, table and function names all said organization before {ID}.
        EXECUTE replace(t.def, 'actor', 'organization');
    END LOOP;
END $make_triggers$;

-- The stand-ins, as they were.""")
    for s in cat["stand_ins"]:
        opts = f" WITH ({s['options']})" if s["options"] else ""
        r.append(f"CREATE VIEW public.{s['name']}{opts} AS\n{s['definition'].rstrip().rstrip(';')};")
        if s["comment"]:
            r.append(f"COMMENT ON VIEW public.{s['name']} IS {q(s['comment'])};")
        # As 720 made them: no access for Supabase's public roles, full use for service_role.
        r.append(f"REVOKE ALL ON public.{s['name']} FROM anon, authenticated;")
        r.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{s['name']} TO service_role;")
    r.append(f"""
DELETE FROM compass.migration_snapshot WHERE migration_id = '{ID}';
NOTIFY pgrst, 'reload schema';

COMMIT;
""")
    rollback = "\n".join(r)

    sha = hashlib.sha256(migration.encode("utf-8")).hexdigest()
    preflight = f"""-- Read-only preflight for migration {ID} (organization -> actor names). Run BEFORE applying;
-- every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'compass.migration_snapshot exists' AS check_name,
           to_regclass('compass.migration_snapshot') IS NOT NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no {ID} row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '{ID}'), NULL
    UNION ALL
    SELECT 3, 'the latest migration is still {cat['last_ledger']}',
           l.m = {q(cat['last_ledger'])}, l.m
      FROM (SELECT migration_id AS m FROM public.architecture_v2_migration_ledger ORDER BY applied_at DESC LIMIT 1) l
    UNION ALL
    SELECT 4, 'the relations named organization are the reviewed {len(relations)}', f.found = {q(expected)}, f.found
      FROM (SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) AS found
              FROM pg_class WHERE relnamespace = 'public'::regnamespace
               AND relname LIKE '%organization%' AND relkind IN ('r','v','m','p')) f
    UNION ALL
    SELECT 5, 'the actor stand-ins are the reviewed {len(stand_in_names)}', s.found = {q(','.join(sorted(stand_in_names)))}, s.found
      FROM (SELECT string_agg(relname, ',' ORDER BY relname) AS found FROM pg_class
             WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'
               AND relname = ANY ({arr(back(r) for r, _ in relations)})) s
    UNION ALL
    SELECT 6, 'the functions {ID} rewrites are as reviewed', g.found = {q(fn_expect)}, g.found
      FROM (SELECT string_agg(proname || '=' || md5(replace(prosrc, chr(13) || chr(10), chr(10))), ' ' ORDER BY proname) AS found
              FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname = ANY ({arr(sorted(cat['functions']))})) g
) checks ORDER BY n;

ROLLBACK;
"""
    verify = f"""-- Read-only checks after migration {ID}; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'no relation named organization is left' AS check_name,
           NOT EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relname LIKE '%organization%' AND relkind IN ('r','v','m','p')) AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'the {len(new_tables)} actor tables are real tables again',
           count(*) = {len(new_tables)}, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','p')
       AND relname = ANY ({arr(new_tables)})
    UNION ALL
    SELECT 3, 'the {len(views)} views carry the actor names',
           count(*) = {len(views)}, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('v','m')
       AND relname = ANY ({arr(back(v) for v in views)})
    UNION ALL
    SELECT 4, 'no column named organization on them',
           NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                        AND column_name LIKE '%organization%'
                        AND table_name = ANY ({arr(back(r) for r, _ in relations)})), NULL
    UNION ALL
    SELECT 5, 'no function named organization is left',
           NOT EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = 'public'::regnamespace
                        AND proname LIKE '%organization%'), NULL
    UNION ALL
    SELECT 6, 'every trigger on the actor tables points at an existing function',
           NOT EXISTS (SELECT 1 FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
                        WHERE NOT tg.tgisinternal AND c.relname = ANY ({arr(new_tables)})
                          AND NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = tg.tgfoid)), NULL
    UNION ALL
    SELECT 7, 'the details triggers are back on the fact tables',
           count(*) = 2, count(*)::text
      FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('actor_details_follows_pointer',
                                                            'actor_details_follows_topicless_fact')
    UNION ALL
    SELECT 8, 'actor rows (the platform''s count)', true, (SELECT count(*)::text FROM public.actor)
    UNION ALL
    SELECT 9, 'actor_template rows', true, (SELECT count(*)::text FROM public.actor_template)
    UNION ALL
    SELECT 10, 'ledger row {ID} with the reviewed checksum',
           EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '{ID}' AND source_sha256 = '{sha}'), NULL
) checks ORDER BY n;

ROLLBACK;
"""
    ledger = f"""-- Ledger row for {ID}. Run right after the migration succeeds. The checksum is the
-- SHA-256 of the committed migration file (LF line endings).

BEGIN;

INSERT INTO public.architecture_v2_migration_ledger (migration_id, source_path, source_sha256)
VALUES ('{ID}', 'migrations/proposed/deferred/{NAME}', '{sha}')
ON CONFLICT (migration_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger
                    WHERE migration_id = '{ID}' AND source_sha256 = '{sha}') THEN
        RAISE EXCEPTION 'ledger: the {ID} row with this checksum is missing';
    END IF;
END $$;

COMMIT;
"""
    return {"migration": migration, "rollback": rollback, "preflight": preflight, "verify": verify,
            "ledger": ledger, "sha": sha}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="a LOCAL *_test copy of production")
    args = parser.parse_args()
    if not args.database.endswith("_test"):
        raise SystemExit("read the catalog from a local *_test copy, never Supabase")
    cat = read_catalog(args.database)
    out = build(cat)
    write = lambda path, text: path.write_bytes(text.encode("utf-8"))  # noqa: E731 (LF endings)
    (DEFERRED / "rollback").mkdir(parents=True, exist_ok=True)
    write(DEFERRED / NAME, out["migration"])
    write(DEFERRED / "rollback" / NAME, out["rollback"])
    for key in ("preflight", "verify", "ledger"):
        write(HERE / f"{key}.sql", out[key])
    # The whole catalog, so the package test can rebuild every file from it.
    write(HERE / "catalog.json", json.dumps({**cat, "sha256": out["sha"]}, indent=2) + "\n")
    print(f"{NAME}: {len(cat['relations'])} relations, {len(cat['stand_ins'])} stand-ins, "
          f"{len(cat['functions'])} functions; sha256 {out['sha']}")
    leftovers = sorted(set(re.findall(r"\w*organization\w*", out["migration"].split("-- 5.")[1].split("-- 6.")[0])))
    print("words still saying organization in the rewritten functions:", leftovers or "none")


if __name__ == "__main__":
    main()
