"""Read-only database access for reporting tools."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
READONLY_URL_ENV_VARS = (
    "GHUS_READONLY_DATABASE_URL",
    "DATABASE_READONLY_URL",
    "READONLY_DATABASE_URL",
)


class MissingReadOnlyDatabaseUrl(RuntimeError):
    """Raised when reporting would otherwise fall back to an owner DB URL."""


def readonly_database_url(env: Optional[Mapping[str, str]] = None) -> str:
    values = env if env is not None else os.environ
    for name in READONLY_URL_ENV_VARS:
        value = values.get(name)
        if value:
            return value
    names = ", ".join(READONLY_URL_ENV_VARS)
    raise MissingReadOnlyDatabaseUrl(
        f"Reporting requires one read-only connection string: {names}. "
        "It will not fall back to DATABASE_URL."
    )


def create_readonly_engine(url: Optional[str] = None, *, env: Optional[Mapping[str, str]] = None) -> Engine:
    load_dotenv(PROJECT_ROOT / ".env")
    db_url = url or readonly_database_url(env)
    return create_engine(db_url, future=True, pool_pre_ping=True)


def create_readonly_sessionmaker(
    url: Optional[str] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> sessionmaker[Session]:
    engine = create_readonly_engine(url, env=env)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )


@contextmanager
def readonly_session(
    url: Optional[str] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Iterator[Session]:
    SessionLocal = create_readonly_sessionmaker(url, env=env)
    with SessionLocal() as session:
        yield session
