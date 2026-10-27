"""The schema facts a migration can change, as comparable sets (read-only queries).

Run against Supabase before and after the reconciliation: the sets must be
identical, because the reconciliation writes ledger rows only.
"""

QUERIES = {
    "tables": """
        SELECT c.relname || ' kind=' || c.relkind::text || ' rls=' || c.relrowsecurity::text
               || ' force_rls=' || c.relforcerowsecurity::text
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')""",
    "columns": """
        SELECT c.table_name || '.' || c.column_name || ' ' || c.data_type || ' null=' || c.is_nullable
               || ' default=' || coalesce(c.column_default, '')
        FROM information_schema.columns c WHERE c.table_schema = 'public'""",
    "constraints": """
        SELECT cl.relname || '.' || co.conname || ' [' || co.contype::text || '] '
               || pg_get_constraintdef(co.oid) || CASE WHEN co.convalidated THEN '' ELSE ' NOT VALID' END
        FROM pg_constraint co JOIN pg_class cl ON cl.oid = co.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace WHERE n.nspname = 'public'""",
    "indexes": "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'",
    "triggers": """
        SELECT c.relname || '.' || t.tgname || ' -> ' || p.proname || ' enabled=' || t.tgenabled::text
               || ' ' || pg_get_triggerdef(t.oid)
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_proc p ON p.oid = t.tgfoid WHERE n.nspname = 'public' AND NOT t.tgisinternal""",
    # Function bodies by hash; functions owned by an extension (pgvector lives
    # in public on Supabase) are the extension's, not a migration's.
    "functions": """
        SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ') '
               || md5(pg_get_functiondef(p.oid))
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                            AND d.deptype = 'e')""",
    "comments": """
        SELECT 'column ' || c.relname || '.' || a.attname || ': ' || d.description
        FROM pg_description d JOIN pg_class c ON c.oid = d.objoid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.objsubid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND d.classoid = 'pg_class'::regclass AND d.objsubid > 0
        UNION ALL
        SELECT 'table ' || c.relname || ': ' || d.description
        FROM pg_description d JOIN pg_class c ON c.oid = d.objoid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND d.classoid = 'pg_class'::regclass AND d.objsubid = 0
        UNION ALL
        SELECT 'constraint ' || cl.relname || '.' || co.conname || ': ' || d.description
        FROM pg_description d JOIN pg_constraint co ON co.oid = d.objoid
        JOIN pg_class cl ON cl.oid = co.conrelid JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public' AND d.classoid = 'pg_constraint'::regclass""",
    "policies": """SELECT tablename || '.' || policyname || ' ' || cmd || ' ' || array_to_string(roles, ',')
                   || ' ' || coalesce(qual, '') || ' ' || coalesce(with_check, '')
                   FROM pg_policies WHERE schemaname = 'public'""",
}


def snapshot(execute) -> dict[str, set[str]]:
    """``execute(sql)`` returns rows of one text column."""
    return {kind: {row[0] for row in execute(sql)} for kind, sql in QUERIES.items()}


def diff(before: dict, after: dict) -> dict[str, dict[str, list[str]]]:
    """Per kind, what only one side has. Empty dict means identical."""
    out = {}
    for kind in sorted(set(before) | set(after)):
        a, b = set(before.get(kind, ())), set(after.get(kind, ()))
        if a != b:
            out[kind] = {"only_before": sorted(a - b), "only_after": sorted(b - a)}
    return out
