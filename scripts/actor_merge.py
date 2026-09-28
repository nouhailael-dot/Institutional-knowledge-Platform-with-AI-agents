"""Retired legacy actor merge entrypoints.

Architecture V2 keeps canonical facts and edges append-only. Manual duplicate
decisions must be represented by the V2 review workflow in
``agents.enrichment.decisions``; this compatibility module deliberately cannot
mutate, repoint, delete, or restore canonical rows.
"""

from __future__ import annotations

_MESSAGE = (
    "legacy actor merge is retired under Architecture V2; submit a "
    "possible_duplicate decision through agents.enrichment.decisions"
)


def merge_actors(*args, **kwargs):
    raise RuntimeError(_MESSAGE)


def revert_merge(*args, **kwargs):
    raise RuntimeError(_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(_MESSAGE)
