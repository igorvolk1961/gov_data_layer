-- liquibase formatted sql

-- ============================================================
-- changeset v001-000: Create data_source table
-- ============================================================
-- This table stores information about each source adapter
-- (e.g. "pravo", "rss", "stub"). All reference tables and the
-- document table reference this table via source_id FK.
-- ============================================================

CREATE TABLE IF NOT EXISTS data_source (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       VARCHAR(50) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    url             TEXT,
    jurisdiction    VARCHAR(50),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE data_source IS 'Source adapters (pravo, rss, stub) — referenced by all reference tables and document table';
COMMENT ON COLUMN data_source.source_id IS 'Adapter source id, e.g. pravo, rss, stub';
COMMENT ON COLUMN data_source.name IS 'Human-readable name, e.g. Право РФ';
COMMENT ON COLUMN data_source.url IS 'Base URL of the source';
COMMENT ON COLUMN data_source.jurisdiction IS 'Jurisdiction scope, e.g. federal';
