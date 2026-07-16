-- liquibase formatted sql

-- ============================================================
-- changeset v001-009: Recreate region as hierarchical, universal table
-- ============================================================
-- Replaces the flat, source-scoped region table with a hierarchical,
-- universal one (not tied to any data source), modeled after rubric.
-- ============================================================

-- 1. Create new hierarchical region table
CREATE TABLE IF NOT EXISTS region_new (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID        REFERENCES region_new(id) ON DELETE SET NULL,
    external_id     VARCHAR(36) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_region_new_parent_id ON region_new(parent_id);
CREATE INDEX IF NOT EXISTS idx_region_new_external_id ON region_new(external_id);

-- 2. Add trigram index for full-text search on name
CREATE INDEX IF NOT EXISTS idx_region_new_name_trgm ON region_new USING gin (name gin_trgm_ops);

-- 3. Migrate unique region names from old table
INSERT INTO region_new (external_id, name)
SELECT DISTINCT ON (r.name)
    r.external_id,
    r.name
FROM region r
ON CONFLICT (external_id) DO NOTHING;

-- 4. Add temporary column to link old region IDs to new ones
ALTER TABLE document ADD COLUMN IF NOT EXISTS region_new_id UUID;

UPDATE document d
SET region_new_id = rn.id
FROM region r
JOIN region_new rn ON rn.name = r.name
WHERE d.region_id = r.id;

-- 5. Drop old FK and old table
ALTER TABLE document DROP CONSTRAINT IF EXISTS fk_document_region;
DROP TABLE IF EXISTS region CASCADE;

-- 6. Rename new table to region
ALTER TABLE region_new RENAME TO region;

-- 7. Rename indexes
ALTER INDEX idx_region_new_parent_id RENAME TO idx_region_parent_id;
ALTER INDEX idx_region_new_external_id RENAME TO idx_region_external_id;
ALTER INDEX idx_region_new_name_trgm RENAME TO idx_region_name_trgm;

-- 8. Add FK from document to new region table
ALTER TABLE document
    ADD CONSTRAINT fk_document_region
    FOREIGN KEY (region_new_id) REFERENCES region(id);

-- 9. Rename column to region_id and drop temp
ALTER TABLE document RENAME COLUMN region_new_id TO region_id;

-- 10. Update region_id FK name
ALTER TABLE document
    DROP CONSTRAINT IF EXISTS fk_document_region,
    ADD CONSTRAINT fk_document_region
    FOREIGN KEY (region_id) REFERENCES region(id);

COMMENT ON TABLE region IS 'Universal hierarchical geographic regions (not tied to any data source). Modeled after rubric.';
COMMENT ON COLUMN region.parent_id IS 'Parent region for hierarchical structure (NULL for top-level)';
COMMENT ON COLUMN region.external_id IS 'Unique region identifier (code from state classifier)';
COMMENT ON COLUMN region.name IS 'Region name';
COMMENT ON COLUMN region.description IS 'Optional region description';
COMMENT ON COLUMN region.weight IS 'Sorting weight (lower = more important)';
