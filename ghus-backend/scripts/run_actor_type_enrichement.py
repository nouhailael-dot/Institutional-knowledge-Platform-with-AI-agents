"""Retired legacy flat actor-type enrichment command.

Architecture V2 category/type proposals must enter through discovery staging and
the approved ``promote.py``/``decisions.py`` writer paths. The historical file
name is retained so scheduled callers fail loudly instead of mutating actors.
"""

from __future__ import annotations


def main() -> None:
    raise RuntimeError(
        "legacy actor_type enrichment is retired; submit Architecture V2 "
        "category/type proposals through staged records and the approved writers"
    )


if __name__ == "__main__":
    main()
