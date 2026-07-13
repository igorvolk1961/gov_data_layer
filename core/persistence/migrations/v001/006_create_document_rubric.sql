-- liquibase formatted sql

-- ============================================================
-- changeset v001-006: Create document_rubric M:N junction table
-- ============================================================
-- Links documents to rubrics (many-to-many).
-- Rubrics are universal (not tied to any data source).
-- ============================================================

CREATE TABLE IF NOT EXISTS document_rubric (
    document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    rubric_id   UUID NOT NULL REFERENCES rubric(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (document_id, rubric_id)
);

CREATE INDEX IF NOT EXISTS idx_document_rubric_rubric_id ON document_rubric(rubric_id);

COMMENT ON TABLE document_rubric IS 'Many-to-many link between documents and universal rubrics';
