-- liquibase formatted sql

-- ============================================================
-- changeset v001-004: Create change tracking tables
-- ============================================================
-- document_section_modification — M:N link between modified sections
--                                 and the documents that modified them
-- document_revocation          — 1:M link between a document and
--                                 the documents it fully revokes
-- ============================================================

-- -----------------------------------------------------------
-- document_section_modification
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_section_modification (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id          UUID        NOT NULL REFERENCES document_section(id) ON DELETE CASCADE,
    modifying_document_id UUID      NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    effective_date      DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (section_id, modifying_document_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_section_mod_section_id ON document_section_modification(section_id);
CREATE INDEX IF NOT EXISTS idx_doc_section_mod_doc_id ON document_section_modification(modifying_document_id);

COMMENT ON TABLE document_section_modification IS 'Many-to-many link between modified sections and the documents that modified them';
COMMENT ON COLUMN document_section_modification.effective_date IS 'Optional date when modification takes effect (defaults to modifying document effective_date)';

-- -----------------------------------------------------------
-- document_revocation
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_revocation (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    revoking_document_id    UUID        NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    revoked_document_id     UUID        NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    effective_date          DATE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (revoking_document_id, revoked_document_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_revocation_revoking ON document_revocation(revoking_document_id);
CREATE INDEX IF NOT EXISTS idx_doc_revocation_revoked ON document_revocation(revoked_document_id);

COMMENT ON TABLE document_revocation IS 'One-to-many link between a document and the documents it fully revokes';
COMMENT ON COLUMN document_revocation.effective_date IS 'Optional date when revocation takes effect (defaults to revoking document effective_date)';
