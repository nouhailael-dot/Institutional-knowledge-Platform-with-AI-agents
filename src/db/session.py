"""
Database session factory.

Reads DATABASE_URL from the environment and exposes a SessionLocal factory
that hands out connected sessions to callers. Use a context manager pattern
when consuming:

    with SessionLocal() as session:
        ...
"""

import os
import socket
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# Load .env from the project root regardless of where this is imported from
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and fill it in."
    )


def _connect_args() -> dict:
    args = {"connect_timeout": 15}
    try:
        url = make_url(DATABASE_URL)
        if url.get_backend_name().startswith("postgresql") and url.host:
            port = url.port or 5432
            infos = socket.getaddrinfo(url.host, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                args["hostaddr"] = infos[0][4][0]
    except OSError:
        pass
    return args


engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args(),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
