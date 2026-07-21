"""REST API server — тонкий адаптер поверх ODLServiceProtocol.

Предоставляет OpenAPI-совместимый REST API для традиционных HTTP-клиентов.
Swagger UI автоматически доступен на /docs.

Эндпоинты:
- POST /api/v1/search — поиск документов
- GET  /api/v1/documents/{source_id} — полная карточка документа
- GET  /api/v1/topics — иерархический рубрикатор
- GET  /api/v1/documents/{document_id}/toc — оглавление документа
- GET  /health — healthcheck
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from core.cache import CacheClient
from core.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from core.models.models import SearchContext
from core.observability import get_tracer
from core.persistence import DatabaseClient


class SearchRequest(BaseModel):
    """Request body for POST /api/v1/search."""

    query: str = Field(min_length=1, description="Search query text")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    limit: int = Field(default=10, ge=1, le=100, description="Max results to return")
    region: str | None = Field(default=None, description="Region filter")
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score threshold (cosine similarity). "
        "Results below this threshold are excluded. "
        "None = no filtering (agent decides policy).",
    )


if TYPE_CHECKING:
    from core.index.qdrant_store import QdrantStore
    from core.odl_service_protocol import ODLServiceProtocol


class _TracingASGIMiddleware:
    """ASGI middleware that traces HTTP requests.

    Uses raw ASGI interface to avoid BaseHTTPMiddleware body-streaming issues
    with SSE (Server-Sent Events) used by the MCP endpoint.
    SSE paths (/mcp) are passed through without tracing.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._tracer = get_tracer()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip tracing for SSE/MCP paths
        path = scope.get("path", "")
        if path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        from urllib.parse import parse_qsl

        trace_name = f"{scope['method']} {path}"
        with self._tracer.trace(trace_name, method=scope["method"], path=path) as span:
            span.set_input(
                {
                    "method": scope["method"],
                    "path": path,
                    "query_params": dict(parse_qsl(scope.get("query_string", b"").decode())),
                }
            )

            # Wrap send to capture status_code
            status_code = [200]

            from collections.abc import MutableMapping

            async def _send(message: MutableMapping[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    status_code[0] = message.get("status", 200)
                await send(message)

            try:
                await self.app(scope, receive, _send)
            except asyncio.CancelledError:
                span.set_error(asyncio.CancelledError("Request cancelled"))
                raise
            except Exception as e:
                span.set_error(e)
                raise
            finally:
                span.set_output({"status_code": status_code[0]})
                if status_code[0] >= 500:
                    span.set_error(Exception(f"HTTP {status_code[0]}"))


def _add_tracing_middleware(app: FastAPI) -> None:
    """Add ASGI tracing middleware that wraps each request in a tracer span.

    Uses raw ASGI middleware instead of @app.middleware("http") to avoid
    BaseHTTPMiddleware body-streaming issues with SSE (MCP endpoint).
    """
    app.add_middleware(_TracingASGIMiddleware)


def create_app(
    service: ODLServiceProtocol,
    cache: CacheClient | None = None,
    db: DatabaseClient | None = None,
    qdrant: QdrantStore | None = None,
) -> FastAPI:
    """Создать FastAPI-приложение с внедрённым ODLService.

    Args:
        service: Реализация ODLServiceProtocol (заглушка или настоящий сервис).
        cache: Опциональный CacheClient для отчёта о состоянии Redis.
        db: Опциональный DatabaseClient для отчёта о состоянии PostgreSQL.
        qdrant: Опциональный QdrantStore для отчёта о состоянии Qdrant.

    Returns:
        Настроенное FastAPI-приложение.
    """
    app = FastAPI(
        title="Official Data Layer API",
        description="API для поиска и получения официальных документов "
        "(государственные и социальные тематики). "
        "Swagger UI для интерактивного тестирования.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Add tracing middleware
    _add_tracing_middleware(app)

    # ------------------------------------------------------------------
    # Healthcheck
    # ------------------------------------------------------------------
    @app.get("/health")
    async def health() -> JSONResponse:
        """Проверка работоспособности сервиса."""
        redis_status = "connected" if (cache and cache.available) else "unavailable"
        db_status = "connected" if (db and db.available) else "unavailable"

        # Qdrant health check
        qdrant_status = "unavailable"
        if qdrant is not None:
            qdrant_ok = await qdrant.check_health()
            qdrant_status = "connected" if qdrant_ok else "unavailable"

        # LangFuse health check (via tracer.check_health — performs auth_check for LangFuseTracer,
        # returns False for FileFallbackTracer since LangFuse itself is not available)
        langfuse_status = "unavailable"
        tracer = get_tracer()
        if tracer is not None:
            langfuse_ok = tracer.check_health()
            langfuse_status = "connected" if langfuse_ok else "unavailable"

        return JSONResponse(
            content={
                "status": "ok",
                "redis": redis_status,
                "database": db_status,
                "qdrant": qdrant_status,
                "langfuse": langfuse_status,
            }
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    @app.post("/api/v1/search")
    async def search_documents(
        body: SearchRequest,
    ) -> JSONResponse:
        """Поиск документов по запросу.

        Args:
            body: Search request with query and optional filters.

        Returns:
            SearchResponse с результатами поиска.
        """
        try:
            context = SearchContext(
                offset=body.offset,
                max_results=body.limit,
                region=body.region,
                score_threshold=body.score_threshold,
            )
            response = await service.search_documents(body.query, context)
            return JSONResponse(
                content=response.model_dump(mode="json"),
            )
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        except SourceUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None

    # ------------------------------------------------------------------
    # Document detail
    # ------------------------------------------------------------------
    @app.get("/api/v1/documents/{source_id}")
    async def get_document_detail(
        source_id: str,
        query: str | None = None,
        region: str | None = None,
        score_threshold: float | None = None,
        max_citation_length: int = 2000,
        max_chunks: int = 5,
    ) -> JSONResponse:
        """Получить полную карточку документа.

        Args:
            source_id: Идентификатор документа в источнике
                (формат `{source_id}-{publish_id}`, как возвращает search).
            query: Опциональный поисковый запрос для фильтрации цитат.
            region: Опциональный фильтр по региону.
            topic: Опциональный фильтр по теме.
            score_threshold: Минимальный порог релевантности (0.0-1.0).
            max_citation_length: Максимальная суммарная длина цитат.

        Returns:
            DocumentDetail — полная карточка с текстом и цитатами.
        """
        try:
            ctx = SearchContext(
                region=region,
                score_threshold=score_threshold,
                max_results=max_chunks,
            )
            detail = await service.get_document_detail(
                source_id=source_id,
                query=query,
                context=ctx if (query or region or score_threshold is not None) else None,
                max_citation_length=max_citation_length,
            )
            return JSONResponse(content=detail.model_dump(mode="json"))
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except SourceUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None

    # ------------------------------------------------------------------
    # Topics (rubricator)
    # ------------------------------------------------------------------
    @app.get("/api/v1/topics")
    async def list_topics(
        parent_id: str | None = None,
        query: str = "",
    ) -> JSONResponse:
        """Просмотр иерархического рубрикатора.

        Args:
            parent_id: ID родительской рубрики. None = корневые рубрики.
            query: Опциональный поисковый запрос для фильтрации рубрик.

        Returns:
            Список узлов рубрикатора.
        """
        try:
            topics = await service.list_topics(parent_id=parent_id, query=query)
            return JSONResponse(
                content=[t.model_dump(mode="json") for t in topics],
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except SourceUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None

    # ------------------------------------------------------------------
    # Table of contents
    # ------------------------------------------------------------------
    @app.get("/api/v1/documents/{document_id}/toc")
    async def get_toc(
        document_id: str,
        parent_section_id: str | None = None,
        query: str = "",
    ) -> JSONResponse:
        """Получить оглавление документа.

        Args:
            document_id: ID документа.
            parent_section_id: ID родительского раздела. None = корневые разделы.
            query: Опциональный поисковый запрос для фильтрации разделов.

        Returns:
            Список узлов оглавления.
        """
        try:
            toc = await service.get_toc(
                document_id=document_id,
                parent_section_id=parent_section_id,
                query=query,
            )
            return JSONResponse(
                content=[t.model_dump(mode="json") for t in toc],
            )
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None

    # ------------------------------------------------------------------
    # Admin / Verification endpoints
    # ------------------------------------------------------------------
    @app.get("/api/v1/admin/reference-counts")
    async def admin_reference_counts() -> JSONResponse:
        """Get counts of all reference tables."""
        counts = await service.admin_get_reference_counts()
        return JSONResponse(content=counts.model_dump(mode="json"))

    @app.get("/api/v1/admin/qdrant/collections")
    async def admin_qdrant_status() -> JSONResponse:
        """Get Qdrant collections status."""
        status = await service.admin_get_qdrant_status()
        return JSONResponse(content=status.model_dump(mode="json"))

    @app.get("/api/v1/admin/documents/{publish_id}/status")
    async def admin_document_status(publish_id: str) -> JSONResponse:
        """Get full status of a document."""
        status = await service.admin_get_document_status(publish_id)
        return JSONResponse(content=status.model_dump(mode="json"))

    return app


__all__ = [
    "create_app",
]
