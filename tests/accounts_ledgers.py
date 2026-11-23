"""Small stand-ins of the run ledgers (collection_run, scrape_run, the request tables),
created in the isolated accounts test database only, with the columns Compass reads."""

from __future__ import annotations

from urllib.parse import urlsplit

import psycopg


def create_ledgers(conninfo: str) -> None:
    parts = urlsplit(conninfo.replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"127.0.0.1", "localhost"} and parts.path.rstrip("/").endswith("_test"), \
        "ledger stand-ins only ever go into a local *_test database"
    with psycopg.connect(conninfo.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        for table in ("actor_update_subscription_run", "collection_run", "actor_update_subscription", "scrape_run"):
            conn.execute(f"DROP TABLE IF EXISTS public.{table}")
        conn.execute("""CREATE TABLE public.actor_update_subscription (
            actor_update_subscription_id uuid PRIMARY KEY, title text, status text, next_due_at timestamptz)""")
        conn.execute("""CREATE TABLE public.collection_run (
            collection_run_id uuid PRIMARY KEY, status text, started_at timestamptz, finished_at timestamptz,
            status_reason text, found_count int, staged_count int, review_item_count int,
            job_name text DEFAULT 'discovery_request', trigger_type text DEFAULT 'subscription',
            spent_usd numeric DEFAULT 0, config_snapshot jsonb DEFAULT '{}'::jsonb, dry_run boolean DEFAULT false)""")
        conn.execute("""CREATE TABLE public.actor_update_subscription_run (
            actor_update_subscription_id uuid, collection_run_id uuid, dry_run boolean DEFAULT false)""")
        conn.execute("""CREATE TABLE public.scrape_run (
            run_id uuid PRIMARY KEY, source_name text, status text, started_at timestamptz,
            finished_at timestamptz, cost_usd numeric DEFAULT 0)""")
