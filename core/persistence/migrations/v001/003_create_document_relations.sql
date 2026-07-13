-- liquibase formatted sql

-- ============================================================
-- changeset v001-003: Create M:N junction tables
-- ============================================================
-- document_organization — links documents to organizations (many-to-many)
-- document_topic        — links documents to topics (many-to-many)
-- ============================================================

-- -----------------------------------------------------------
-- document_organization
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_organization (
    document_id     UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (document_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_document_organization_org_id ON document_organization(organization_id);

COMMENT ON TABLE document_organization IS 'Many-to-many link between documents and organizations';

-- -----------------------------------------------------------
-- document_topic
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_topic (
    document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    topic_id    UUID NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (document_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_document_topic_topic_id ON document_topic(topic_id);

COMMENT ON TABLE document_topic IS 'Many-to-many link between documents and topics';
