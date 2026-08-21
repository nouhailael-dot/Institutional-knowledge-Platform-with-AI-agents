"""
Database session factory.

Reads DATABASE_URL from the environment and exposes a SessionLocal factory
that hands out connected sessions to callers. Use a context manager pattern
when consuming:

    with SessionLocal() as session:
        ...
"""

import os
import ipaddress
import socket
import subprocess
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


def _public_ipv4_addresses(host: str, port: int) -> list[str]:
    addresses = []
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        infos = []

    for info in infos:
        ip = info[4][0]
        if ipaddress.ip_address(ip).is_global and ip not in addresses:
            addresses.append(ip)

    if addresses or os.name != "nt":
        return addresses

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"Resolve-DnsName -Type A {host} | "
                    "Where-Object { $_.IPAddress } | "
                    "Select-Object -ExpandProperty IPAddress"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return addresses

    for line in result.stdout.splitlines():
        ip = line.strip()
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if parsed.version == 4 and parsed.is_global and ip not in addresses:
            addresses.append(ip)
    return addresses


def _connect_args() -> dict:
    args = {"connect_timeout": 15}
    try:
        url = make_url(DATABASE_URL)
        if url.get_backend_name().startswith("postgresql") and url.host:
            port = url.port or 5432
            for ip in _public_ipv4_addresses(url.host, port):
                try:
                    with socket.create_connection((ip, port), timeout=3):
                        args["hostaddr"] = ip
                        break
                except OSError:
                    continue
    except OSError:
        pass
    return args


engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args(),
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)
