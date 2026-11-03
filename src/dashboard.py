"""Dashboard reads: what a person did in the Ecosystem Directory, and spending by month.

GHUS Dashboard Design, 2026-11-02. Read only: every figure comes from records
the approved writers already keep in the shared database -
``review_admission_decision`` (Review admissions: Add, Update, Park) and
``review_item_decision`` (Review decisions on an existing record: Verify and
field updates), and ``collection_run.spent_usd`` for spending. Nothing here
writes, and nothing is invented: a record whose name cannot be read is left
out rather than shown under a made-up one.
"""

from __future__ import annotations

from src.browse import _readonly

# Review admission decision -> what it did to the Directory.
ADMISSION_ACTIONS = {"new": "added", "same_existing": "updated", "defer": "parked"}

_ACTIVITY_SQL = """
WITH acts AS (
  SELECT d.entity_type,
         COALESCE(d.target_entity_id::text, d.outcome->>'canonical_entity_id') AS entity_id,
         CASE d.decision_kind WHEN 'new' THEN 'added' WHEN 'same_existing' THEN 'updated'
              ELSE 'parked' END AS action,
         COALESCE(d.edited_payload->>'name', d.edited_payload->>'full_name') AS payload_name,
         d.decided_at
    FROM review_admission_decision d
   WHERE lower(btrim(d.reviewer)) = lower(btrim(%(me)s))
     AND d.decision_kind IN ('new', 'same_existing', 'defer')
     AND d.decided_at >= now() - make_interval(days => %(days)s)
  UNION ALL
  SELECT i.entity_type, i.entity_id::text,
         CASE WHEN i.review_kind = 'verify_actor' THEN 'verified' ELSE 'updated' END,
         NULL, x.decided_at
    FROM review_item_decision x
    JOIN review_item i ON i.review_item_id = x.review_item_id
   WHERE lower(btrim(x.decided_by)) = lower(btrim(%(me)s))
     AND x.decision IN ('approve', 'resolve')
     AND x.decided_at >= now() - make_interval(days => %(days)s)
)
SELECT a.entity_type, a.entity_id, a.action, a.decided_at,
       COALESCE(ac.name, p.full_name, e.name, a.payload_name) AS name
  FROM acts a
  LEFT JOIN actor ac ON a.entity_type = 'actor' AND ac.actor_id::text = a.entity_id
  LEFT JOIN person p ON a.entity_type = 'person' AND p.person_id::text = a.entity_id
  LEFT JOIN event e ON a.entity_type = 'event' AND e.event_id::text = a.entity_id
 WHERE COALESCE(ac.name, p.full_name, e.name, a.payload_name) IS NOT NULL
 ORDER BY a.decided_at DESC
 LIMIT %(limit)s
"""

_SPENDING_SQL = """
SELECT to_char(date_trunc('month', started_at), 'YYYY-MM') AS month,
       COALESCE(NULLIF(btrim(initiated_by), ''), 'not recorded') AS initiated_by,
       count(*) AS runs, COALESCE(sum(spent_usd), 0) AS spent_usd
  FROM collection_run
 WHERE NOT dry_run AND started_at IS NOT NULL
 GROUP BY 1, 2
 ORDER BY 1 DESC, 4 DESC
"""


def directory_activity(reviewer: str, *, days: int = 30, limit: int = 5) -> list[dict]:
    """The reviewer's latest Directory contributions, newest first.

    A blank name has no activity: there is no sign-in, so the name typed in
    Review Results is the only way to say whose decisions these are.
    """
    me = str(reviewer or "").strip()
    if not me:
        return []
    with _readonly() as conn, conn.cursor() as cur:
        cur.execute(_ACTIVITY_SQL, {"me": me, "days": int(days), "limit": int(limit)})
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    for row in rows:
        row["decided_at"] = row["decided_at"].isoformat() if row["decided_at"] else None
    return rows


def spending_by_month() -> list[dict]:
    """Every month's request spending, by who started the runs. For the admin.

    Months are never reset or deleted: the Dashboard shows the current month,
    and this keeps the earlier ones readable.
    """
    with _readonly() as conn, conn.cursor() as cur:
        cur.execute(_SPENDING_SQL)
        months: dict[str, dict] = {}
        for month, who, runs, spent in cur.fetchall():
            entry = months.setdefault(month, {"month": month, "spent_usd": 0.0, "runs": 0, "by": []})
            entry["spent_usd"] = round(entry["spent_usd"] + float(spent), 4)
            entry["runs"] += int(runs)
            entry["by"].append({"initiated_by": who, "runs": int(runs), "spent_usd": float(spent)})
    return list(months.values())
