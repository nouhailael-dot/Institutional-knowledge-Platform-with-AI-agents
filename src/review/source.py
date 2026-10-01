"""Read-only adapters for importing agent results owned by another checkout."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ReadOnlyRunStore:
    """Minimal RunStore-compatible reader that cannot recover or mutate jobs."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def exists(self) -> bool:
        return self.path.is_file()

    @contextmanager
    def connect(self):
        if not self.exists():
            raise FileNotFoundError(self.path)
        uri = self.path.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()
