-- liquibase formatted sql

-- ============================================================
-- changeset v003-000: Drop unused document_organization table
-- ============================================================
-- The document_organization M:N junction table was created in v001-003
-- but never populated. The actual document→organization link is stored
-- directly in document.organization_id (VARCHAR) with a composite FK
-- to organization(source_id, external_id), added in v001-008.
--
-- This changeset removes the unused table.
-- ============================================================

DROP TABLE IF EXISTS document_organization CASCADE;

COMMENT ON TABLE document_organization IS NULL;
