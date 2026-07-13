"""PravoClient — HTTP-клиент к API publication.pravo.gov.ru.

Предоставляет методы для работы с REST API портала pravo.gov.ru:
- get_public_blocks — получение блоков публикации
- get_categories — получение категорий
- get_signatory_authorities — получение органов власти
- get_document_types — получение видов документов
- search_documents — поиск документов с фильтрами
- get_document — получение деталей документа
- download_pdf — скачивание PDF документа

Включает circuit breaker для защиты от недоступности API.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx

from adapters.base.circuit_breaker import CircuitBreaker, CircuitState
from core.errors import SourceUnavailableError
from core.observability.logger import get_logger

if TYPE_CHECKING:
    from core.observability.tracer import Tracer

logger = get_logger(__name__)

# Default connection pool limits
_DEFAULT_LIMITS = httpx.Limits(
    max_connections=10,
    max_keepalive_connections=5,
)

# Base URL for pravo.gov.ru API
_BASE_URL = "http://publication.pravo.gov.ru"

# API endpoint paths
_PUBLIC_BLOCKS_PATH = "/api/PublicBlocks"
_CATEGORIES_PATH = "/api/Categories"
_SIGNATORY_AUTHORITIES_PATH = "/api/SignatoryAuthorities"
_DOCUMENT_TYPES_PATH = "/api/DocumentTypes"
_DOCUMENTS_PATH = "/api/Documents"
_DOCUMENT_PATH = "/api/Document"
_DOCUMENT_PDF_PATH = "/api/Document/Pdf"

# Non-retryable HTTP status codes
_NON_RETRYABLE_STATUSES = {400, 401, 403, 404, 405}

# Circuit breaker defaults
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_RECOVERY_TIMEOUT = 30.0


class PravoClient:
    """HTTP-клиент к API publication.pravo.gov.ru.

    Предоставляет методы для всех REST-endpoint'ов API pravo.gov.ru.
    Использует httpx.AsyncClient с retry (3 попытки), таймаутами (30s)
    и rate limiting.
    """

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        """Инициализация PravoClient.

        Args:
            base_url: Базовый URL API.
            timeout: Таймаут HTTP-запроса в секундах.
            max_retries: Количество попыток при ошибке HTTP.
            client: Внешний HTTP-клиент (для тестов). Если None, создаётся внутренний.
            tracer: Опциональный tracer для observability.
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client
        self._owns_client = client is None
        self._tracer: Tracer | None = tracer
        self._circuit_breaker = CircuitBreaker(
            name="pravo",
            failure_threshold=_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=_CIRCUIT_RECOVERY_TIMEOUT,
        )

    @property
    def tracer(self) -> Tracer:
        """Lazy tracer — defer get_tracer() until first use."""
        if self._tracer is None:
            from core.observability.tracer import get_tracer

            self._tracer = get_tracer()
        return self._tracer

    @property
    def circuit_state(self) -> CircuitState:
        """Current circuit breaker state for the pravo API."""
        return self._circuit_breaker.state

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the circuit breaker instance (for observability)."""
        return self._circuit_breaker

    async def check_health(self) -> bool:
        """Probe the pravo API to check if it's reachable.

        Makes a lightweight request to /api/PublicBlocks (root level).
        On success, records a success in the circuit breaker.
        On failure, records a failure.

        Returns:
            True if the API is reachable, False otherwise.
        """
        try:
            await self.get_public_blocks()
            self._circuit_breaker.record_success()
            return True
        except SourceUnavailableError:
            self._circuit_breaker.record_failure()
            return False

    def _get_http_client(self) -> httpx.AsyncClient:
        """Получить HTTP-клиент (создать, если ещё не создан)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=_DEFAULT_LIMITS,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        span_name: str = "pravo.request",
    ) -> dict[str, Any] | bytes:
        """Выполнить HTTP-запрос к API с retry и observability.

        Args:
            method: HTTP-метод (GET, POST).
            path: Путь к endpoint (например, '/api/Documents').
            params: Query-параметры.
            json_data: JSON-тело запроса.
            span_name: Имя span для tracer.

        Returns:
            JSON-ответ (dict) или сырые байты (для PDF).

        Raises:
            SourceUnavailableError: API недоступен.
        """
        url = f"{self._base_url}{path}"

        # Circuit breaker check — fast-fail if circuit is open
        if not self._circuit_breaker.can_request():
            circuit_state = self._circuit_breaker.state.value
            error_msg = (
                f"API request blocked by circuit breaker "
                f"(state={circuit_state}, failures={self._circuit_breaker.failure_count})"
            )
            logger.warning("Circuit breaker blocked request to %s (state=%s)", url, circuit_state)
            raise SourceUnavailableError(error_msg)

        with self.tracer.trace(
            span_name,
            source_id="pravo",
            url=url,
            method=method,
            circuit_state=self._circuit_breaker.state.value,
        ) as span:
            span.set_input(
                {
                    "url": url,
                    "method": method,
                    "params": params,
                    "has_body": json_data is not None,
                    "circuit_state": self._circuit_breaker.state.value,
                }
            )

            client = self._get_http_client()
            last_error: Exception | None = None
            non_retryable = False

            for attempt in range(1, self._max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                    )
                    response.raise_for_status()

                    # Record success in circuit breaker
                    self._circuit_breaker.record_success()

                    content_type = response.headers.get("content-type", "")
                    if "application/pdf" in content_type or "pdf" in path.lower():
                        body = response.content
                        span.set_output(
                            {
                                "status_code": response.status_code,
                                "content_length": len(body),
                                "attempt": attempt,
                                "content_type": "pdf",
                            }
                        )
                        return body

                    body = response.json()
                    span.set_output(
                        {
                            "status_code": response.status_code,
                            "attempt": attempt,
                        }
                    )
                    return body  # type: ignore[no-any-return]

                except httpx.TimeoutException as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "API timeout (attempt %d/%d): %s",
                        attempt,
                        self._max_retries,
                        url,
                    )
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "API HTTP error (attempt %d/%d, HTTP %d): %s",
                        attempt,
                        self._max_retries,
                        exc.response.status_code,
                        url,
                    )
                    if exc.response.status_code in _NON_RETRYABLE_STATUSES:
                        non_retryable = True
                        break
                except httpx.RequestError as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "API request error (attempt %d/%d): %s",
                        attempt,
                        self._max_retries,
                        url,
                    )

                if attempt < self._max_retries:
                    # Multiplicative backoff: 1s, 2s, 4s
                    await asyncio.sleep(1.0 * 2 ** (attempt - 1))

            # All retries exhausted — record failure in circuit breaker
            self._circuit_breaker.record_failure()

            error_detail = str(last_error) if last_error else "Unknown error"
            circuit_state = self._circuit_breaker.state.value
            if non_retryable:
                error_msg = (
                    f"API request failed with non-retryable HTTP status: {error_detail} "
                    f"(circuit={circuit_state})"
                )
            else:
                error_msg = (
                    f"Failed to call API after {self._max_retries} attempts: {error_detail} "
                    f"(circuit={circuit_state})"
                )
            span.set_error(SourceUnavailableError(error_msg))
            raise SourceUnavailableError(error_msg) from last_error

    async def get_public_blocks(
        self,
        parent: str | None = None,
    ) -> list[dict[str, Any]]:
        """Получить блоки публикации.

        Args:
            parent: ID родительского блока. None = корневые блоки.

        Returns:
            Список блоков публикации.
        """
        params: dict[str, Any] = {}
        if parent is not None:
            params["parent"] = parent

        result = await self._request(
            "GET",
            _PUBLIC_BLOCKS_PATH,
            params=params,
            span_name="pravo.get_public_blocks",
        )
        if isinstance(result, bytes):
            return []
        return result.get("items", result) if isinstance(result, dict) else result  # type: ignore[no-any-return]

    async def get_categories(
        self,
        block: str,
    ) -> list[dict[str, Any]]:
        """Получить категории для блока публикации.

        Args:
            block: ID блока публикации.

        Returns:
            Список категорий.
        """
        result = await self._request(
            "GET",
            _CATEGORIES_PATH,
            params={"block": block},
            span_name="pravo.get_categories",
        )
        if isinstance(result, bytes):
            return []
        return result.get("items", result) if isinstance(result, dict) else result  # type: ignore[no-any-return]

    async def get_signatory_authorities(
        self,
        block: str,
        category: str,
    ) -> list[dict[str, Any]]:
        """Получить органы власти для блока и категории.

        Args:
            block: ID блока публикации.
            category: ID категории.

        Returns:
            Список органов власти.
        """
        result = await self._request(
            "GET",
            _SIGNATORY_AUTHORITIES_PATH,
            params={"block": block, "category": category},
            span_name="pravo.get_signatory_authorities",
        )
        if isinstance(result, bytes):
            return []
        return result.get("items", result) if isinstance(result, dict) else result  # type: ignore[no-any-return]

    async def get_document_types(
        self,
        block: str,
        category: str,
        authority_id: str,
    ) -> list[dict[str, Any]]:
        """Получить виды документов.

        Args:
            block: ID блока публикации.
            category: ID категории.
            authority_id: ID органа власти.

        Returns:
            Список видов документов.
        """
        result = await self._request(
            "GET",
            _DOCUMENT_TYPES_PATH,
            params={
                "block": block,
                "category": category,
                "signatoryAuthorityId": authority_id,
            },
            span_name="pravo.get_document_types",
        )
        if isinstance(result, bytes):
            return []
        return result.get("items", result) if isinstance(result, dict) else result  # type: ignore[no-any-return]

    async def search_documents(
        self,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Поиск документов с фильтрами.

        Args:
            params: Параметры поиска (ключевые слова, даты, типы и т.д.).

        Returns:
            Результаты поиска.
        """
        result = await self._request(
            "GET",
            _DOCUMENTS_PATH,
            params=params,
            span_name="pravo.search_documents",
        )
        if isinstance(result, bytes):
            return {"items": [], "total": 0}
        if isinstance(result, dict):
            return result
        return {"items": result, "total": len(result)}

    async def get_document(self, eo_number: str) -> dict[str, Any]:
        """Получить детали документа по номеру электронного опубликования.

        Args:
            eo_number: Номер электронного опубликования (например, '0001202012230060').

        Returns:
            Детали документа.
        """
        result = await self._request(
            "GET",
            _DOCUMENT_PATH,
            params={"eoNumber": eo_number},
            span_name="pravo.get_document",
        )
        if isinstance(result, bytes):
            return {}
        if isinstance(result, dict):
            return result
        return {}

    async def download_pdf(self, eo_number: str) -> bytes:
        """Скачать PDF документа.

        Args:
            eo_number: Номер электронного опубликования.

        Returns:
            Сырые байты PDF-файла.
        """
        result = await self._request(
            "GET",
            _DOCUMENT_PDF_PATH,
            params={"eoNumber": eo_number},
            span_name="pravo.download_pdf",
        )
        if isinstance(result, dict):
            msg = f"Expected PDF bytes but got JSON for eo_number={eo_number}"
            raise SourceUnavailableError(msg)
        return result

    async def close(self) -> None:
        """Закрыть HTTP-клиент, если он был создан внутри."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> PravoClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


__all__ = [
    "PravoClient",
]
