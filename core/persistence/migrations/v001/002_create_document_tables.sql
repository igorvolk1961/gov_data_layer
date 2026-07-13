-- liquibase formatted sql

-- ============================================================
-- changeset v001-002: Create document and document_section tables
-- ============================================================
-- document         — canonical model of an official document
-- document_section — sections/parts of a document (hierarchical,
--                    self-referencing via parent_id)
-- ============================================================

-- -----------------------------------------------------------
-- document
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id           UUID        NOT NULL REFERENCES data_source(id) ON DELETE CASCADE,
    external_id         VARCHAR(36) NOT NULL,
    document_number     VARCHAR(255),
    title               TEXT        NOT NULL,
    abstract            TEXT,
    effective_date      DATE,
    publication_date    DATE,
    signing_date        DATE,
    doc_type_id         UUID        REFERENCES document_type(id),
    jurisdiction_id     UUID        REFERENCES jurisdiction(id),
    region_id           UUID        REFERENCES region(id),
    meta                JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_document_source_id ON document(source_id);
CREATE INDEX IF NOT EXISTS idx_document_external_id ON document(external_id);
CREATE INDEX IF NOT EXISTS idx_document_doc_type_id ON document(doc_type_id);
CREATE INDEX IF NOT EXISTS idx_document_effective_date ON document(effective_date);
CREATE INDEX IF NOT EXISTS idx_document_publication_date ON document(publication_date);

COMMENT ON TABLE document IS 'Canonical model of an official document';
COMMENT ON COLUMN document.external_id IS 'Source-specific document identifier (GUID string)';
COMMENT ON COLUMN document.document_number IS 'Official document number (e.g. 123-FZ)';
COMMENT ON COLUMN document.title IS 'Document title';
COMMENT ON COLUMN document.abstract IS 'Document abstract/summary';
COMMENT ON COLUMN document.effective_date IS 'Date when the document comes into force';
COMMENT ON COLUMN document.publication_date IS 'Date of official publication';
COMMENT ON COLUMN document.signing_date IS 'Date of signing';
COMMENT ON COLUMN document.meta IS 'Additional metadata as JSONB';

-- -----------------------------------------------------------
-- document_section
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_section (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             UUID        NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    parent_id               UUID        REFERENCES document_section(id) ON DELETE SET NULL,
    external_id             VARCHAR(36),
    title                   TEXT        NOT NULL,
    heading                 TEXT,
    text                    TEXT,
    ordinal                 INTEGER     NOT NULL DEFAULT 0,
    level                   INTEGER     NOT NULL DEFAULT 0,
    is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,
    deleted_by_document_id  UUID        REFERENCES document(id) ON DELETE SET NULL,
    delete_effective_date   DATE,
    is_modified             BOOLEAN     NOT NULL DEFAULT FALSE,
    modified_effective_date DATE,
    meta                    JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_section_document_id ON document_section(document_id);
CREATE INDEX IF NOT EXISTS idx_document_section_parent_id ON document_section(parent_id);
CREATE INDEX IF NOT EXISTS idx_document_section_external_id ON document_section(external_id);
CREATE INDEX IF NOT EXISTS idx_document_section_deleted ON document_section(is_deleted) WHERE is_deleted = TRUE;
CREATE INDEX IF NOT EXISTS idx_document_section_modified ON document_section(is_modified) WHERE is_modified = TRUE;

COMMENT ON TABLE document_section IS 'Sections/parts of a document (hierarchical, self-referencing via parent_id)';
COMMENT ON COLUMN document_section.parent_id IS 'Parent section for hierarchical structure (NULL for top-level)';
COMMENT ON COLUMN document_section.external_id IS 'Source-specific section identifier (GUID string)';
COMMENT ON COLUMN document_section.title IS 'Section title';
COMMENT ON COLUMN document_section.heading IS 'Section heading (may differ from title)';
COMMENT ON COLUMN document_section.text IS 'Section text content';
COMMENT ON COLUMN document_section.ordinal IS 'Ordering within parent (0-based)';
COMMENT ON COLUMN document_section.level IS 'Hierarchy depth (0 = top-level)';
COMMENT ON COLUMN document_section.is_deleted IS 'Flag indicating this section has been deleted';
COMMENT ON COLUMN document_section.deleted_by_document_id IS 'Document that caused this deletion';
COMMENT ON COLUMN document_section.delete_effective_date IS 'Optional date when deletion takes effect (defaults to deleting document effective_date)';
COMMENT ON COLUMN document_section.is_modified IS 'Flag indicating this section has been modified';
COMMENT ON COLUMN document_section.modified_effective_date IS 'Optional date when modification takes effect (defaults to modifying document effective_date)';
