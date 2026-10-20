-- PROPOSAL ONLY. Platform-owned frozen-center review history.
BEGIN;
CREATE TABLE IF NOT EXISTS hub_center_review (
    hub_center_review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id uuid NOT NULL REFERENCES hub(hub_id),
    proposed_city text NOT NULL,
    proposed_state_code text REFERENCES region_state(state_code),
    proposed_latitude numeric(9,6) NOT NULL,
    proposed_longitude numeric(9,6) NOT NULL,
    shift_miles numeric(8,2) NOT NULL,
    trigger_threshold_miles numeric(8,2) NOT NULL DEFAULT 25,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (hub_id,proposed_latitude,proposed_longitude,status)
);
COMMIT;
