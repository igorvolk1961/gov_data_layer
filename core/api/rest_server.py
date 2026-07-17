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
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

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
    topic: str | None = Field(default=None, description="Topic filter")
    score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score threshold (cosine similarity). "
        "Results below this threshold are excluded. "
        "None = no filtering (agent decides policy).",
    )


if TYPE_CHECKING:
    from core.odl_service_protocol import ODLServiceProtocol

if TYPE_CHECKING:
    pass


def _add_tracing_middleware(app: FastAPI) -> None:
    """Add tracing middleware that wraps each request in a tracer span.

    Uses the global Tracer (configured via core.observability.configure()).
    Each HTTP request gets a trace with method, path, and status code tags.
    """
    tracer = get_tracer()

    @app.middleware("http")
    async def trace_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_name = f"{request.method} {request.url.path}"
        with tracer.trace(trace_name, method=request.method, path=request.url.path) as span:
            span.set_input(
                {
                    "method": request.method,
                    "path": str(request.url.path),
                    "query_params": dict(request.query_params),
                }
            )
            try:
                response: Response = await call_next(request)
                span.set_output(
                    {
                        "status_code": response.status_code,
                    }
                )
                if response.status_code >= 500:
                    span.set_error(Exception(f"HTTP {response.status_code}"))
                return response
            except asyncio.CancelledError:
                span.set_error(asyncio.CancelledError("Request cancelled"))
                raise
            except Exception as e:
                span.set_error(e)
                raise


def create_app(
    service: ODLServiceProtocol,
    cache: CacheClient | None = None,
    db: DatabaseClient | None = None,
) -> FastAPI:
    """Создать FastAPI-приложение с внедрённым ODLService.

    Args:
        service: Реализация ODLServiceProtocol (заглушка или настоящий сервис).
        cache: Опциональный CacheClient для отчёта о состоянии Redis.
        db: Опциональный DatabaseClient для отчёта о состоянии PostgreSQL.

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
        return JSONResponse(
            content={
                "status": "ok",
                "redis": redis_status,
                "database": db_status,
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
                topic=body.topic,
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
    async def get_document_detail(source_id: str) -> JSONResponse:
        """Получить полную карточку документа.

        Args:
            source_id: Идентификатор документа в источнике.

        Returns:
            DocumentDetail — полная карточка с текстом и цитатами.
        """
        try:
            detail = await service.get_document_detail(source_id)
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
