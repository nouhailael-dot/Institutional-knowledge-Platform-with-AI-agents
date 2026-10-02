"""Assemble one searchable text blob (doc_text) per entity.

This is the join that touches the colleague's schema. If he renames a column,
THIS is the file that breaks — the column names below are the contract. Run
`python src/assemble.py` to print samples and sanity-check the output.

Design notes:
- We index only LIVE actors (merged_into_actor_id IS NULL); the 53 dedupe
  duplicates are skipped so search never returns the same org twice.
- partnership_profile and actor_relevance are 1:1 with actor (verified), so a
  LEFT JOIN is safe — no row multiplication.
- Every field is added ONLY IF it has content (see `_section`). Most actors have
  just name + description today; the 28 with a partnership_profile get the full,
  rich blob. As the data fills in, re-running this enriches docs automatically.
- Sectors are intentionally absent: the sector tables are empty right now. The
  hook is left in place (commented) so it lights up when they're populated.
"""

from src.db import get_connection


def _section(label: str, value) -> str:
    """Return 'Label: value\n' — but only if value is non-empty. This is what
    keeps empty fields (the common case here) out of the blob."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return f"{label}: {text}\n"


def assemble_actors() -> list[dict]:
    """One doc per live actor, joining in its partnership profile, relevance
    narrative, and the hubs it belongs to."""
    sql = """
        SELECT
            a.actor_id,
            a.name,
            NULLIF(to_jsonb(a)->>'actor_type', '') AS actor_type,
            COALESCE(
                NULLIF(to_jsonb(a)->>'actor_category', ''),
                NULLIF(to_jsonb(a)->>'actor_type', '')
            )
                AS actor_category,
            NULLIF(to_jsonb(a)->>'category_type', '') AS category_type,
            a.description,
            a.primary_technical_focus,
            a.technical_approach,
            a.current_activities,
            a.key_constraints,
            a.estimated_trl,
            a.location_city, a.state, a.country,
            pp.why_valuable_for_um6p,
            pp.thematic_focus,
            pp.key_entry_points,
            pp.africa_specific_mandate,
            pp.strategic_plan,
            ar.why_relevant,
            ar.current_evidence,
            -- hubs this actor belongs to, as a comma list (many hubs -> one actor)
            (SELECT string_agg(h.name, ', ')
               FROM hub_actor ha JOIN hub h ON h.hub_id = ha.hub_id
              WHERE ha.actor_id = a.actor_id) AS hub_names
        FROM actor a
        LEFT JOIN partnership_profile pp ON pp.actor_id = a.actor_id
        LEFT JOIN actor_relevance     ar ON ar.actor_id = a.actor_id
        WHERE a.merged_into_actor_id IS NULL
        ORDER BY a.name
    """
    docs = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))

            location = ", ".join(
                p for p in (r["location_city"], r["state"], r["country"]) if p
            )

            doc_text = (
                _section("Name", r["name"])
                + _section("Actor category", r["actor_category"])
                + _section("Category type", r["category_type"])
                + _section("Location", location)
                + _section("Description", r["description"])
                + _section("Primary technical focus", r["primary_technical_focus"])
                + _section("Technical approach", r["technical_approach"])
                + _section("Current activities", r["current_activities"])
                + _section("Key constraints", r["key_constraints"])
                + _section("Estimated TRL", r["estimated_trl"])
                # The most valuable text in the dataset — see CLAUDE.md.
                + _section("Why valuable for UM6P", r["why_valuable_for_um6p"])
                + _section("Thematic focus", r["thematic_focus"])
                + _section("Key entry points", r["key_entry_points"])
                + _section("Africa-specific mandate", r["africa_specific_mandate"])
                + _section("Strategic plan", r["strategic_plan"])
                + _section("Why relevant", r["why_relevant"])
                + _section("Current evidence", r["current_evidence"])
                + _section("Part of hubs", r["hub_names"])
                # + _section("Sectors", r["sector_names"])  # empty for now
            )
            docs.append({
                "entity_id": r["actor_id"],
                "entity_type": "actor",
                "name": r["name"],
                "doc_text": doc_text.strip(),
            })
    return docs


def assemble_hubs() -> list[dict]:
    """One doc per hub — the narrative descriptions of each ecosystem."""
    sql = """
        SELECT hub_id, name, primary_city, state, country, region, description,
               integrated_flow_description, cross_hub_themes, primary_sectors,
               secondary_sectors, strategic_value_summary, core_topic_strengths,
               constraints_summary, funding_summary
        FROM hub ORDER BY name
    """
    docs = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            location = ", ".join(
                p for p in (r["primary_city"], r["state"], r["country"], r["region"]) if p
            )
            doc_text = (
                _section("Hub", r["name"])
                + _section("Location", location)
                + _section("Description", r["description"])
                + _section("Integrated flow", r["integrated_flow_description"])
                + _section("Strategic value", r["strategic_value_summary"])
                + _section("Core strengths", r["core_topic_strengths"])
                + _section("Cross-hub themes", r["cross_hub_themes"])
                + _section("Primary sectors", r["primary_sectors"])
                + _section("Secondary sectors", r["secondary_sectors"])
                + _section("Constraints", r["constraints_summary"])
                + _section("Funding", r["funding_summary"])
            )
            docs.append({
                "entity_id": r["hub_id"],
                "entity_type": "hub",
                "name": r["name"],
                "doc_text": doc_text.strip(),
            })
    return docs


def assemble_events() -> list[dict]:
    """One doc per event."""
    sql = """
        SELECT event_id, name, event_type, location, recurring_pattern,
               next_date, sponsoring_orgs
        FROM event ORDER BY name
    """
    docs = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            doc_text = (
                _section("Event", r["name"])
                + _section("Type", r["event_type"])
                + _section("Location", r["location"])
                + _section("Recurring pattern", r["recurring_pattern"])
                + _section("Next date", r["next_date"])
                + _section("Sponsoring orgs", r["sponsoring_orgs"])
            )
            docs.append({
                "entity_id": r["event_id"],
                "entity_type": "event",
                "name": r["name"],
                "doc_text": doc_text.strip(),
            })
    return docs


def assemble_all() -> list[dict]:
    """Everything to be embedded, in one list. embed.py calls this."""
    return assemble_actors() + assemble_hubs() + assemble_events()


if __name__ == "__main__":
    docs = assemble_all()
    by_type = {}
    for d in docs:
        by_type[d["entity_type"]] = by_type.get(d["entity_type"], 0) + 1
    print(f"Assembled {len(docs)} docs: {by_type}")

    # Show the richest actor doc (the ones with a partnership profile) so we can
    # eyeball that why_valuable_for_um6p actually made it into the blob.
    actor_docs = [d for d in docs if d["entity_type"] == "actor"]
    richest = max(actor_docs, key=lambda d: len(d["doc_text"]))
    print("\n===== RICHEST ACTOR DOC (sanity check the join) =====")
    print(richest["doc_text"][:1500])
    print("\n===== A TYPICAL (thin) ACTOR DOC =====")
    median = sorted(actor_docs, key=lambda d: len(d["doc_text"]))[len(actor_docs)//2]
    print(median["doc_text"])
