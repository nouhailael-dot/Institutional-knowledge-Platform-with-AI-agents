"""Postgres connection. Everything that talks to the database imports this.

One job: read DATABASE_URL from .env and hand out a live connection. No ORM,
no pooling framework — at 4 users and ~300 rows that would be ceremony. If you
later need a pool, add it here and nothing else changes.
"""

import ipaddress
import os
import socket
import time
from urllib.parse import urlsplit

import psycopg
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root into os.environ

DATABASE_URL = os.environ.get("DATABASE_URL")
CONNECT_TIMEOUT_SECONDS = 10


def psycopg_database_url(value: str | None) -> str:
    """Convert common SQLAlchemy PostgreSQL URLs to Psycopg conninfo.

    SQLAlchemy records its driver after a ``+`` in the scheme. Psycopg/libpq
    does not understand that suffix, even when it names Psycopg itself. Keep
    credentials and every other URL component byte-for-byte unchanged.
    """
    url = str(value or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
        )
    for scheme in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
    ):
        if url.lower().startswith(scheme):
            return "postgresql://" + url[len(scheme):]
    if url.lower().startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    if url.lower().startswith("postgresql://"):
        return url
    if "://" not in url:
        return url  # libpq keyword conninfo, e.g. "host=... dbname=..."
    raise RuntimeError("DATABASE_URL must use a PostgreSQL connection scheme.")


# The shared database's last address that resolved, per host:port. On 2026-11-03
# this computer's DNS failed twelve times in a day ("failed to resolve host
# aws-1-us-east-1.pooler.supabase.com"); each failure took a page down although
# the database itself was up. A failed lookup now uses the address that last worked.
_last_good_hostaddr: dict[str, str] = {}
# Waits before each connection attempt: at once, then after 1 s and 3 s.
CONNECT_RETRY_WAITS = (0, 1, 3)


def stable_hostaddr(conninfo: str) -> str | None:
    """The database host's IPv4 address, or the last one that resolved when DNS fails.

    None for a local or literal-IP host, or keyword conninfo: nothing to resolve.
    """
    if "://" not in str(conninfo or ""):
        return None
    parsed = urlsplit(conninfo)
    host = parsed.hostname
    if not host or host == "localhost":
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    key = f"{host}:{parsed.port or 5432}"
    try:
        infos = socket.getaddrinfo(host, parsed.port or 5432, socket.AF_INET, socket.SOCK_STREAM)
        _last_good_hostaddr[key] = infos[0][4][0]
    except OSError:
        pass
    return _last_good_hostaddr.get(key)


def connect_resilient(conninfo: str, **kwargs) -> psycopg.Connection:
    """psycopg.connect, through a DNS blip and a pooler's slow start.

    The host name is kept (TLS checks it); ``hostaddr`` only spares the lookup.
    """
    last: Exception | None = None
    for wait in CONNECT_RETRY_WAITS:
        if wait:
            time.sleep(wait)
        extra = {}
        if "hostaddr" not in kwargs:
            hostaddr = stable_hostaddr(conninfo)
            if hostaddr:
                extra["hostaddr"] = hostaddr
        try:
            return psycopg.connect(conninfo, **kwargs, **extra)
        except psycopg.OperationalError as exc:
            last = exc
    raise last  # type: ignore[misc]


def _connect(*, read_only: bool = False) -> psycopg.Connection:
    """Open PostgreSQL, riding out transient DNS, pooler and network failures."""
    conninfo = psycopg_database_url(DATABASE_URL)
    kwargs = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    if read_only:
        kwargs["options"] = "-c statement_timeout=8000"
    conn = connect_resilient(conninfo, **kwargs)
    if read_only:
        conn.read_only = True
    return conn


def get_connection() -> psycopg.Connection:
    """Open a new Postgres connection. Caller is responsible for closing it,
    so prefer the context-manager form:

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM actor")
            print(cur.fetchone())
    """
    return _connect()


def get_readonly_connection() -> psycopg.Connection:
    """A hardened connection for running LLM-generated SQL (the router).

    Two guarantees the database itself enforces, so a bad query can't hurt the
    colleague's data even if our own validation missed something:
      - `read_only = True` — the session physically rejects any write/DDL.
      - `statement_timeout=8000` — a runaway query is killed after 8 seconds.
    """
    return _connect(read_only=True)


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
