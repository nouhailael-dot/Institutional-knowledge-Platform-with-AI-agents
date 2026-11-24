"""Build migration 720 (actor -> organization names) and its package from a catalog.

    python migrations/proposed/organization_720/generate.py --database ghus_phase7_prodcopy_test

Reads, from a LOCAL copy of production (never Supabase): the 27 relations named
actor, their columns in order, and the source of the functions 720 rewrites.
Writes:
    ../deferred/720_organization_names.sql
    ../deferred/rollback/720_organization_names.sql
    preflight.sql, verify.sql, ledger.sql (this folder)

GHUS decision of 24 Nov 2026: "actor" becomes "organization" in the database too.
Stage 1 (this migration): the relations named actor and their own columns are
renamed; a stand-in view keeps each old name (with its old column names)
working, so the platform and the agents run unchanged until they move to the
new names. Internal type codes ('actor' in entity_type, verify_actor...) and the
columns of tables that keep their names are stage 2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DEFERRED = HERE.parent / "deferred"
ID = "720"
NAME = "720_organization_names.sql"


def new_name(old: str) -> str:
    return old.replace("actor", "organization")


# ---------------------------------------------------------------------------- functions
# The functions that name actor relations or columns, rewritten by hand with the new
# names. Type codes ('actor' in subject_type), the session key ghus.actor_is_human and
# the JSON key actor_fact_id in fact_sources keep their values (the code reads them).
RENAMED_FUNCTIONS = {
    "ghus_actor_details_on_pointer": "ghus_organization_details_on_pointer",
    "ghus_actor_details_on_topicless_fact": "ghus_organization_details_on_topicless_fact",
    "ghus_guard_actor_status": "ghus_guard_organization_status",
    "ghus_prevent_actor_family_cycle": "ghus_prevent_organization_family_cycle",
    "ghus_project_actor_verification_status": "ghus_project_organization_verification_status",
}
# Same name, new body.
REBODIED_FUNCTIONS = ("ghus_guard_ranking_is_university", "ghus_guard_subscription_run_append_only",
                      "ghus_validate_entity_edge")
# Dropped and created again: its parameter p_actor is renamed (a parameter name cannot
# change in place). Only the two functions above call it, by name.
RECREATED = ("ghus_actor_details_refresh", "ghus_organization_details_refresh")

NEW_BODIES = {
    "ghus_organization_details_on_pointer": """
CREATE OR REPLACE FUNCTION public.ghus_organization_details_on_pointer()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    PERFORM ghus_organization_details_refresh(NEW.organization_id, NEW.fact_key);
    RETURN NULL;
END $function$;""",
    "ghus_organization_details_on_topicless_fact": """
CREATE OR REPLACE FUNCTION public.ghus_organization_details_on_topicless_fact()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    PERFORM ghus_organization_details_refresh(NEW.organization_id, NEW.fact_key);
    RETURN NULL;
END $function$;""",
    "ghus_organization_details_refresh": """
CREATE FUNCTION public.ghus_organization_details_refresh(p_organization uuid, p_key text)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_value jsonb;
    v_source jsonb;
    v_column boolean;
BEGIN
    SELECT CASE WHEN f.collection_state = 'found' THEN f.fact_value
                ELSE to_jsonb(f.collection_state) END,
           jsonb_strip_nulls(jsonb_build_object(
               'source_url', s.url, 'retrieved_at', f.retrieved_at,
               'confidence', f.confidence, 'topic_id', f.topic_id,
               'actor_fact_id', f.organization_fact_id))
      INTO v_value, v_source
      FROM organization_fact f
      LEFT JOIN source s ON s.source_id = f.source_id
     WHERE f.organization_id = p_organization AND f.fact_key = p_key
       AND (EXISTS (SELECT 1 FROM organization_fact_current_pointer p
                     WHERE p.organization_fact_id = f.organization_fact_id)
            OR (f.topic_id IS NULL AND EXISTS (
                    SELECT 1 FROM organization_fact_current c
                     WHERE c.organization_fact_id = f.organization_fact_id
                       AND c.resolution_state = 'accepted')))
     ORDER BY (f.collection_state = 'found') DESC, f.retrieved_at DESC NULLS LAST,
              f.created_at DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO organization_details (organization_id) VALUES (p_organization)
        ON CONFLICT (organization_id) DO NOTHING;

    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'organization_details'
                      AND column_name = p_key
                      AND column_name NOT IN ('organization_id', 'other_facts', 'fact_sources',
                                              'updated_at'))
      INTO v_column;

    IF v_column THEN
        EXECUTE format(
            'UPDATE organization_details SET %I = $1, fact_sources = fact_sources || $2, '
            'updated_at = now() WHERE organization_id = $3', p_key)
        USING v_value, jsonb_build_object(p_key, v_source), p_organization;
    ELSE
        UPDATE organization_details
           SET other_facts = other_facts || jsonb_build_object(p_key, v_value),
               fact_sources = fact_sources || jsonb_build_object(p_key, v_source),
               updated_at = now()
         WHERE organization_id = p_organization;
    END IF;
END $function$;""",
    "ghus_guard_organization_status": """
CREATE OR REPLACE FUNCTION public.ghus_guard_organization_status()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.status IN ('verified','rejected')
     AND COALESCE(current_setting('ghus.verification_projection',true),'off') <> 'on'
  THEN
    RAISE EXCEPTION 'verified/rejected status requires organization_verification_event';
  END IF;
  RETURN NEW;
END;
$function$;""",
    "ghus_guard_ranking_is_university": """
CREATE OR REPLACE FUNCTION public.ghus_guard_ranking_is_university()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE category text;
BEGIN
    SELECT a.organization_category INTO category FROM organization a
     WHERE a.organization_id = NEW.organization_id;
    IF category IS DISTINCT FROM 'university_academic' THEN
        RAISE EXCEPTION
            'rankings are recorded for university organizations only; organization % is %',
            NEW.organization_id, COALESCE(category, 'unclassified');
    END IF;
    RETURN NEW;
END $function$;""",
    "ghus_guard_subscription_run_append_only": """
CREATE OR REPLACE FUNCTION public.ghus_guard_subscription_run_append_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' AND compass.purge_door_open() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'organization_update_subscription_run is append-only: % is not permitted', TG_OP;
END $function$;""",
    "ghus_prevent_organization_family_cycle": """
CREATE OR REPLACE FUNCTION public.ghus_prevent_organization_family_cycle()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE cycle_found boolean;
BEGIN
    IF NEW.relationship_type NOT IN ('unit_of','operated_by') THEN
        RETURN NEW;
    END IF;
    WITH RECURSIVE ancestors(organization_id,path) AS (
        SELECT NEW.object_id,ARRAY[NEW.object_id]
        UNION ALL
        SELECT edge.object_id,ancestors.path || edge.object_id
        FROM ancestors
        JOIN entity_edge edge
          ON edge.subject_type='actor' AND edge.object_type='actor'
         AND edge.subject_id=ancestors.organization_id
         AND edge.relationship_type IN ('unit_of','operated_by')
        WHERE NOT edge.object_id=ANY(ancestors.path)
    )
    SELECT EXISTS(SELECT 1 FROM ancestors WHERE organization_id=NEW.subject_id)
    INTO cycle_found;
    IF cycle_found THEN
        RAISE EXCEPTION 'organization family cycle refused for % -> %',NEW.subject_id,NEW.object_id;
    END IF;
    RETURN NEW;
END $function$;""",
    "ghus_project_organization_verification_status": """
CREATE OR REPLACE FUNCTION public.ghus_project_organization_verification_status()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    PERFORM set_config('ghus.verification_projection','on',true);
    UPDATE organization SET status=NEW.decision,updated_at=now() WHERE organization_id=NEW.organization_id;
    PERFORM set_config('ghus.verification_projection','off',true);
    RETURN NEW;
END;
$function$;""",
    "ghus_validate_entity_edge": """
CREATE OR REPLACE FUNCTION public.ghus_validate_entity_edge()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    allowed_subjects text[];
    allowed_objects text[];
    endpoint_exists boolean;
BEGIN
    SELECT subject_types,object_types INTO allowed_subjects,allowed_objects
    FROM entity_edge_type_definition
    WHERE relationship_type=NEW.relationship_type;
    IF allowed_subjects IS NULL
       OR NOT NEW.subject_type=ANY(allowed_subjects)
       OR NOT NEW.object_type=ANY(allowed_objects) THEN
        RAISE EXCEPTION 'invalid endpoint pair % -> % for %',
            NEW.subject_type,NEW.object_type,NEW.relationship_type;
    END IF;

    IF NEW.subject_type='actor' THEN
        SELECT EXISTS(SELECT 1 FROM organization WHERE organization_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type='person' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.subject_id) INTO endpoint_exists;
    ELSIF NEW.subject_type='event' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.subject_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.subject_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION 'missing % subject endpoint %',NEW.subject_type,NEW.subject_id;
    END IF;

    IF NEW.object_type='actor' THEN
        SELECT EXISTS(SELECT 1 FROM organization WHERE organization_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type='person' THEN
        SELECT EXISTS(SELECT 1 FROM person WHERE person_id=NEW.object_id) INTO endpoint_exists;
    ELSIF NEW.object_type='event' THEN
        SELECT EXISTS(SELECT 1 FROM event WHERE event_id=NEW.object_id) INTO endpoint_exists;
    ELSE
        SELECT EXISTS(SELECT 1 FROM strategic_entity WHERE strategic_entity_id=NEW.object_id) INTO endpoint_exists;
    END IF;
    IF NOT endpoint_exists THEN
        RAISE EXCEPTION 'missing % object endpoint %',NEW.object_type,NEW.object_id;
    END IF;
    RETURN NEW;
END $function$;""",
}

ORIGINAL_FUNCTIONS = (*RENAMED_FUNCTIONS, *REBODIED_FUNCTIONS, RECREATED[0])
LABEL_OLD, LABEL_NEW = "Corporate Actor", "Corporate Organization"


def read_catalog(database: str) -> dict:
    url = f"postgresql://ghus_test@127.0.0.1:55432/{database}"
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname='public' AND c.relname LIKE '%actor%' AND c.relkind IN ('r','v')
                       ORDER BY c.relkind, c.relname""")
        relations = cur.fetchall()
        columns = {}
        for rel, _ in relations:
            cur.execute("""SELECT a.attname FROM pg_attribute a WHERE a.attrelid = %s::regclass
                           AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""", (f"public.{rel}",))
            columns[rel] = [r[0] for r in cur.fetchall()]
        cur.execute("""SELECT p.proname, md5(p.prosrc), pg_get_function_identity_arguments(p.oid)
                       FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.proname = ANY(%s)
                       ORDER BY 1""", (list(ORIGINAL_FUNCTIONS),))
        functions = {name: {"md5": digest, "args": args} for name, digest, args in cur.fetchall()}
    missing = set(ORIGINAL_FUNCTIONS) - set(functions)
    if missing:
        raise SystemExit(f"functions not found: {sorted(missing)}")
    return {"relations": relations, "columns": columns, "functions": functions}


def q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def build(cat: dict) -> dict[str, str]:
    relations = cat["relations"]
    tables = [r for r, k in relations if k == "r"]
    views = [r for r, k in relations if k == "v"]
    expected = ", ".join(f"{r}:{k}" for r, k in relations)
    fn_expect = " ".join(f"{n}={cat['functions'][n]['md5']}" for n in sorted(cat["functions"]))
    renamed_cols = {rel: [c for c in cols if "actor" in c] for rel, cols in cat["columns"].items()}
    n_cols = sum(len(v) for v in renamed_cols.values())

    m = []
    m.append(f"""-- {ID}: actor -> organization in the database's own names (GHUS decision, 24 Nov 2026).
--
-- Stage 1 of 2. Generated by migrations/proposed/organization_720/generate.py from a
-- local copy of production; see that folder's README for the apply sequence.
--
--   * {len(tables)} tables and {len(views)} views named actor are renamed (actor -> organization,
--     hub_actor -> hub_organization ...), with their {n_cols} columns named actor
--     (actor_id -> organization_id ...), and the constraint, index, trigger and
--     policy names on them.
--   * Each old name stays as a stand-in VIEW with the old column names, so every
--     query, insert, update and delete the platform and the agents send today runs
--     unchanged (writes pass through to the renamed table; its triggers still run).
--     The stand-ins run with the caller's rights (security_invoker) and Supabase's
--     public roles anon and authenticated have no access to them.
--   * The functions that name these relations are rewritten with the new names and
--     renamed where their name says actor; the originals are saved in
--     compass.migration_snapshot for the rollback, with every rename made.
--   * The category label 'Company / {LABEL_OLD}' reads 'Company / {LABEL_NEW}'.
--
-- Not in stage 1 (stage 2, with the code): internal type codes ('actor' in
-- entity_type, verify_actor, create_actor), the session key ghus.actor_is_human, and
-- the columns named actor in tables that keep their names (event.host_actor_id ...).
--
-- One transaction: any failure changes nothing. Refuses unless the catalog is exactly
-- the one this was generated from.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
DECLARE found text; fns text;
BEGIN
    IF to_regclass('compass.migration_snapshot') IS NULL THEN
        RAISE EXCEPTION '{ID} refused: migration 710 (compass.migration_snapshot) is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '{ID}') THEN
        RAISE EXCEPTION '{ID} refused: already in the ledger';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                AND relname LIKE '%organization%' AND relkind IN ('r','v','m')) THEN
        RAISE EXCEPTION '{ID} refused: a relation named organization already exists';
    END IF;
    SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) INTO found
      FROM pg_class WHERE relnamespace = 'public'::regnamespace
       AND relname LIKE '%actor%' AND relkind IN ('r','v','m');
    IF found IS DISTINCT FROM {q(expected)} THEN
        RAISE EXCEPTION '{ID} refused: the relations named actor differ from the reviewed ones: %', found;
    END IF;
    SELECT string_agg(proname || '=' || md5(prosrc), ' ' ORDER BY proname) INTO fns
      FROM pg_proc WHERE pronamespace = 'public'::regnamespace
       AND proname IN ({", ".join(q(n) for n in sorted(cat["functions"]))});
    IF fns IS DISTINCT FROM {q(fn_expect)} THEN
        RAISE EXCEPTION '{ID} refused: functions differ from the reviewed ones: %', fns;
    END IF;
END $guard$;

-- The functions as they are, for the rollback (restored byte for byte).
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '{ID}', 'public.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       pg_get_functiondef(p.oid)
  FROM pg_proc p
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proname IN ({", ".join(q(n) for n in sorted(cat["functions"]))});

-- Every rename, recorded so the rollback reverses exactly these and nothing else.
CREATE TEMP TABLE _renames (kind text, rel text, old text, new text) ON COMMIT DROP;
""")
    m.append("-- 1. Tables and views.")
    for rel in tables:
        m.append(f"ALTER TABLE public.{rel} RENAME TO {new_name(rel)};")
    for rel in views:
        m.append(f"ALTER VIEW public.{rel} RENAME TO {new_name(rel)};")
    m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(
        f"('relation', NULL, {q(r)}, {q(new_name(r))})" for r, _ in relations) + ";")
    m.append("\n-- 2. Their columns named actor (a view's own column names too).")
    pairs = []
    for rel, cols in renamed_cols.items():
        for col in cols:
            m.append(f"ALTER TABLE public.{new_name(rel)} RENAME COLUMN {col} TO {new_name(col)};")
            pairs.append(f"('column', {q(new_name(rel))}, {q(col)}, {q(new_name(col))})")
    m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(pairs) + ";")
    new_tables = [new_name(r) for r in tables]
    m.append(f"""
-- 3. Constraint, index, trigger and policy names on them that say actor (a name that
--    would pass PostgreSQL's 63 characters is kept as it is).
DO $names$
DECLARE r record; target text;
BEGIN
    FOR r IN SELECT c.conname AS old, c.conrelid::regclass::text AS rel
               FROM pg_constraint c
              WHERE c.connamespace = 'public'::regnamespace AND c.conname LIKE '%actor%'
                AND c.conrelid::regclass::text = ANY ({q('{' + ','.join(new_tables) + '}')}::text[]) LOOP
        target := replace(r.old, 'actor', 'organization');
        CONTINUE WHEN length(target) > 63;
        EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', r.rel, r.old, target);
        INSERT INTO _renames VALUES ('constraint', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT i.relname AS old, t.relname AS rel
               FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid
              WHERE t.relnamespace = 'public'::regnamespace AND i.relname LIKE '%actor%'
                AND t.relname = ANY ({q('{' + ','.join(new_tables) + '}')}::text[]) LOOP
        target := replace(r.old, 'actor', 'organization');
        CONTINUE WHEN length(target) > 63;
        EXECUTE format('ALTER INDEX public.%I RENAME TO %I', r.old, target);
        INSERT INTO _renames VALUES ('index', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT tg.tgname AS old, c.relname AS rel
               FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid
              WHERE NOT tg.tgisinternal AND c.relnamespace = 'public'::regnamespace
                AND tg.tgname LIKE '%actor%'
                AND c.relname = ANY ({q('{' + ','.join(new_tables) + '}')}::text[]) LOOP
        target := replace(r.old, 'actor', 'organization');
        CONTINUE WHEN length(target) > 63;
        EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', r.old, r.rel, target);
        INSERT INTO _renames VALUES ('trigger', r.rel, r.old, target);
    END LOOP;
    FOR r IN SELECT p.policyname AS old, p.tablename AS rel FROM pg_policies p
              WHERE p.schemaname = 'public' AND p.policyname LIKE '%actor%'
                AND p.tablename = ANY ({q('{' + ','.join(new_tables) + '}')}::text[]) LOOP
        target := replace(r.old, 'actor', 'organization');
        CONTINUE WHEN length(target) > 63;
        EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', r.old, r.rel, target);
        INSERT INTO _renames VALUES ('policy', r.rel, r.old, target);
    END LOOP;
END $names$;
""")
    m.append("-- 4. Functions: renamed where they say actor, then the new bodies.")
    for old, new in RENAMED_FUNCTIONS.items():
        args = cat["functions"][old]["args"]
        m.append(f"ALTER FUNCTION public.{old}({args}) RENAME TO {new};")
    m.append("INSERT INTO _renames VALUES\n    " + ",\n    ".join(
        [f"('function', NULL, {q(o)}, {q(n)})" for o, n in RENAMED_FUNCTIONS.items()]
        + [f"('function_recreated', NULL, {q(RECREATED[0])}, {q(RECREATED[1])})"]) + ";")
    m.append(f"DROP FUNCTION public.{RECREATED[0]}({cat['functions'][RECREATED[0]]['args']});")
    m.append(NEW_BODIES[RECREATED[1]])
    for name in (*RENAMED_FUNCTIONS.values(), *REBODIED_FUNCTIONS):
        m.append(NEW_BODIES[name])
    m.append("\n-- 5. The stand-ins: each old name, with its old column names, over the renamed relation.")
    for rel, _ in relations:
        cols = cat["columns"][rel]
        select = ",\n       ".join(new_name(c) + (f" AS {c}" if "actor" in c else "") for c in cols)
        m.append(f"CREATE VIEW public.{rel} WITH (security_invoker = true) AS\nSELECT {select}\n  FROM public.{new_name(rel)};")
        m.append(f"COMMENT ON VIEW public.{rel} IS "
                 f"{q(f'Stand-in for {new_name(rel)} until the code uses the new name (migration {ID}).')};")
        m.append(f"REVOKE ALL ON public.{rel} FROM anon, authenticated;")
        m.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{rel} TO service_role;")
    m.append(f"""
-- 6. The category label people read.
UPDATE public.organization_category_definition
   SET display_name = replace(display_name, {q(LABEL_OLD)}, {q(LABEL_NEW)})
 WHERE display_name LIKE {q('%' + LABEL_OLD + '%')};

-- 7. Keep the renames for the rollback.
INSERT INTO compass.migration_snapshot (migration_id, object_name, definition)
SELECT '{ID}', 'rename:' || kind || ':' || COALESCE(rel, '') || ':' || old, new FROM _renames;

COMMIT;
""")
    migration = "\n".join(m)

    # ---------------------------------------------------------------- rollback
    r = []
    r.append(f"""-- Rollback {ID}: the actor names come back exactly as they were.
-- Run in the SQL editor, then: DELETE FROM architecture_v2_migration_ledger WHERE migration_id = '{ID}';
-- The data is untouched; only names, the stand-in views, the rewritten functions and
-- the category label change back.

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM compass.migration_snapshot WHERE migration_id = '{ID}') THEN
        RAISE EXCEPTION 'rollback {ID} refused: no snapshot of {ID} (it was not applied here)';
    END IF;
END $guard$;

-- The stand-in views go first: the old names are needed again.""")
    for rel, _ in reversed(relations):
        r.append(f"DROP VIEW public.{rel};")
    r.append(f"""
UPDATE public.organization_category_definition
   SET display_name = replace(display_name, {q(LABEL_NEW)}, {q(LABEL_OLD)})
 WHERE display_name LIKE {q('%' + LABEL_NEW + '%')};

-- Functions: names back, then the saved definitions (byte for byte).
DROP FUNCTION public.{RECREATED[1]}(uuid, text);""")
    for old, new in RENAMED_FUNCTIONS.items():
        args = cat["functions"][old]["args"]
        r.append(f"ALTER FUNCTION public.{new}({args}) RENAME TO {old};")
    r.append(f"""DO $restore$
DECLARE d record;
BEGIN
    FOR d IN SELECT definition FROM compass.migration_snapshot
              WHERE migration_id = '{ID}' AND object_name NOT LIKE 'rename:%' LOOP
        EXECUTE d.definition;
    END LOOP;
END $restore$;

-- Constraint, index, trigger and policy names, exactly as recorded.
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
            WHEN 'trigger' THEN EXECUTE format('ALTER TRIGGER %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
            WHEN 'policy' THEN EXECUTE format('ALTER POLICY %I ON public.%I RENAME TO %I', x.definition, parts[3], parts[4]);
        END CASE;
    END LOOP;
END $names$;
""")
    r.append("-- Columns, then tables and views.")
    for rel, cols in renamed_cols.items():
        for col in cols:
            r.append(f"ALTER TABLE public.{new_name(rel)} RENAME COLUMN {new_name(col)} TO {col};")
    for rel in views:
        r.append(f"ALTER VIEW public.{new_name(rel)} RENAME TO {rel};")
    for rel in tables:
        r.append(f"ALTER TABLE public.{new_name(rel)} RENAME TO {rel};")
    r.append(f"""
DELETE FROM compass.migration_snapshot WHERE migration_id = '{ID}';

COMMIT;
""")
    rollback = "\n".join(r)

    sha = hashlib.sha256(migration.encode("utf-8")).hexdigest()
    preflight = f"""-- Read-only preflight for migration {ID} (actor -> organization names). Run in the
-- Supabase SQL editor BEFORE applying it; every row must say ok = true. Changes nothing.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'migration 710 applied (compass.migration_snapshot exists)' AS check_name,
           to_regclass('compass.migration_snapshot') IS NOT NULL AS ok, NULL::text AS detail
    UNION ALL
    SELECT 2, 'ledger has no {ID} row',
           NOT EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '{ID}'), NULL
    UNION ALL
    SELECT 3, 'no relation named organization yet',
           NOT EXISTS (SELECT 1 FROM pg_class WHERE relnamespace = 'public'::regnamespace
                        AND relname LIKE '%organization%' AND relkind IN ('r','v','m')), NULL
    UNION ALL
    SELECT 4, 'the relations named actor are the reviewed {len(relations)}', f.found = {q(expected)}, f.found
      FROM (SELECT string_agg(relname || ':' || relkind::text, ', ' ORDER BY relkind, relname) AS found
              FROM pg_class WHERE relnamespace = 'public'::regnamespace
               AND relname LIKE '%actor%' AND relkind IN ('r','v','m')) f
    UNION ALL
    SELECT 5, 'the functions {ID} rewrites are as reviewed', g.found = {q(fn_expect)}, g.found
      FROM (SELECT string_agg(proname || '=' || md5(prosrc), ' ' ORDER BY proname) AS found
              FROM pg_proc WHERE pronamespace = 'public'::regnamespace
               AND proname IN ({", ".join(q(n) for n in sorted(cat["functions"]))})) g
    UNION ALL
    SELECT 6, 'latest ledger entries (informational)', true,
           (SELECT string_agg(migration_id, ', ' ORDER BY applied_at DESC)
              FROM (SELECT migration_id, applied_at FROM public.architecture_v2_migration_ledger
                     ORDER BY applied_at DESC LIMIT 5) l)
) checks ORDER BY n;

ROLLBACK;
"""
    verify = f"""-- Read-only checks after migration {ID}; every row must say ok = true.

BEGIN READ ONLY;

SELECT check_name, ok, detail FROM (
    SELECT 1 AS n, 'the {len(relations)} renamed relations exist' AS check_name,
           count(*) = {len(relations)} AS ok, count(*)::text AS detail
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','v')
       AND relname = ANY ({q('{' + ','.join(new_name(r) for r, _ in relations) + '}')}::text[])
    UNION ALL
    SELECT 2, 'every old name is now a stand-in view',
           count(*) = {len(relations)}, count(*)::text
      FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'v'
       AND relname = ANY ({q('{' + ','.join(r for r, _ in relations) + '}')}::text[])
    UNION ALL
    SELECT 3, 'the stand-ins run with the caller''s rights',
           bool_and(coalesce(c.reloptions::text, '') LIKE '%security_invoker=true%'), NULL
      FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'v'
       AND c.relname = ANY ({q('{' + ','.join(r for r, _ in relations) + '}')}::text[])
    UNION ALL
    SELECT 4, 'anon and authenticated have no access to the stand-ins',
           NOT EXISTS (SELECT 1 FROM information_schema.role_table_grants
                        WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
                          AND table_name = ANY ({q('{' + ','.join(r for r, _ in relations) + '}')}::text[])), NULL
    UNION ALL
    SELECT 5, 'organization.organization_id exists',
           EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                    AND table_name = 'organization' AND column_name = 'organization_id'), NULL
    UNION ALL
    SELECT 6, 'no column named actor left on a renamed relation',
           NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                        AND column_name LIKE '%actor%'
                        AND table_name = ANY ({q('{' + ','.join(new_name(r) for r, _ in relations) + '}')}::text[])), NULL
    UNION ALL
    SELECT 7, 'the rewritten functions exist',
           count(*) = {len(RENAMED_FUNCTIONS) + len(REBODIED_FUNCTIONS) + 1}, count(*)::text
      FROM pg_proc WHERE pronamespace = 'public'::regnamespace
       AND proname = ANY ({q('{' + ','.join([*RENAMED_FUNCTIONS.values(), *REBODIED_FUNCTIONS, RECREATED[1]]) + '}')}::text[])
    UNION ALL
    SELECT 8, 'the label reads Company / {LABEL_NEW}',
           EXISTS (SELECT 1 FROM public.organization_category_definition
                    WHERE display_name LIKE {q('%' + LABEL_NEW + '%')})
           AND NOT EXISTS (SELECT 1 FROM public.organization_category_definition
                            WHERE display_name LIKE {q('%' + LABEL_OLD + '%')}), NULL
    UNION ALL
    SELECT 9, 'the old names still read the same rows',
           (SELECT count(*) FROM public.actor) = (SELECT count(*) FROM public.organization), NULL
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
        raise SystemExit("refused: only a local *_test database")
    cat = read_catalog(args.database)
    out = build(cat)
    files = {DEFERRED / NAME: out["migration"], DEFERRED / "rollback" / NAME: out["rollback"],
             HERE / "preflight.sql": out["preflight"], HERE / "verify.sql": out["verify"],
             HERE / "ledger.sql": out["ledger"]}
    for path, text in files.items():
        path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    (HERE / "catalog.json").write_text(json.dumps(cat, indent=1), encoding="utf-8")
    print(f"written; {NAME} sha256 {out['sha']}")


if __name__ == "__main__":
    main()
