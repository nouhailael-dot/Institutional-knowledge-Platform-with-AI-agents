"""Deterministic read access for Architecture V2 immutable facts."""

from __future__ import annotations

from sqlalchemy import text


def current_actor_facts(session, *, actor_id: str, topic_id: str | None = None):
    """Return one current fact per logical key, scoped to an optional topic."""
    return session.execute(
        text(
            "SELECT * FROM actor_fact_current_v2 WHERE actor_id=CAST(:actor AS uuid) "
            "AND (:topic IS NULL OR topic_id=CAST(:topic AS uuid)) "
            "ORDER BY topic_id,fact_key"
        ),
        {"actor": actor_id, "topic": topic_id},
    ).mappings().all()


def actor_fact_history(
    session, *, actor_id: str, topic_id: str | None = None, fact_key: str | None = None
):
    """Return immutable current and historical versions without collapsing evidence."""
    return session.execute(
        text(
            "SELECT * FROM actor_fact_history WHERE actor_id=CAST(:actor AS uuid) "
            "AND (:topic IS NULL OR topic_id=CAST(:topic AS uuid)) "
            "AND (:fact_key IS NULL OR fact_key=:fact_key) "
            "ORDER BY topic_id,fact_key,created_at,actor_fact_id"
        ),
        {"actor": actor_id, "topic": topic_id, "fact_key": fact_key},
    ).mappings().all()
