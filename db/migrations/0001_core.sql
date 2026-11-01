-- 0001_core.sql: the core system tables every later module relies on.
--
-- These tables live in their own schema (default: "engine"). A schema is a named folder
-- of tables inside the database. Supabase only exposes the "public" schema to its web API,
-- so keeping ours separate means nobody can read these tables through Supabase's API.
-- Row Level Security is also switched on as a second lock.

-- system_flag: system-wide switches, stored as key/value. Used for the kill switch, so the
-- dashboard and every worker see the same stop signal.
CREATE TABLE system_flag (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    reason      text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- job: one unit of background work (render a video, publish a post, pull metrics).
-- idempotency_key is UNIQUE, so the same piece of work can never be queued twice.
CREATE TABLE job (
    id               bigserial PRIMARY KEY,
    kind             text NOT NULL,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key  text NOT NULL UNIQUE,
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'done', 'dead')),
    attempts         int  NOT NULL DEFAULT 0,
    max_attempts     int  NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
    run_after        timestamptz NOT NULL DEFAULT now(),
    locked_at        timestamptz,
    locked_by        text,
    last_error       text,
    error_class      text,
    result           jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz
);
-- Lets the worker find the next runnable job quickly.
CREATE INDEX job_ready_idx ON job (run_after, id) WHERE status = 'queued';

-- alert: something you need to know about (a job died, spend spiked, an account got flagged).
CREATE TABLE alert (
    id               bigserial PRIMARY KEY,
    severity         text NOT NULL CHECK (severity IN ('info', 'warn', 'critical')),
    source           text NOT NULL,
    message          text NOT NULL,
    details          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    emailed_at       timestamptz,
    acknowledged_at  timestamptz
);
CREATE INDEX alert_open_idx ON alert (created_at) WHERE acknowledged_at IS NULL;

-- approval: an item waiting for your yes/no before it can go out (a caption, a post, an ad
-- change). One row per item, so the same thing is never asked about twice.
CREATE TABLE approval (
    id             bigserial PRIMARY KEY,
    item_type      text NOT NULL,
    item_id        text NOT NULL,
    summary        text NOT NULL,
    status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'approved', 'rejected')),
    decision_note  text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    decided_at     timestamptz,
    UNIQUE (item_type, item_id)
);

ALTER TABLE system_flag ENABLE ROW LEVEL SECURITY;
ALTER TABLE job         ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert       ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval    ENABLE ROW LEVEL SECURITY;
