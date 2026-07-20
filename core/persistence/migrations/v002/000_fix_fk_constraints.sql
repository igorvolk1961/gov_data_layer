-- liquibase formatted sql

-- ============================================================
-- changeset v002-000: Fix FK constraints — RESTRICT for reference tables, NO ACTION for document_section
-- ============================================================
-- Изменяет ON DELETE поведение внешних ключей:
--   - document → region, jurisdiction, document_type, organization → RESTRICT
--   - document_section → parent_id, deleted_by_document_id → NO ACTION
-- ============================================================

-- -----------------------------------------------------------
-- 1. document → region — RESTRICT
-- -----------------------------------------------------------
ALTER TABLE document DROP CONSTRAINT IF EXISTS fk_document_region;
ALTER TABLE document DROP CONSTRAINT IF EXISTS document_region_id_fkey;
ALTER TABLE document
    ADD CONSTRAINT fk_document_region
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE RESTRICT;

-- -----------------------------------------------------------
-- 2. document → jurisdiction — RESTRICT
-- -----------------------------------------------------------
ALTER TABLE document DROP CONSTRAINT IF EXISTS fk_document_jurisdiction;
ALTER TABLE document DROP CONSTRAINT IF EXISTS document_jurisdiction_id_fkey;
ALTER TABLE document
    ADD CONSTRAINT fk_document_jurisdiction
    FOREIGN KEY (jurisdiction_id) REFERENCES jurisdiction(id) ON DELETE RESTRICT;

-- -----------------------------------------------------------
-- 3. document → document_type — RESTRICT
-- -----------------------------------------------------------
ALTER TABLE document DROP CONSTRAINT IF EXISTS fk_document_document_type;
ALTER TABLE document
    ADD CONSTRAINT fk_document_document_type
    FOREIGN KEY (source_id, document_type_id)
    REFERENCES document_type(source_id, external_id) ON DELETE RESTRICT;

-- -----------------------------------------------------------
-- 4. document → organization — RESTRICT
-- -----------------------------------------------------------
ALTER TABLE document DROP CONSTRAINT IF EXISTS fk_document_organization;
ALTER TABLE document
    ADD CONSTRAINT fk_document_organization
    FOREIGN KEY (source_id, organization_id)
    REFERENCES organization(source_id, external_id) ON DELETE RESTRICT;

-- -----------------------------------------------------------
-- 5. document_section → parent_id (self-ref) — NO ACTION
-- -----------------------------------------------------------
ALTER TABLE document_section DROP CONSTRAINT IF EXISTS document_section_parent_id_fkey;
ALTER TABLE document_section DROP CONSTRAINT IF EXISTS fk_document_section_parent;
ALTER TABLE document_section
    ADD CONSTRAINT fk_document_section_parent
    FOREIGN KEY (parent_id) REFERENCES document_section(id);

-- -----------------------------------------------------------
-- 6. document_section → deleted_by_document_id — NO ACTION
-- -----------------------------------------------------------
ALTER TABLE document_section DROP CONSTRAINT IF EXISTS document_section_deleted_by_document_id_fkey;
ALTER TABLE document_section DROP CONSTRAINT IF EXISTS fk_document_section_deleted_by;
ALTER TABLE document_section
    ADD CONSTRAINT fk_document_section_deleted_by
    FOREIGN KEY (deleted_by_document_id) REFERENCES document(id);
