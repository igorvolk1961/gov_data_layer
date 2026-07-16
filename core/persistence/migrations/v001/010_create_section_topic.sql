-- 010: Create section_topic junction table
-- Links document_sections to topics (rubrics) with a relevance score.
-- Enables filtering search results by topic + section context.

CREATE TABLE IF NOT EXISTS section_topic (
    section_id UUID NOT NULL REFERENCES document_section(id) ON DELETE CASCADE,
    topic_id   UUID NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    score      REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (section_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_section_topic_section_id ON section_topic(section_id);
CREATE INDEX IF NOT EXISTS idx_section_topic_topic_id   ON section_topic(topic_id);
