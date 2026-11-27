"""Where the topic list is read from, before and after migration 820.

Topics were a second copy of the sectors: the same eight codes and names
(AGRI, AI, CHEM, ENERGY, HEALTH, MINING, SUSTAIN, WATER). Migration 820 gives
each of those sectors the id its topic had and removes the ``topic`` table, so
every stored ``topic_id`` (facts, requests, hubs, Review items) now names a
sector. Until 820 is applied the ``topic`` table is still read; afterwards the
same rows come from ``sector``. Either way a query gets ``topic_id``, ``code``,
``name``, ``description`` and ``active``.
"""

from __future__ import annotations

from sqlalchemy import text

# The eight thematic sectors, shaped like the old topic rows.
SECTOR_TOPICS = ("(SELECT sector_id AS topic_id, code, name, description, active "
                 "FROM sector WHERE is_thematic)")


def topic_rows(session) -> str:
    """A FROM item with the topic rows: the ``topic`` table while it exists, else the sectors."""
    present = session.execute(text("SELECT to_regclass('public.topic') IS NOT NULL")).scalar()
    return "topic" if present else SECTOR_TOPICS
