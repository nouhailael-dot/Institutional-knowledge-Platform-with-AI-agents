-- Open-web Phase 2 domain trust and fetch accounting. Emit only; do not run automatically.

CREATE TABLE IF NOT EXISTS discovered_domain (
    domain text PRIMARY KEY,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    pages_fetched integer NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
    records_extracted integer NOT NULL DEFAULT 0 CHECK (records_extracted >= 0),
    records_promoted integer NOT NULL DEFAULT 0 CHECK (records_promoted >= 0),
    status text NOT NULL DEFAULT 'probation'
        CHECK (status IN ('probation', 'trusted', 'blocked'))
);

CREATE INDEX IF NOT EXISTS ix_discovered_domain_status_last_seen
    ON discovered_domain (status, last_seen_at DESC);
