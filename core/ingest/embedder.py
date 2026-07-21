"""Embedder — text embedding using sentence-transformers.

Runs the model in a thread pool executor since sentence-transformers is blocking.
Model name and vector size are configurable via config.yaml → EmbeddingConfig.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from core.observability import get_tracer

_HAS_SENTENCE_TRANSFORMERS = False
try:
    from sentence_transformers import SentenceTransformer

    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass  # handled in __init__


def _log_tracer(level: str, name: str, **tags: Any) -> None:
    """Log a message through the tracer (single-point root span)."""
    with contextlib.suppress(Exception):
        _t = get_tracer().trace(name, **tags)
        _t.__enter__()
        _t._data.level = level
        _t.__exit__(None, None, None)


class Embedder:
    """Text embedder using sentence-transformers."""

    def __init__(
        self,
        model_name: str | None = None,
        vector_size: int | None = None,
    ) -> None:
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
            _log_tracer("INFO", "embedder.init", model=model_name)
        else:
            _log_tracer("WARN", "embedder.stub")

    async def _ensure_model(self) -> None:
        """Lazy-load the model (blocking, runs in thread pool)."""
        if self._model is not None:
            return
        if not _HAS_SENTENCE_TRANSFORMERS:
            return

        loop = asyncio.get_event_loop()

        def _load() -> Any:
            _log_tracer("INFO", "embedder.load", model=self._model_name)
            model = SentenceTransformer(self._model_name)
            _log_tracer("INFO", "embedder.loaded", vector_size=str(model.get_embedding_dimension()))
            return model

        self._model = await loop.run_in_executor(None, _load)
        if hasattr(self._model, "get_embedding_dimension"):
            self._vector_size = self._model.get_embedding_dimension()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        await self._ensure_model()
        if self._model is None:
            return [[0.0] * self._vector_size for _ in texts]
        loop = asyncio.get_event_loop()

        def _encode() -> list[list[float]]:
            embeddings = self._model.encode(texts, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]

        return await loop.run_in_executor(None, _encode)

    async def embed_query(self, query: str) -> list[float]:
        result = await self.embed([query])
        return result[0] if result else [0.0] * self._vector_size

    @property
    def vector_size(self) -> int:
        return self._vector_size


__all__ = [
    "Embedder",
]
