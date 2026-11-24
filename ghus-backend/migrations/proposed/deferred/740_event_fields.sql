-- 740: events get the place and format columns of the Events template (GHUS, 24 Nov 2026).
--
-- Structure only: adds 8 empty columns to public.event. Nothing is removed and no row
-- is written: the free-text `location` stays, so every page and agent keeps working.
--
--   venue, city, state_code, country, region_code   the template's Venue, City, State,
--                                                    Country and Region
--   event_format                                     In person / Online / Hybrid
--   registration_url                                 Registration URL
--   organizer                                        who runs or hosts it (sponsors stay
--                                                    in sponsoring_orgs)
--
-- Filling the place columns from today's `location` is a separate, optional step that
-- is NOT part of 740: migrations/proposed/event_740/ (generate.py -> fill_locations.sql).
--
-- One transaction: any failure changes nothing. Rollback:
-- deferred/rollback/740_event_fields.sql

BEGIN;
SET LOCAL lock_timeout = '15s';

DO $guard$
BEGIN
    IF EXISTS (SELECT 1 FROM public.architecture_v2_migration_ledger WHERE migration_id = '740') THEN
        RAISE EXCEPTION '740 refused: already in the ledger';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                 AND table_name = 'event'
                 AND column_name IN ('venue', 'city', 'state_code', 'country', 'region_code',
                                     'event_format', 'registration_url', 'organizer')) THEN
        RAISE EXCEPTION '740 refused: public.event already has one of the new columns';
    END IF;
END $guard$;

ALTER TABLE public.event
    ADD COLUMN venue text,
    ADD COLUMN city text,
    ADD COLUMN state_code text,
    ADD COLUMN country text,
    ADD COLUMN region_code text,
    ADD COLUMN event_format text
        CHECK (event_format IS NULL OR event_format IN ('In person', 'Online', 'Hybrid')),
    ADD COLUMN registration_url text,
    ADD COLUMN organizer text;

COMMENT ON COLUMN public.event.venue IS 'Venue (Events template)';
COMMENT ON COLUMN public.event.city IS 'City (Events template)';
COMMENT ON COLUMN public.event.state_code IS 'State, two letters (Events template)';
COMMENT ON COLUMN public.event.country IS 'Country: USA or the country name (Events template)';
COMMENT ON COLUMN public.event.region_code IS 'Region, from the state (region_state)';
COMMENT ON COLUMN public.event.event_format IS 'Format: In person, Online or Hybrid (Events template)';
COMMENT ON COLUMN public.event.registration_url IS 'Registration URL (Events template)';
COMMENT ON COLUMN public.event.organizer IS 'Organizer: who runs or hosts the event; sponsors stay in sponsoring_orgs';

COMMIT;
