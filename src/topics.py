"""Where the topic list is read from, before and after migration 820 (platform side).

Same rule as ghus-backend/agents/common/topics.py: topics were a copy of the eight
thematic sectors. After 820 the ``topic`` table is gone and each of those sectors
carries its topic's old id, so the rows come from ``sector`` with the same shape:
``topic_id``, ``code``, ``name``, ``description``, ``active``.
"""

from __future__ import annotations

SECTOR_TOPICS = ("(SELECT sector_id AS topic_id, code, name, description, active "
                 "FROM sector WHERE is_thematic)")


def topic_rows(cursor_or_connection) -> str:
    """A FROM item with the topic rows: the ``topic`` table while it exists, else the sectors."""
    row = cursor_or_connection.execute("SELECT to_regclass('public.topic') IS NOT NULL").fetchone()
    present = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return "topic" if present else SECTOR_TOPICS
