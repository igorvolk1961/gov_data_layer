-- liquibase formatted sql

-- ============================================================
-- changeset v001-008: Rename document table columns to match OfficialDocument model
-- ============================================================
-- Приведение названий колонок таблицы document в соответствие
-- с полями канонической модели OfficialDocument:
--
--   abstract         → summary
--   effective_date   → valid_from
--   publication_date → publish_date
--   signing_date     → valid_to
--   doc_type_id      → document_type_id  (+ type change UUID→VARCHAR(36),
--                                          FK now uses composite key)
--   (new)            → organization_id   (VARCHAR(36), composite FK)
-- ============================================================

-- -----------------------------------------------------------
-- 1. Rename simple columns (same data type, same semantics)
-- -----------------------------------------------------------
ALTER TABLE document RENAME COLUMN abstract         TO summary;
ALTER TABLE document RENAME COLUMN effective_date   TO valid_from;
ALTER TABLE document RENAME COLUMN publication_date TO publish_date;
ALTER TABLE document RENAME COLUMN signing_date     TO valid_to;

-- -----------------------------------------------------------
-- 2. Rename indexes
-- -----------------------------------------------------------
ALTER INDEX idx_document_effective_date  RENAME TO idx_document_valid_from;
ALTER INDEX idx_document_publication_date RENAME TO idx_document_publish_date;

-- -----------------------------------------------------------
-- 3. Handle doc_type_id → document_type_id
--    Drop old FK, add new VARCHAR column, migrate data, drop old column
-- -----------------------------------------------------------
ALTER TABLE document
    DROP CONSTRAINT IF EXISTS document_doc_type_id_fkey;

-- Add new column with correct type
ALTER TABLE document
    ADD COLUMN document_type_id VARCHAR(36);

-- Migrate data from old doc_type_id UUID to source GUID
UPDATE document d
    SET document_type_id = dt.external_id
    FROM document_type dt
    WHERE dt.id = d.doc_type_id;

-- Drop old column
ALTER TABLE document DROP COLUMN doc_type_id;

-- Add composite FK
CREATE INDEX IF NOT EXISTS idx_document_document_type_id ON document(document_type_id);

ALTER TABLE document
    ADD CONSTRAINT fk_document_document_type
    FOREIGN KEY (source_id, document_type_id)
    REFERENCES document_type(source_id, external_id);

-- -----------------------------------------------------------
-- 4. Add organization_id column (new)
-- -----------------------------------------------------------
ALTER TABLE document
    ADD COLUMN organization_id VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_document_organization_id ON document(organization_id);

ALTER TABLE document
    ADD CONSTRAINT fk_document_organization
    FOREIGN KEY (source_id, organization_id)
    REFERENCES organization(source_id, external_id);

-- -----------------------------------------------------------
-- 5. Update comments
-- -----------------------------------------------------------
COMMENT ON COLUMN document.summary IS 'Document abstract/summary';
COMMENT ON COLUMN document.valid_from IS 'Date when the document comes into force';
COMMENT ON COLUMN document.publish_date IS 'Date of official publication';
COMMENT ON COLUMN document.valid_to IS 'Date when legal validity ends (null = indefinite)';
COMMENT ON COLUMN document.document_type_id IS 'Source-specific document type identifier (GUID), composite FK to document_type(source_id, external_id)';
COMMENT ON COLUMN document.organization_id IS 'Source-specific organization identifier (GUID), composite FK to organization(source_id, external_id)';
