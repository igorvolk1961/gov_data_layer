-- liquibase formatted sql

-- ============================================================
-- changeset v001-007: Rename document.external_id to publish_id
-- ============================================================
-- Переименование колонки для соответствия канонической модели:
-- external_id → publish_id
-- ============================================================

ALTER TABLE document
    RENAME COLUMN external_id TO publish_id;

COMMENT ON COLUMN document.publish_id IS 'Source-specific document identifier (publish_id / eoNumber)';
