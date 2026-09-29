-- DEFERRED; NO RUNNER. P15 service/UI cutover and role audit required.
REVOKE INSERT, UPDATE, DELETE ON actor, hub, event, person, hub_actor
    FROM anon, authenticated;
REVOKE DELETE ON actor, hub, event, person, hub_actor FROM service_role;
REVOKE UPDATE (record_status, ghus_notes) ON actor FROM anon, authenticated;
REVOKE UPDATE (record_status, ghus_notes) ON event FROM anon, authenticated;
REVOKE UPDATE (center_frozen, approved_at, approved_by) ON hub FROM anon, authenticated;
