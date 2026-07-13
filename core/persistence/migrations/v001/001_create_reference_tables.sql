-- liquibase formatted sql

-- ============================================================
-- changeset v001-001: Create reference tables
-- ============================================================
-- These tables store reference data from the source API:
--   document_type  — e.g. "Federal Law", "Presidential Decree"
--   organization   — e.g. "President of the Russian Federation"
--   jurisdiction   — e.g. "federal", "regional"
--   region         — e.g. "Moscow", "Saint Petersburg"
--   topic          — e.g. "Economy", "Social Policy"
-- All reference tables are scoped to a data_source via source_id FK.
-- ============================================================

-- -----------------------------------------------------------
-- document_type
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_type (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id     VARCHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE document_type IS 'Document types from source (e.g. Federal Law, Presidential Decree)';
COMMENT ON COLUMN document_type.external_id IS 'Source-specific document type identifier (GUID string)';
COMMENT ON COLUMN document_type.name IS 'Human-readable document type name';
COMMENT ON COLUMN document_type.weight IS 'Sorting weight (lower = more important)';

-- -----------------------------------------------------------
-- organization
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS organization (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id     VARCHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE organization IS 'Organizations from source (e.g. President, Government, Ministry)';
COMMENT ON COLUMN organization.external_id IS 'Source-specific organization identifier (GUID string)';
COMMENT ON COLUMN organization.name IS 'Human-readable organization name';
COMMENT ON COLUMN organization.weight IS 'Sorting weight (lower = more important)';

-- -----------------------------------------------------------
-- jurisdiction
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS jurisdiction (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id     VARCHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE jurisdiction IS 'Jurisdictions from source (e.g. federal, regional)';
COMMENT ON COLUMN jurisdiction.external_id IS 'Source-specific jurisdiction identifier (GUID string)';
COMMENT ON COLUMN jurisdiction.name IS 'Human-readable jurisdiction name';
COMMENT ON COLUMN jurisdiction.weight IS 'Sorting weight (lower = more important)';

-- -----------------------------------------------------------
-- region
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS region (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id     VARCHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE region IS 'Regions from source (e.g. Moscow, Saint Petersburg)';
COMMENT ON COLUMN region.external_id IS 'Source-specific region identifier (GUID string)';
COMMENT ON COLUMN region.name IS 'Human-readable region name';
COMMENT ON COLUMN region.weight IS 'Sorting weight (lower = more important)';

-- -----------------------------------------------------------
-- topic
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS topic (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id     VARCHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

COMMENT ON TABLE topic IS 'Topics from source (e.g. Economy, Social Policy)';
COMMENT ON COLUMN topic.external_id IS 'Source-specific topic identifier (GUID string)';
COMMENT ON COLUMN topic.name IS 'Human-readable topic name';
COMMENT ON COLUMN topic.weight IS 'Sorting weight (lower = more important)';
