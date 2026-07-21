-- liquibase formatted sql

-- ============================================================
-- changeset v004-001: Add jurisdiction_id and region_id to organization
-- ============================================================
-- Adds FK columns to the organization table linking to the
-- jurisdiction and region reference tables.
-- ============================================================

ALTER TABLE organization
    ADD COLUMN jurisdiction_id UUID REFERENCES jurisdiction(id),
    ADD COLUMN region_id UUID REFERENCES region(id);

COMMENT ON COLUMN organization.jurisdiction_id IS 'FK → jurisdiction.id — jurisdiction scope of this organization (federal/regional/international)';
COMMENT ON COLUMN organization.region_id IS 'FK → region.id — geographic region of this organization (set for regional bodies, null for federal/international)';
