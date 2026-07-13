"""RSSAdapter — базовый класс для источников, поддерживающих RSS/Atom ленты.

Общий функционал:
- Парсинг RSS/Atom ленты через httpx + xml.etree
- fetch_new_entries() — получение новых записей
- parse_entry() — парсинг одной записи в сырые данные

PravoAdapter наследует от RSSAdapter.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import httpx

from core.errors import SourceUnavailableError
from core.observability.logger import get_logger

# Default connection pool limits
_DEFAULT_LIMITS = httpx.Limits(
    max_connections=10,
    max_keepalive_connections=5,
)

if TYPE_CHECKING:
    from core.observability.tracer import Tracer

logger = get_logger(__name__)

# Namespace map for RSS/Atom parsing
_ATOM_NS = "http://www.w3.org/2005/Atom"

_RSS_NAMESPACES = {
    "atom": _ATOM_NS,
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class RSSAdapter(ABC):
    """Базовый класс для источников, поддерживающих RSS/Atom ленты.

    Предоставляет общий функционал для:
    - HTTP-запроса к RSS/Atom ленте
    - Парсинга RSS 2.0 и Atom форматов
    - Извлечения новых записей
    - Парсинга отдельной записи в сырые данные

    Наследники (например, PravoAdapter) реализуют:
    - parse_entry() — преобразование записи в каноническую модель
    - Дополнительные методы API (поиск, получение деталей и т.д.)
    """

    def __init__(
        self,
        *,
        feed_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        """Инициализация RSSAdapter.

        Args:
            feed_url: URL RSS/Atom ленты.
            timeout: Таймаут HTTP-запроса в секундах.
            max_retries: Количество попыток при ошибке HTTP.
            client: Внешний HTTP-клиент (для тестов). Если None, создаётся
                    внутренний.
            tracer: Опциональный tracer для observability.
        """
        self._feed_url = feed_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client
        self._owns_client = client is None
        self._tracer: Tracer | None = tracer

    @property
    def tracer(self) -> Tracer:
        """Lazy tracer — defer get_tracer() until first use.

        This avoids RuntimeError at import time when the tracer hasn't been
        configured yet (e.g. during test collection).
        """
        if self._tracer is None:
            from core.observability.tracer import get_tracer

            self._tracer = get_tracer()
        return self._tracer

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Уникальный идентификатор источника (например, 'pravo', 'nalog')."""
        ...

    def _get_http_client(self) -> httpx.AsyncClient:
        """Получить HTTP-клиент (создать, если ещё не создан)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=_DEFAULT_LIMITS,
            )
        return self._client

    async def fetch_feed(self, url: str | None = None) -> str:
        """Загрузить RSS/Atom ленту по URL.

        Args:
            url: URL ленты. Если None, используется self._feed_url.

        Returns:
            Сырой XML-контент ленты.

        Raises:
            SourceUnavailableError: Лента недоступна.
            ValueError: URL не указан.
        """
        feed_url = url or self._feed_url
        if not feed_url:
            raise ValueError("feed_url is required")

        with self.tracer.trace("rss.fetch_feed", source_id=self.source_id, url=feed_url) as span:
            span.set_input({"url": feed_url})

            client = self._get_http_client()
            last_error: Exception | None = None
            non_retryable = False

            for attempt in range(1, self._max_retries + 1):
                try:
                    async with client.stream("GET", feed_url, timeout=self._timeout) as response:
                        response.raise_for_status()
                        body = await response.aread()
                        body_text = body.decode("utf-8")
                        span.set_output(
                            {
                                "status_code": response.status_code,
                                "content_length": len(body_text),
                                "attempt": attempt,
                            }
                        )
                        return body_text

                except httpx.TimeoutException as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "Feed timeout (attempt %d/%d): %s",
                        attempt,
                        self._max_retries,
                        feed_url,
                    )
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "Feed HTTP error (attempt %d/%d, HTTP %d): %s",
                        attempt,
                        self._max_retries,
                        exc.response.status_code,
                        feed_url,
                    )
                    # Non-retryable status codes
                    if exc.response.status_code in (400, 401, 403, 404, 405):
                        non_retryable = True
                        break
                except httpx.RequestError as exc:
                    last_error = exc
                    span.set_error(exc)
                    logger.warning(
                        "Feed request error (attempt %d/%d): %s",
                        attempt,
                        self._max_retries,
                        feed_url,
                    )

                if attempt < self._max_retries:
                    # Multiplicative backoff: 1s, 2s, 4s, 8s...
                    await asyncio.sleep(1.0 * 2 ** (attempt - 1))

            error_detail = str(last_error) if last_error else "Unknown error"
            if non_retryable:
                error_msg = f"Feed request failed with non-retryable HTTP status: {error_detail}"
            else:
                error_msg = (
                    f"Failed to fetch feed after {self._max_retries} attempts: {error_detail}"
                )
            span.set_error(SourceUnavailableError(error_msg))
            raise SourceUnavailableError(error_msg) from last_error

    def parse_feed(self, raw_xml: str) -> list[dict[str, Any]]:
        """Парсинг RSS/Atom ленты в список сырых записей.

        Поддерживает:
        - RSS 2.0 (item элементы)
        - Atom (entry элементы)

        Args:
            raw_xml: Сырой XML-контент ленты.

        Returns:
            Список словарей с сырыми данными записей.
        """
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            logger.error("Failed to parse feed XML: %s", exc)
            raise ValueError(f"Failed to parse feed XML: {exc}") from exc

        # Определяем формат: RSS 2.0 или Atom
        if root.tag == "rss":
            return self._parse_rss(root)
        elif root.tag in ("feed", f"{{{_ATOM_NS}}}feed"):
            return self._parse_atom(root)
        else:
            logger.warning("Unknown feed root tag: %s", root.tag)
            return []

    def _parse_rss(self, root: ET.Element) -> list[dict[str, Any]]:
        """Парсинг RSS 2.0 ленты."""
        channel = root.find("channel")
        if channel is None:
            logger.warning("RSS feed has no <channel> element")
            return []

        entries: list[dict[str, Any]] = []
        for item in channel.findall("item"):
            entry = self._extract_rss_item(item)
            if entry:
                entries.append(entry)

        return entries

    def _extract_rss_item(self, item: ET.Element) -> dict[str, Any] | None:
        """Извлечение данных из одного RSS item."""
        entry: dict[str, Any] = {}

        # Основные поля RSS 2.0
        for field in ("title", "link", "description", "guid", "pubDate", "author"):
            elem = item.find(field)
            if elem is not None and elem.text:
                entry[field] = elem.text.strip()

        # Расширенные поля через namespace
        for ns_prefix, ns_uri in _RSS_NAMESPACES.items():
            for field in ("encoded", "creator", "date"):
                elem = item.find(f"{ns_prefix}:{field}", {ns_prefix: ns_uri})
                if elem is not None and elem.text:
                    entry[f"{ns_prefix}_{field}"] = elem.text.strip()

        # Категории
        categories: list[str] = []
        for cat in item.findall("category"):
            if cat.text:
                categories.append(cat.text.strip())
        if categories:
            entry["categories"] = categories

        # Вложения (enclosures)
        enclosures: list[dict[str, str]] = []
        for enc in item.findall("enclosure"):
            enc_data: dict[str, str] = {}
            if enc_url := enc.get("url"):
                enc_data["url"] = enc_url
            if enc_type := enc.get("type"):
                enc_data["type"] = enc_type
            if enc_length := enc.get("length"):
                enc_data["length"] = enc_length
            if enc_data:
                enclosures.append(enc_data)
        if enclosures:
            entry["enclosures"] = enclosures

        return entry if entry else None

    def _parse_atom(self, root: ET.Element) -> list[dict[str, Any]]:
        """Парсинг Atom ленты."""
        entries: list[dict[str, Any]] = []
        for entry_elem in root.findall(f"{{{_ATOM_NS}}}entry"):
            entry = self._extract_atom_entry(entry_elem)
            if entry:
                entries.append(entry)

        return entries

    def _extract_atom_entry(self, entry: ET.Element) -> dict[str, Any] | None:
        """Извлечение данных из одного Atom entry."""
        result: dict[str, Any] = {}

        # Заголовок
        title_elem = entry.find(f"{{{_ATOM_NS}}}title")
        if title_elem is not None and title_elem.text:
            result["title"] = title_elem.text.strip()

        # Ссылка
        link_elem = entry.find(f"{{{_ATOM_NS}}}link")
        if link_elem is not None:
            href = link_elem.get("href")
            if href:
                result["link"] = href

        # ID
        id_elem = entry.find(f"{{{_ATOM_NS}}}id")
        if id_elem is not None and id_elem.text:
            result["guid"] = id_elem.text.strip()

        # Обновление/публикация
        updated_elem = entry.find(f"{{{_ATOM_NS}}}updated")
        if updated_elem is not None and updated_elem.text:
            result["updated"] = updated_elem.text.strip()

        published_elem = entry.find(f"{{{_ATOM_NS}}}published")
        if published_elem is not None and published_elem.text:
            result["published"] = published_elem.text.strip()

        # Содержимое
        content_elem = entry.find(f"{{{_ATOM_NS}}}content")
        if content_elem is not None and content_elem.text:
            result["content"] = content_elem.text.strip()

        summary_elem = entry.find(f"{{{_ATOM_NS}}}summary")
        if summary_elem is not None and summary_elem.text:
            result["summary"] = summary_elem.text.strip()

        # Автор
        author_elem = entry.find(f"{{{_ATOM_NS}}}author")
        if author_elem is not None:
            name_elem = author_elem.find(f"{{{_ATOM_NS}}}name")
            if name_elem is not None and name_elem.text:
                result["author"] = name_elem.text.strip()

        # Категории
        categories: list[str] = []
        for cat in entry.findall(f"{{{_ATOM_NS}}}category"):
            term = cat.get("term")
            if term:
                categories.append(term)
        if categories:
            result["categories"] = categories

        return result if result else None

    async def fetch_new_entries(
        self,
        feed_url: str | None = None,
        *,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Получить новые записи из RSS/Atom ленты.

        Args:
            feed_url: URL ленты. Если None, используется self._feed_url.
            since: Опциональная дата — возвращать только записи новее этой даты.

        Returns:
            Список сырых записей (словарей).

        Raises:
            SourceUnavailableError: Лента недоступна.
        """
        with self.tracer.trace(
            "rss.fetch_new_entries",
            source_id=self.source_id,
            feed_url=feed_url or self._feed_url or "",
            since=since.isoformat() if since else "",
        ) as span:
            span.set_input(
                {
                    "feed_url": feed_url,
                    "since": since.isoformat() if since else None,
                }
            )

            raw_xml = await self.fetch_feed(feed_url)
            entries = self.parse_feed(raw_xml)

            if since is not None:
                filtered: list[dict[str, Any]] = []
                for entry in entries:
                    pub_date = self._extract_date(entry)
                    if pub_date is not None and pub_date > since:
                        filtered.append(entry)
                span.set_output(
                    {
                        "total_entries": len(entries),
                        "after_filter": len(filtered),
                    }
                )
                return filtered

            span.set_output({"total_entries": len(entries)})
            return entries

    @abstractmethod
    async def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        """Парсинг одной RSS-записи в сырые данные для нормализации.

        Наследники реализуют этот метод для преобразования RSS-записи
        в формат, который затем передаётся в normalize().

        Args:
            raw_entry: Сырая запись из RSS/Atom ленты.

        Returns:
            Словарь с сырыми данными, готовыми для normalize().
        """
        ...

    def _extract_date(self, entry: dict[str, Any]) -> datetime | None:
        """Извлечение даты из записи (RSS pubDate или Atom updated/published).

        Пытается распарсить дату из различных форматов:
        - RSS 2.0: pubDate (RFC 2822)
        - Atom: updated, published (ISO 8601)
        - Dublin Core: dc_date (ISO 8601)

        Args:
            entry: Сырая запись.

        Returns:
            datetime в UTC или None, если дату не удалось распарсить.
        """
        date_str: str | None = None

        # RSS 2.0 pubDate
        if "pubDate" in entry:
            date_str = entry["pubDate"]
        # Atom updated
        elif "updated" in entry:
            date_str = entry["updated"]
        # Atom published
        elif "published" in entry:
            date_str = entry["published"]
        # Dublin Core date
        elif "dc_date" in entry:
            date_str = entry["dc_date"]

        if not date_str:
            return None

        return self._parse_date_string(date_str)

    @staticmethod
    def _parse_date_string(date_str: str) -> datetime | None:
        """Парсинг строки даты из различных форматов.

        Поддерживает:
        - RFC 2822 (например, 'Mon, 15 Aug 2022 12:00:00 +0300')
        - ISO 8601 (например, '2022-08-15T12:00:00Z' или '2022-08-15T12:00:00+03:00')
        - YYYY-MM-DD
        """
        # Пробуем RFC 2822 (RSS pubDate)
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # Пробуем ISO 8601 (Atom)
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # Пробуем YYYY-MM-DD
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        logger.warning("Unable to parse date string: %s", date_str)
        return None

    async def close(self) -> None:
        """Закрыть HTTP-клиент, если он был создан внутри адаптера."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> RSSAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()


__all__ = [
    "RSSAdapter",
]
