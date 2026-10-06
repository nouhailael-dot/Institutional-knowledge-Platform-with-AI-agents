-- Read-only checks. Run after each stage; compare with the expected comment.

-- §all: row counts never change (compare with architecture_v2_cutover_baseline)
SELECT b.table_name, b.row_count AS baseline,
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) c FROM %I', b.table_name),
              false, true, '')))[1]::text::bigint AS now
FROM architecture_v2_cutover_baseline b ORDER BY 1;

-- §expand: ledger has every expand step
SELECT count(*) AS applied_steps FROM architecture_v2_migration_ledger;

-- §gazetteer: > 30000 places
SELECT count(*) AS places FROM us_city_coord;

-- §backfill: every existing actor verified with an honest bootstrap event
SELECT count(*) FILTER (WHERE status='verified') AS verified, count(*) AS actors FROM actor;
SELECT count(*) AS bootstrap_events FROM actor_verification_event
 WHERE decision_origin='existing_canonical_migration' AND decided_by IS NULL;
-- §backfill: legacy preservation dispositions
SELECT legacy_table, disposition, count(*) FROM legacy_migration_record GROUP BY 1,2 ORDER BY 1,2;
-- §backfill: data-loss audit — every row must pass
SELECT * FROM ghus_pre_cutover_data_loss_audit() WHERE NOT passed;   -- expect 0 rows

-- §review window: outstanding GHUS work
SELECT review_kind, status, count(*) FROM review_item GROUP BY 1,2 ORDER BY 1,2;
SELECT count(*) AS actors_without_category FROM actor WHERE actor_category IS NULL;  -- 0 before 495

-- §topic / contract: hub completeness
SELECT count(*) AS hubs, count(topic_id) AS with_topic, count(center_latitude) AS with_center
FROM hub;
SELECT count(*) AS memberships, count(topic_id) AS with_topic, count(distance_miles) AS with_distance
FROM hub_actor;

-- §cutover: legacy structures gone, read view intact
SELECT count(*) AS legacy_actor_columns FROM information_schema.columns
 WHERE table_schema='public' AND table_name='actor'
   AND column_name IN ('actor_type','verification_status','record_status','state',
                       'primary_technical_focus','funding_summary');                 -- expect 0
SELECT count(*) AS live_actors, count(city) AS with_city,
       count(primary_technical_focus) AS with_focus
FROM actor_read WHERE merged_into_actor_id IS NULL;
