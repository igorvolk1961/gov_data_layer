"""Unit tests for QdrantStore topic/rubric collection methods.

Tests cover:
- ensure_topic_collection when disabled (no Qdrant)
- upsert_topic_vectors with empty and populated lists
- count_topics, delete_topic_collection
- delete_all_collections
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.index.qdrant_store import QdrantStore
from core.models.models import TopicPoint

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store() -> QdrantStore:
    """Create a disabled QdrantStore for testing (no actual Qdrant)."""
    return QdrantStore(disabled=True)


class TestQdrantStoreTopicMethods:
    """Tests for topic/rubric collection methods in QdrantStore."""

    @pytest.mark.asyncio
    async def test_ensure_topic_collection_disabled(self, store: QdrantStore) -> None:
        """ensure_topic_collection should be no-op when disabled."""
        await store.ensure_topic_collection()  # should not raise

    async def test_upsert_topic_vectors_empty(self, store: QdrantStore) -> None:
        """Upsert with empty list should be no-op."""
        await store.upsert_topic_vectors([])  # should not raise

    async def test_upsert_topic_vectors_disabled(self, store: QdrantStore) -> None:
        """Upsert with data should be no-op when disabled."""
        topics = [
            TopicPoint(id="labor-law", topic_id="uuid-1", name="Трудовое право"),
            TopicPoint(id="social", topic_id="uuid-2", name="Социальная защита"),
        ]
        await store.upsert_topic_vectors(topics)

    async def test_count_topics_disabled(self, store: QdrantStore) -> None:
        """count_topics should return 0 when disabled."""
        count = await store.count_topics()
        assert count == 0

    async def test_delete_topic_collection_disabled(self, store: QdrantStore) -> None:
        """delete_topic_collection should be no-op when disabled."""
        await store.delete_topic_collection()

    async def test_delete_all_collections_disabled(self, store: QdrantStore) -> None:
        """delete_all_collections should be no-op when disabled."""
        await store.delete_all_collections()

    async def test_upsert_skips_topics_without_embedding(self, store: QdrantStore) -> None:
        """Topics without embedding should be skipped."""
        topics = [
            TopicPoint(id="no-emb", topic_id="uuid-1", name="No Embedding"),
        ]
        await store.upsert_topic_vectors(topics)  # should not raise

    @patch("core.index.qdrant_store._HAS_QDRANT", True)
    async def test_ensure_topic_collection_creates_collection(self) -> None:
        """When qdrant-client is available, ensure_topic_collection should create."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        mock_client.create_collection = MagicMock()
        mock_client.create_payload_index = MagicMock()

        store = QdrantStore(host="localhost", port=6333, disabled=False)
        store._client = mock_client

        await store.ensure_topic_collection()
        mock_client.create_collection.assert_called_once()
        # Verify it creates 'topics' collection
        call_kwargs = mock_client.create_collection.call_args[1]
        assert call_kwargs["collection_name"] == "topics"

    @patch("core.index.qdrant_store._HAS_QDRANT", True)
    async def test_upsert_topic_vectors_with_embeddings(self) -> None:
        """Topics with embeddings should be upserted."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        mock_client.upsert = MagicMock()
        mock_client.create_collection = MagicMock()
        mock_client.create_payload_index = MagicMock()

        store = QdrantStore(host="localhost", port=6333, disabled=False)
        store._client = mock_client

        topics = [
            TopicPoint(
                id="labor-law",
                topic_id="uuid-1",
                name="Трудовое право",
                embedding=[0.1, 0.2, 0.3],
            ),
        ]
        await store.upsert_topic_vectors(topics)
        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args[1]
        assert call_kwargs["collection_name"] == "topics"
        assert len(call_kwargs["points"]) == 1
        import uuid

        point_id = call_kwargs["points"][0].id
        # Now point IDs are UUID v5 from external_id
        uuid.UUID(point_id)  # validate UUID format
        assert call_kwargs["points"][0].payload["external_id"] == "labor-law"

    @patch("core.index.qdrant_store._HAS_QDRANT", True)
    async def test_count_topics_with_client(self) -> None:
        """count_topics should delegate to Qdrant client."""
        from types import SimpleNamespace

        mock_count = MagicMock()
        mock_count.count = 5

        mock_topic_col = SimpleNamespace(name="topics")
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = [mock_topic_col]
        mock_client.count.return_value = mock_count

        store = QdrantStore(host="localhost", port=6333, disabled=False)
        store._client = mock_client

        count = await store.count_topics()
        assert count == 5
        mock_client.count.assert_called_once_with(collection_name="topics")

    @patch("core.index.qdrant_store._HAS_QDRANT", True)
    async def test_delete_topic_collection(self) -> None:
        """delete_topic_collection should delete the collection."""
        from types import SimpleNamespace

        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = [
            SimpleNamespace(name="topics"),
        ]
        mock_client.delete_collection = MagicMock()

        store = QdrantStore(host="localhost", port=6333, disabled=False)
        store._client = mock_client

        await store.delete_topic_collection()
        mock_client.delete_collection.assert_called_once_with("topics")

    @patch("core.index.qdrant_store._HAS_QDRANT", True)
    async def test_delete_all_collections(self) -> None:
        """delete_all_collections should delete both documents and topics."""
        from types import SimpleNamespace

        mock_doc = SimpleNamespace(name="documents")
        mock_topics = SimpleNamespace(name="topics")

        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = [mock_doc, mock_topics]
        mock_client.delete_collection = MagicMock()

        store = QdrantStore(host="localhost", port=6333, disabled=False)
        store._client = mock_client

        await store.delete_all_collections()
        assert mock_client.delete_collection.call_count == 2
        calls = [c[0][0] for c in mock_client.delete_collection.call_args_list]
        assert "documents" in calls
        assert "topics" in calls
