-- liquibase formatted sql

-- ============================================================
-- changeset v001-005: Create rubric table
-- ============================================================
-- rubric — hierarchical, universal classification rubrics
--           NOT tied to any data source (no source_id FK).
--           Self-referencing via parent_id for hierarchy.
-- ============================================================

CREATE TABLE IF NOT EXISTS rubric (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID        REFERENCES rubric(id) ON DELETE SET NULL,
    external_id     VARCHAR(36) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    weight          INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rubric_parent_id ON rubric(parent_id);
CREATE INDEX IF NOT EXISTS idx_rubric_external_id ON rubric(external_id);

COMMENT ON TABLE rubric IS 'Universal hierarchical classification rubrics (not tied to any data source)';
COMMENT ON COLUMN rubric.parent_id IS 'Parent rubric for hierarchical structure (NULL for top-level)';
COMMENT ON COLUMN rubric.external_id IS 'Unique rubric identifier (GUID string)';
COMMENT ON COLUMN rubric.name IS 'Rubric name';
COMMENT ON COLUMN rubric.description IS 'Optional rubric description';
COMMENT ON COLUMN rubric.weight IS 'Sorting weight (lower = more important)';
