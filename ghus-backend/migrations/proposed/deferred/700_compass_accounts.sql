-- PROPOSAL for the schema owner (GHUS Compass multi-user accounts, Nov 2026).
-- Never executed on shared Supabase by an agent. Apply only after explicit
-- approval, a fresh backup, and an entry in the migration ledger.
--
-- Identities are Supabase Auth's (auth.users). This adds only what Compass
-- needs around them, in its own schema so no ecosystem table is duplicated or
-- altered:
--
--   compass.permission / role / role_permission   configurable roles
--   compass.user_profile                          name, role, status, preferences
--   compass.invitation                            admin-issued, invitation-only sign-up
--   compass.audit_event                           permanent, append-only history
--   compass.record_owner                          original owner of a shared record
--   compass.usage_event                           per-user runs, tokens and cost
--   compass.notification                          per-user notices
--
-- No role is assigned and no user is created here. A profile with no role has
-- no access. Seeded roles: admin, editor, viewer (see the permission matrix).
--
-- Security: the platform backend is the only client (it connects as the
-- database owner and enforces every permission). Row Level Security is on for
-- every table, and the browser roles (anon, authenticated) have no grant on the
-- schema, so the Supabase REST API exposes none of it.
--
-- Additive: a new schema; no existing row changes.
-- ROLLBACK: migrations/proposed/deferred/rollback/700_compass_accounts.sql

BEGIN;

CREATE SCHEMA IF NOT EXISTS compass;
REVOKE ALL ON SCHEMA compass FROM PUBLIC;
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON SCHEMA compass FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON SCHEMA compass FROM authenticated';
    END IF;
END $grants$;

-- Roles and permissions ---------------------------------------------------------
CREATE TABLE compass.permission (
    code        text PRIMARY KEY CHECK (code ~ '^[a-z_]+\.[a-z_]+$'),
    description text NOT NULL
);

CREATE TABLE compass.role (
    code        text PRIMARY KEY CHECK (code ~ '^[a-z_]+$'),
    label       text NOT NULL,
    description text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE compass.role_permission (
    role_code       text NOT NULL REFERENCES compass.role(code) ON DELETE CASCADE,
    permission_code text NOT NULL REFERENCES compass.permission(code) ON DELETE CASCADE,
    PRIMARY KEY (role_code, permission_code)
);

-- Profiles -----------------------------------------------------------------------
CREATE TABLE compass.user_profile (
    user_id        uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    email          text NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    full_name      text NOT NULL CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 120),
    role_code      text REFERENCES compass.role(code),          -- NULL: no access
    status         text NOT NULL DEFAULT 'invited'
                   CHECK (status IN ('invited', 'active', 'deactivated')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    last_login_at  timestamptz,
    -- Sessions that began before this are refused (password change or reset, deactivation).
    sessions_valid_after timestamptz,
    deactivated_at timestamptz,
    deactivated_by uuid REFERENCES compass.user_profile(user_id),
    preferences    jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(preferences) = 'object'),
    CHECK ((status = 'deactivated') = (deactivated_at IS NOT NULL))
);
CREATE UNIQUE INDEX user_profile_email_key ON compass.user_profile (email);
CREATE INDEX user_profile_role_idx ON compass.user_profile (role_code);

-- Invitations (invitation-only registration) -------------------------------------
CREATE TABLE compass.invitation (
    invitation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    full_name     text NOT NULL CHECK (char_length(btrim(full_name)) BETWEEN 1 AND 120),
    role_code     text NOT NULL REFERENCES compass.role(code),
    -- NULL only for the first administrator, invited by the bootstrap command.
    invited_by    uuid REFERENCES compass.user_profile(user_id),
    bootstrap     boolean NOT NULL DEFAULT false,
    user_id       uuid REFERENCES auth.users(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    accepted_at   timestamptz,
    revoked_at    timestamptz,
    revoked_by    uuid REFERENCES compass.user_profile(user_id),
    CHECK (expires_at > created_at),
    CHECK (accepted_at IS NULL OR revoked_at IS NULL),
    CHECK (invited_by IS NOT NULL OR bootstrap)
);
-- One open invitation per address.
CREATE UNIQUE INDEX invitation_open_email_key ON compass.invitation (email)
    WHERE accepted_at IS NULL AND revoked_at IS NULL;

-- Permanent audit history ---------------------------------------------------------
CREATE TABLE compass.audit_event (
    audit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    user_id      uuid REFERENCES compass.user_profile(user_id),   -- NULL: before accounts
    user_label   text NOT NULL,                                   -- name at the time
    action       text NOT NULL CHECK (action ~ '^[a-z_]+\.[a-z_]+$'),
    entity_type  text,
    entity_id    text,
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_addr  text
);
CREATE INDEX audit_event_user_idx ON compass.audit_event (user_id, occurred_at DESC);
CREATE INDEX audit_event_entity_idx ON compass.audit_event (entity_type, entity_id, occurred_at DESC);
CREATE INDEX audit_event_action_idx ON compass.audit_event (action, occurred_at DESC);

CREATE FUNCTION compass.guard_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'compass.% is append-only', TG_TABLE_NAME;
END $$;
CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON compass.audit_event
    FOR EACH ROW EXECUTE FUNCTION compass.guard_append_only();

-- Original ownership of shared records -------------------------------------------
-- One row per record that a known user first created, imported, discovered or
-- mapped. Editing or verifying never changes it; a record without a row shows
-- "Not recorded".
CREATE TABLE compass.record_owner (
    entity_type   text NOT NULL CHECK (entity_type IN ('actor', 'person', 'event', 'hub',
                                                       'request', 'map', 'import')),
    entity_id     text NOT NULL,
    owner_user_id uuid NOT NULL REFERENCES compass.user_profile(user_id),
    origin        text NOT NULL CHECK (origin IN ('created', 'imported', 'discovered', 'mapped',
                                                  'requested')),
    -- What brought it in: the Review item, map or import (provenance; never a person).
    source_ref    text,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX record_owner_owner_idx ON compass.record_owner (owner_user_id, entity_type);

CREATE FUNCTION compass.guard_owner_unchanged() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.origin IS DISTINCT FROM OLD.origin OR NEW.recorded_at IS DISTINCT FROM OLD.recorded_at
       OR NEW.source_ref IS DISTINCT FROM OLD.source_ref THEN
        RAISE EXCEPTION 'original ownership of % % never changes', OLD.entity_type, OLD.entity_id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER record_owner_unchanged BEFORE UPDATE OR DELETE ON compass.record_owner
    FOR EACH ROW EXECUTE FUNCTION compass.guard_owner_unchanged();

-- Usage and cost ------------------------------------------------------------------
-- Who started each paid operation, and how. Costs stay in their existing ledgers
-- (collection_run.spent_usd, scrape_run.cost_usd, the map store's calls) and are
-- read from there; this table never copies them. It holds a cost only for an
-- operation that has no ledger of its own: an Ask Compass answer (priced from its
-- token usage) or an organization check that was never applied (the cost the check
-- reported). One row per operation; append-only.
CREATE TABLE compass.usage_event (
    usage_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    user_id       uuid REFERENCES compass.user_profile(user_id),
    kind          text NOT NULL CHECK (kind IN ('run_now', 'actor_check', 'people_search',
                                                'datafeed_completion', 'ask', 'other')),
    reference     text NOT NULL,                -- run, check, task or import id
    trigger       text NOT NULL DEFAULT 'manual' CHECK (trigger IN ('manual', 'run_now', 'scheduled')),
    cost_usd      numeric(12, 6) CHECK (cost_usd >= 0),   -- only when no ledger holds it
    cost_basis    text NOT NULL DEFAULT 'ledger'
                  CHECK (cost_basis IN ('ledger', 'usage_priced', 'check_result', 'unknown')),
    input_tokens  bigint CHECK (input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens >= 0),
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (kind, reference)
);
CREATE INDEX usage_event_user_idx ON compass.usage_event (user_id, occurred_at DESC);
CREATE TRIGGER usage_event_append_only BEFORE UPDATE OR DELETE ON compass.usage_event
    FOR EACH ROW EXECUTE FUNCTION compass.guard_append_only();

-- Notifications ------------------------------------------------------------------
CREATE TABLE compass.notification (
    notification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES compass.user_profile(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    kind       text NOT NULL CHECK (kind ~ '^[a-z_]+$'),
    title      text NOT NULL CHECK (char_length(title) <= 200),
    body       text NOT NULL DEFAULT '' CHECK (char_length(body) <= 2000),
    link       text,
    read_at    timestamptz,
    -- One notification per event and person: a second attempt is ignored.
    dedupe_key text NOT NULL CHECK (char_length(dedupe_key) BETWEEN 1 AND 200),
    -- Email delivery, for later: asked for by the person's preferences; nothing
    -- sends it yet (emailed_at stays empty until an approved sender exists).
    email_requested boolean NOT NULL DEFAULT false,
    emailed_at timestamptz,
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX notification_unread_idx ON compass.notification (user_id, created_at DESC)
    WHERE read_at IS NULL;
CREATE INDEX notification_email_idx ON compass.notification (created_at)
    WHERE email_requested AND emailed_at IS NULL;

-- Row Level Security: on everywhere, no browser access ----------------------------
ALTER TABLE compass.permission      ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.role            ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.role_permission ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.user_profile    ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.invitation      ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.audit_event     ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.record_owner    ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.usage_event     ENABLE ROW LEVEL SECURITY;
ALTER TABLE compass.notification    ENABLE ROW LEVEL SECURITY;
-- No policies: anon and authenticated see nothing even if granted later by
-- mistake. The backend (table owner) is not subject to these policies.

-- Seed: permissions and the three roles (no user, no assignment) -------------------
INSERT INTO compass.permission (code, description) VALUES
    ('records.view',            'Browse the shared organizations, people, events and hubs'),
    ('ask.use',                 'Ask Compass questions'),
    ('maps.view',               'Open maps the user may see'),
    ('dashboard.view',          'Open the personal dashboard'),
    ('usage.view_own',          'See one''s own usage and costs'),
    ('maps.create',             'Create maps and run paid map research'),
    ('requests.view',           'Open Monitor and Update requests'),
    ('requests.create',         'Create and run Discovery and Update requests (paid agents)'),
    ('datafeed.import',         'Import records through Data Feed'),
    ('review.view',             'Open Review Results'),
    ('review.decide',           'Verify, reject and park records'),
    ('records.edit',            'Edit shared records'),
    ('notes.write',             'Add and edit GHUS Notes'),
    ('records.remove',          'Remove a record from the Directory, or restore it'),
    ('records.delete_permanent','Permanently delete a record (confirmation, dependency checks, audit)'),
    ('usage.view_all',          'See every user''s usage, costs and activity'),
    ('audit.view_all',          'Read the full audit history'),
    ('users.manage',            'Invite users, assign roles, activate and deactivate accounts'),
    ('settings.admin',          'Change administrative and security settings');

INSERT INTO compass.role (code, label, description) VALUES
    ('admin',  'Admin',             'Full access, user management, all usage and costs'),
    ('editor', 'Editor / Reviewer', 'Works on the shared database; cannot manage users or security settings'),
    ('viewer', 'Viewer',            'Read-only: browse records, Ask Compass, authorized maps');

INSERT INTO compass.role_permission (role_code, permission_code)
SELECT 'admin', code FROM compass.permission;

INSERT INTO compass.role_permission (role_code, permission_code) VALUES
    ('editor', 'records.view'), ('editor', 'ask.use'), ('editor', 'maps.view'),
    ('editor', 'dashboard.view'), ('editor', 'usage.view_own'), ('editor', 'maps.create'),
    ('editor', 'requests.view'), ('editor', 'requests.create'), ('editor', 'datafeed.import'),
    ('editor', 'review.view'), ('editor', 'review.decide'), ('editor', 'records.edit'),
    ('editor', 'notes.write'), ('editor', 'records.remove'), ('editor', 'records.delete_permanent'),
    ('viewer', 'records.view'), ('viewer', 'ask.use'), ('viewer', 'maps.view'),
    ('viewer', 'dashboard.view'), ('viewer', 'usage.view_own');

COMMIT;
