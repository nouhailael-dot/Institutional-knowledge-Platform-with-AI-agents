"""Run pytest without .env, service credentials, or network connections.

From the platform root: python scripts/test_offline.py tests -q
From ghus-backend: python ../scripts/test_offline.py tests/agent -q
The placeholder key permits mocked Anthropic clients to initialize. Actual
network connections fail immediately, including connections to local databases.
"""
import os
from pathlib import Path
import socket
import sys
import threading


def main():
    for name in list(os.environ):
        if any(token in name.upper() for token in
               ("DATABASE_URL", "API_KEY", "ACCESS_TOKEN", "SECRET_KEY")):
            os.environ.pop(name, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["GHUS_AGENT_AUTO_VERIFY"] = "0"
    os.environ["ANTHROPIC_API_KEY"] = "offline-test-placeholder"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path.cwd()))

    # Windows implements socketpair over a private loopback connection. AnyIO
    # needs that pair for its event loop, even with an in-process TestClient.
    original_pair = socket.socketpair
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    context = threading.local()

    def local_pair(*args, **kwargs):
        context.creating_pair = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            context.creating_pair = False

    def guarded_connect(sock, address):
        if getattr(context, "creating_pair", False):
            return original_connect(sock, address)
        raise AssertionError("Offline test attempted a real network connection")

    def guarded_connect_ex(sock, address):
        if getattr(context, "creating_pair", False):
            return original_connect_ex(sock, address)
        raise AssertionError("Offline test attempted a real network connection")

    socket.socketpair = local_pair
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    import pytest
    return pytest.main(["-p", "no:cacheprovider", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
