"""Records awaiting permanent deletion (migration 710): agents treat them as gone.

A deleted organization, person, event or hub stays in its table for 30 days so it
can be restored; meanwhile no agent reads, updates or proposes it as an active
record. Without migration 710 (no compass.deleted_record) nothing is deleted.
"""

from __future__ import annotations

from sqlalchemy import text


def pending_deletion_ids(session, entity_type: str) -> set[str]:
    if not session.execute(text("SELECT to_regclass('compass.deleted_record') IS NOT NULL")).scalar():
        return set()
    return {row[0] for row in session.execute(text(
        "SELECT entity_id::text FROM compass.deleted_record WHERE entity_type = :t "
        "AND restored_at IS NULL AND purged_at IS NULL"), {"t": entity_type}).all()}
