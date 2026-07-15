"""Embedder — text embedding using sentence-transformers.

Runs the model in a thread pool executor since sentence-transformers is blocking.
Model name and vector size are configurable via config.yaml → EmbeddingConfig.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_HAS_SENTENCE_TRANSFORMERS = False
try:
    from sentence_transformers import SentenceTransformer

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    logger.warning("sentence-transformers not installed — embedding will use fallback")


class Embedder:
    """Text embedder using sentence-transformers.

    Model and vector size are read from AppConfig → EmbeddingConfig.
    Falls back to identity embeddings if sentence-transformers is not available
    (for testing/stub purposes).
    """

    def __init__(
        self,
        model_name: str | None = None,
        vector_size: int | None = None,
    ) -> None:
        """Initialize the embedder.

        Args:
            model_name: Sentence-transformers model name.
                        If None, reads from AppConfig (config.yaml → embedding.model).
                        Default: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2".
            vector_size: Expected embedding dimension.
                         If None, reads from AppConfig (config.yaml → embedding.vector_size).
                         Default: 384 (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
        """
        if model_name is None or vector_size is None:
            try:
                from core.api.app_config import get_config

                cfg = get_config()
                if model_name is None:
                    model_name = cfg.embedding.model
                if vector_size is None:
                    vector_size = cfg.embedding.vector_size
            except Exception:
                if model_name is None:
                    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                if vector_size is None:
                    vector_size = 384

        self._model_name = model_name
        self._model: Any = None
        self._vector_size: int = vector_size

        if _HAS_SENTENCE_TRANSFORMERS:
            logger.info("Embedder will load model '%s' on first use", model_name)
        else:
            logger.warning(
                "sentence-transformers not available — "
                "Embedder will return zero vectors (stub mode)"
            )

    async def _ensure_model(self) -> None:
        """Lazy-load the model (blocking, runs in thread pool)."""
        if self._model is not None:
            return
        if not _HAS_SENTENCE_TRANSFORMERS:
            return

        loop = asyncio.get_event_loop()

        def _load() -> Any:
            logger.info("Loading embedding model '%s'...", self._model_name)
            model = SentenceTransformer(self._model_name)
            logger.info(
                "Model '%s' loaded (vector size: %d)",
                self._model_name,
                model.get_embedding_dimension(),
            )
            return model

        self._model = await loop.run_in_executor(None, _load)
        if hasattr(self._model, "get_embedding_dimension"):
            self._vector_size = self._model.get_embedding_dimension()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (list of floats).
        """
        if not texts:
            return []

        await self._ensure_model()

        if self._model is None:
            # Stub mode: return zero vectors
            return [[0.0] * self._vector_size for _ in texts]

        loop = asyncio.get_event_loop()

        def _encode() -> list[list[float]]:
            embeddings = self._model.encode(texts, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]

        return await loop.run_in_executor(None, _encode)

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string (for search).

        Args:
            query: Search query text.

        Returns:
            Single embedding vector.
        """
        result = await self.embed([query])
        return result[0] if result else [0.0] * self._vector_size

    @property
    def vector_size(self) -> int:
        """Get the embedding vector dimension."""
        return self._vector_size


__all__ = [
    "Embedder",
]
