"""Secret-safe PostgreSQL connection helpers for the additive package."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from sqlalchemy import URL, create_engine

REQUIRED_ENV = ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSFILE")
URL_SECRET = re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://)[^@\s]+@")
PASSWORD_FIELD = re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]+")


def connection_settings() -> dict[str, str]:
    if os.environ.get("PGPASSWORD"):
        raise RuntimeError("PGPASSWORD must be unset; store the password only in PGPASSFILE")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing required PostgreSQL environment variables: " + ", ".join(missing))
    passfile = Path(os.environ["PGPASSFILE"])
    if not passfile.is_file():
        raise RuntimeError("PGPASSFILE does not name an existing file")
    try:
        port = int(os.environ["PGPORT"])
    except ValueError as exc:
        raise RuntimeError("PGPORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PGPORT is outside the valid range")
    return {
        "host": os.environ["PGHOST"].strip(),
        "port": str(port),
        "user": os.environ["PGUSER"].strip(),
        "database": os.environ["PGDATABASE"].strip(),
        "sslmode": os.environ.get("PGSSLMODE", "require").strip() or "require",
    }


def database_url() -> URL:
    settings = connection_settings()
    return URL.create(
        "postgresql+psycopg2",
        username=settings["user"],
        host=settings["host"],
        port=int(settings["port"]),
        database=settings["database"],
        query={"sslmode": settings["sslmode"]},
    )


def engine(*, read_only: bool = False, statement_timeout_ms: int | None = None):
    options: list[str] = []
    if read_only:
        options.append("-c default_transaction_read_only=on")
    if statement_timeout_ms is not None:
        options.append(f"-c statement_timeout={statement_timeout_ms}")
    connect_args = {"options": " ".join(options)} if options else {}
    return create_engine(database_url(), connect_args=connect_args)


def redact_error(value: object) -> str:
    message = str(value)
    for name in ("PGPASSWORD", "DATABASE_URL", "V2_ADDITIVE_DATABASE_URL"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = URL_SECRET.sub(r"\1[REDACTED]@", message)
    message = PASSWORD_FIELD.sub(r"\1[REDACTED]", message)
    return message


def fail_safely(exc: BaseException) -> NoReturn:
    print(f"ERROR: {redact_error(exc)}", file=sys.stderr)
    raise SystemExit(1)


def guarded(main: Callable[[], None]) -> None:
    try:
        main()
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        raise SystemExit(130) from None
    except BaseException as exc:
        fail_safely(exc)
