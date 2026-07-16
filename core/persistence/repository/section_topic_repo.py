"""SectionTopicRepository — CRUD for the section_topic junction table.

Links document_sections to topics (rubrics) with a relevance score.
Enables filtering search results by topic + section context.
"""

from __future__ import annotations

from typing import Any

from core.persistence.db_client import DatabaseClient

_ST_BATCH_SIZE = 500


class SectionTopicRepository:
    """Repository for the section_topic junction table."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    async def link_section_to_topic(
        self,
        section_id: str,
        topic_id: str,
        score: float = 1.0,
    ) -> None:
        """Insert a single section-topic link (upsert on conflict).

        Args:
            section_id: UUID of the document_section record.
            topic_id: UUID of the topic record.
            score: Relevance score (0.0-1.0).
        """
        await self._db.execute(
            """
            INSERT INTO section_topic (section_id, topic_id, score)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (section_id, topic_id)
            DO UPDATE SET score = GREATEST(section_topic.score, $3)
            """,
            section_id,
            topic_id,
            score,
        )

    async def batch_link(
        self,
        links: list[dict[str, Any]],
    ) -> None:
        """Batch-insert section-topic links.

        Each link dict must have keys: section_id, topic_id, score.

        Args:
            links: List of link dicts to insert.
        """
        if not links:
            return

        for i in range(0, len(links), _ST_BATCH_SIZE):
            batch = links[i : i + _ST_BATCH_SIZE]
            values: list[str] = []
            params: list[Any] = []
            for j, link in enumerate(batch):
                idx = j * 3
                values.append(f"(${idx + 1}::uuid, ${idx + 2}::uuid, ${idx + 3})")
                params.append(link["section_id"])
                params.append(link["topic_id"])
                params.append(link.get("score", 1.0))

            sql = f"""
                INSERT INTO section_topic (section_id, topic_id, score)
                VALUES {", ".join(values)}
                ON CONFLICT (section_id, topic_id)
                DO UPDATE SET score = GREATEST(section_topic.score, EXCLUDED.score)
            """
            await self._db.execute(sql, *params)

    async def get_section_topics(
        self,
        section_id: str,
    ) -> list[dict[str, Any]]:
        """Get all topics linked to a section.

        Args:
            section_id: UUID of the document_section record.

        Returns:
            List of dicts with keys: topic_id, topic_name, score.
        """
        rows = await self._db.fetch(
            """
            SELECT st.topic_id, t.name AS topic_name, st.score
            FROM section_topic st
            JOIN topic t ON t.id = st.topic_id
            WHERE st.section_id = $1::uuid
            ORDER BY st.score DESC
            """,
            section_id,
        )
        return [dict(r) for r in rows]

    async def get_document_topics(
        self,
        document_uuid: str,
    ) -> list[dict[str, Any]]:
        """Get all topics linked to any section of a document.

        Args:
            document_uuid: UUID of the document record.

        Returns:
            List of dicts with keys: topic_id, topic_name, score (max).
        """
        rows = await self._db.fetch(
            """
            SELECT st.topic_id, t.name AS topic_name, MAX(st.score) AS score
            FROM section_topic st
            JOIN document_section ds ON ds.id = st.section_id
            JOIN topic t ON t.id = st.topic_id
            WHERE ds.document_id = $1::uuid
            GROUP BY st.topic_id, t.name
            ORDER BY score DESC
            """,
            document_uuid,
        )
        return [dict(r) for r in rows]

    async def count_links(self) -> int:
        """Get total number of section-topic links."""
        row = await self._db.fetchval("SELECT COUNT(*) FROM section_topic")
        return row or 0

    async def delete_by_document(self, document_uuid: str) -> None:
        """Delete all section-topic links for a document.

        Args:
            document_uuid: UUID of the document record.
        """
        await self._db.execute(
            """
            DELETE FROM section_topic
            WHERE section_id IN (
                SELECT id FROM document_section WHERE document_id = $1::uuid
            )
            """,
            document_uuid,
        )
