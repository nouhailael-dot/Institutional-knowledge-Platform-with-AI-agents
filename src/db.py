"""Postgres connection. Everything that talks to the database imports this.

One job: read DATABASE_URL from .env and hand out a live connection. No ORM,
no pooling framework — at 4 users and ~300 rows that would be ceremony. If you
later need a pool, add it here and nothing else changes.
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root into os.environ

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_connection() -> psycopg.Connection:
    """Open a new Postgres connection. Caller is responsible for closing it,
    so prefer the context-manager form:

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM actor")
            print(cur.fetchone())
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    return psycopg.connect(DATABASE_URL)


def get_readonly_connection() -> psycopg.Connection:
    """A hardened connection for running LLM-generated SQL (the router).

    Two guarantees the database itself enforces, so a bad query can't hurt the
    colleague's data even if our own validation missed something:
      - `read_only = True` — the session physically rejects any write/DDL.
      - `statement_timeout=8000` — a runaway query is killed after 8 seconds.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    conn = psycopg.connect(DATABASE_URL, options="-c statement_timeout=8000")
    conn.read_only = True   # must be set before the first transaction
    return conn


if __name__ == "__main__":
    # Smoke test: run `python src/db.py` once credentials are in .env.
    # Proves we can reach the colleague's populated database.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM actor")
        (n_actors,) = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM partnership_profile "
            "WHERE why_valuable_for_um6p IS NOT NULL "
            "AND btrim(why_valuable_for_um6p) <> ''"
        )
        (n_why,) = cur.fetchone()
        print(f"Connected. actors = {n_actors}")
        print(f"actors with a why_valuable_for_um6p = {n_why}")
        if n_actors:
            print(f"  -> {n_why}/{n_actors} "
                  f"({100 * n_why / n_actors:.0f}%) have the key field populated")
