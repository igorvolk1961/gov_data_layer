"""Unit-тесты для RSSAdapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from adapters.base.rss_adapter import RSSAdapter
from core.errors import SourceUnavailableError


def _make_stream_mock(response: MagicMock) -> Any:
    """Create a mock for client.stream() that works as an async context manager.

    Returns a callable that returns an async context manager yielding the response.
    Usage:
        mock_client.stream = _make_stream_mock(mock_response)
    """

    @asynccontextmanager
    async def _stream(*_args: object, **_kwargs: object) -> AsyncIterator[MagicMock]:
        yield response

    return _stream


# ──────────────────────────────────────────────
# Concrete implementation for testing
# ──────────────────────────────────────────────


class ConcreteRSSAdapter(RSSAdapter):
    """Конкретная реализация RSSAdapter для тестов."""

    @property
    def source_id(self) -> str:
        return "test_source"

    async def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        return {"source": self.source_id, **raw_entry}


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def tracer_mock() -> MagicMock:
    """Create a no-op tracer mock for injection into RSSAdapter."""
    span_mock = MagicMock()
    span_mock.__enter__.return_value = span_mock
    tracer = MagicMock()
    tracer.trace.return_value = span_mock
    return tracer


@pytest.fixture
def adapter(tracer_mock: MagicMock) -> ConcreteRSSAdapter:
    return ConcreteRSSAdapter(
        feed_url="https://example.com/feed.xml",
        tracer=tracer_mock,
    )


@pytest.fixture
def rss_sample() -> str:
    """Пример RSS 2.0 ленты."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test RSS feed</description>
    <item>
      <title>First Article</title>
      <link>https://example.com/1</link>
      <description>Description of first article</description>
      <guid>https://example.com/1</guid>
      <pubDate>Mon, 15 Aug 2022 12:00:00 +0300</pubDate>
      <author>Author One</author>
      <category>News</category>
      <category>Tech</category>
      <enclosure url="https://example.com/file.pdf" type="application/pdf" length="12345"/>
    </item>
    <item>
      <title>Second Article</title>
      <link>https://example.com/2</link>
      <description>Description of second article</description>
      <guid>https://example.com/2</guid>
      <pubDate>Tue, 16 Aug 2022 14:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


@pytest.fixture
def atom_sample() -> str:
    """Пример Atom ленты."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <link href="https://example.com/atom"/>
  <id>urn:uuid:12345</id>
  <updated>2022-08-15T12:00:00Z</updated>
  <entry>
    <title>Atom Article</title>
    <link href="https://example.com/atom/1"/>
    <id>urn:uuid:abcde</id>
    <updated>2022-08-15T12:00:00Z</updated>
    <published>2022-08-14T10:00:00Z</published>
    <summary>Atom summary</summary>
    <author>
      <name>Atom Author</name>
    </author>
    <category term="Science"/>
  </entry>
</feed>"""


@pytest.fixture
def mock_client() -> AsyncMock:
    """Мок HTTP-клиента."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


# ──────────────────────────────────────────────
# Tests: ABC enforcement
# ──────────────────────────────────────────────


class TestABCEnforcement:
    def test_cannot_instantiate_abstract(self) -> None:
        """RSSAdapter нельзя инстанциировать напрямую."""
        with pytest.raises(TypeError):
            RSSAdapter()  # type: ignore[abstract]

    def test_must_implement_source_id(self) -> None:
        """Наследник должен реализовать source_id."""
        with pytest.raises(TypeError):

            class MissingSource(RSSAdapter):  # type: ignore[abstract]
                async def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
                    return raw_entry

            MissingSource()

    def test_must_implement_parse_entry(self) -> None:
        """Наследник должен реализовать parse_entry."""
        with pytest.raises(TypeError):

            class MissingParse(RSSAdapter):  # type: ignore[abstract]
                @property
                def source_id(self) -> str:
                    return "test"

            MissingParse()


# ──────────────────────────────────────────────
# Tests: RSS 2.0 parsing
# ──────────────────────────────────────────────


class TestRSSParsing:
    def test_parse_rss_feed(self, adapter: ConcreteRSSAdapter, rss_sample: str) -> None:
        """Парсинг RSS 2.0 ленты возвращает список записей."""
        entries = adapter.parse_feed(rss_sample)
        assert len(entries) == 2

    def test_parse_rss_item_fields(self, adapter: ConcreteRSSAdapter, rss_sample: str) -> None:
        """Проверка полей RSS записи."""
        entries = adapter.parse_feed(rss_sample)
        entry = entries[0]

        assert entry["title"] == "First Article"
        assert entry["link"] == "https://example.com/1"
        assert entry["description"] == "Description of first article"
        assert entry["guid"] == "https://example.com/1"
        assert entry["pubDate"] == "Mon, 15 Aug 2022 12:00:00 +0300"
        assert entry["author"] == "Author One"

    def test_parse_rss_categories(self, adapter: ConcreteRSSAdapter, rss_sample: str) -> None:
        """Проверка категорий RSS записи."""
        entries = adapter.parse_feed(rss_sample)
        entry = entries[0]
        assert entry["categories"] == ["News", "Tech"]

    def test_parse_rss_enclosures(self, adapter: ConcreteRSSAdapter, rss_sample: str) -> None:
        """Проверка вложений RSS записи."""
        entries = adapter.parse_feed(rss_sample)
        entry = entries[0]
        assert len(entry["enclosures"]) == 1
        enc = entry["enclosures"][0]
        assert enc["url"] == "https://example.com/file.pdf"
        assert enc["type"] == "application/pdf"
        assert enc["length"] == "12345"

    def test_parse_rss_empty_feed(self, adapter: ConcreteRSSAdapter) -> None:
        """Пустая RSS лента."""
        xml = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""
        entries = adapter.parse_feed(xml)
        assert entries == []

    def test_parse_rss_no_channel(self, adapter: ConcreteRSSAdapter) -> None:
        """RSS без channel."""
        xml = """<?xml version="1.0"?><rss version="2.0"></rss>"""
        entries = adapter.parse_feed(xml)
        assert entries == []


# ──────────────────────────────────────────────
# Tests: Atom parsing
# ──────────────────────────────────────────────


class TestAtomParsing:
    def test_parse_atom_feed(self, adapter: ConcreteRSSAdapter, atom_sample: str) -> None:
        """Парсинг Atom ленты возвращает список записей."""
        entries = adapter.parse_feed(atom_sample)
        assert len(entries) == 1

    def test_parse_atom_entry_fields(self, adapter: ConcreteRSSAdapter, atom_sample: str) -> None:
        """Проверка полей Atom записи."""
        entries = adapter.parse_feed(atom_sample)
        entry = entries[0]

        assert entry["title"] == "Atom Article"
        assert entry["link"] == "https://example.com/atom/1"
        assert entry["guid"] == "urn:uuid:abcde"
        assert entry["updated"] == "2022-08-15T12:00:00Z"
        assert entry["published"] == "2022-08-14T10:00:00Z"
        assert entry["summary"] == "Atom summary"
        assert entry["author"] == "Atom Author"
        assert entry["categories"] == ["Science"]

    def test_parse_atom_empty_feed(self, adapter: ConcreteRSSAdapter) -> None:
        """Пустая Atom лента."""
        xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>"""
        entries = adapter.parse_feed(xml)
        assert entries == []


# ──────────────────────────────────────────────
# Tests: Invalid XML
# ──────────────────────────────────────────────


class TestInvalidXML:
    def test_parse_invalid_xml(self, adapter: ConcreteRSSAdapter) -> None:
        """Некорректный XML вызывает ValueError."""
        with pytest.raises(ValueError, match="Failed to parse feed XML"):
            adapter.parse_feed("not xml")

    def test_parse_unknown_root(self, adapter: ConcreteRSSAdapter) -> None:
        """Неизвестный корневой элемент возвращает пустой список."""
        xml = """<?xml version="1.0"?><unknown><data/></unknown>"""
        entries = adapter.parse_feed(xml)
        assert entries == []


# ──────────────────────────────────────────────
# Tests: Date extraction
# ──────────────────────────────────────────────


class TestDateExtraction:
    def test_extract_rfc2822_date(self, adapter: ConcreteRSSAdapter) -> None:
        """Парсинг RFC 2822 даты."""
        entry = {"pubDate": "Mon, 15 Aug 2022 12:00:00 +0300"}
        dt = adapter._extract_date(entry)
        assert dt is not None
        assert dt.tzinfo is not None
        # 12:00 +0300 = 09:00 UTC
        assert dt.hour == 9
        assert dt.day == 15
        assert dt.month == 8
        assert dt.year == 2022

    def test_extract_iso8601_date(self, adapter: ConcreteRSSAdapter) -> None:
        """Парсинг ISO 8601 даты."""
        entry = {"updated": "2022-08-15T12:00:00Z"}
        dt = adapter._extract_date(entry)
        assert dt is not None
        assert dt.year == 2022
        assert dt.month == 8
        assert dt.day == 15
        assert dt.hour == 12

    def test_extract_iso8601_with_offset(self, adapter: ConcreteRSSAdapter) -> None:
        """Парсинг ISO 8601 с таймзоной."""
        entry = {"published": "2022-08-15T12:00:00+03:00"}
        dt = adapter._extract_date(entry)
        assert dt is not None
        # 12:00 +03:00 = 09:00 UTC
        assert dt.hour == 9

    def test_extract_yyyy_mm_dd(self, adapter: ConcreteRSSAdapter) -> None:
        """Парсинг YYYY-MM-DD."""
        entry = {"pubDate": "2022-08-15"}
        dt = adapter._extract_date(entry)
        assert dt is not None
        assert dt.year == 2022
        assert dt.month == 8
        assert dt.day == 15
        assert dt.hour == 0
        assert dt.tzinfo is not None

    def test_extract_date_missing(self, adapter: ConcreteRSSAdapter) -> None:
        """Нет даты — возвращаем None."""
        entry: dict[str, Any] = {"title": "No date"}
        assert adapter._extract_date(entry) is None

    def test_extract_date_invalid(self, adapter: ConcreteRSSAdapter) -> None:
        """Некорректная дата — возвращаем None."""
        entry = {"pubDate": "not a date"}
        assert adapter._extract_date(entry) is None

    def test_extract_date_dc_date(self, adapter: ConcreteRSSAdapter) -> None:
        """Парсинг Dublin Core даты."""
        entry = {"dc_date": "2022-08-15T12:00:00Z"}
        dt = adapter._extract_date(entry)
        assert dt is not None
        assert dt.year == 2022


# ──────────────────────────────────────────────
# Tests: fetch_new_entries with since filter
# ──────────────────────────────────────────────


class TestFetchNewEntries:
    @pytest.fixture
    def mock_response(self, rss_sample: str) -> MagicMock:
        """Create a mock HTTP response returning the RSS sample."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.text = rss_sample
        response.raise_for_status.return_value = None
        response.aread = AsyncMock(return_value=rss_sample.encode("utf-8"))
        return response

    @pytest.fixture
    def adapter_with_mock(
        self, mock_client: AsyncMock, mock_response: MagicMock, tracer_mock: MagicMock
    ) -> ConcreteRSSAdapter:
        """Adapter with injected mock client that returns the RSS sample."""
        mock_client.stream = _make_stream_mock(mock_response)
        return ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            tracer=tracer_mock,
        )

    @pytest.mark.asyncio
    async def test_fetch_new_entries_with_since(
        self, adapter_with_mock: ConcreteRSSAdapter
    ) -> None:
        """fetch_new_entries с since фильтром."""
        since = datetime(2022, 8, 16, 10, 0, tzinfo=timezone.utc)
        entries = await adapter_with_mock.fetch_new_entries(since=since)

        # Только вторая запись (16 Aug) новее since
        assert len(entries) == 1
        assert entries[0]["title"] == "Second Article"

    @pytest.mark.asyncio
    async def test_fetch_new_entries_without_since(
        self, adapter_with_mock: ConcreteRSSAdapter
    ) -> None:
        """fetch_new_entries без since возвращает все записи."""
        entries = await adapter_with_mock.fetch_new_entries()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_fetch_new_entries_empty(
        self, mock_client: AsyncMock, tracer_mock: MagicMock
    ) -> None:
        """fetch_new_entries с пустой лентой."""
        empty_response = MagicMock(spec=httpx.Response)
        empty_response.status_code = 200
        empty_response.text = (
            """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""
        )
        empty_response.raise_for_status.return_value = None
        empty_response.aread = AsyncMock(
            return_value=b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        )
        mock_client.stream = _make_stream_mock(empty_response)

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            tracer=tracer_mock,
        )
        entries = await adapter.fetch_new_entries()
        assert entries == []


# ──────────────────────────────────────────────
# Tests: Feed fetching with retry
# ──────────────────────────────────────────────


class TestFeedFetching:
    @pytest.mark.asyncio
    async def test_fetch_feed_success(self, mock_client: AsyncMock, tracer_mock: MagicMock) -> None:
        """Успешный запрос ленты."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<rss><channel><item><title>Test</title></item></channel></rss>"
        mock_response.raise_for_status.return_value = None
        mock_response.aread = AsyncMock(
            return_value=b"<rss><channel><item><title>Test</title></item></channel></rss>"
        )
        mock_client.stream = _make_stream_mock(mock_response)

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            tracer=tracer_mock,
        )
        result = await adapter.fetch_feed()
        assert "<title>Test</title>" in result

        # Verify tracer span methods were called
        span_mock = tracer_mock.trace.return_value.__enter__.return_value
        span_mock.set_input.assert_called_once_with({"url": "https://example.com/feed.xml"})
        span_mock.set_output.assert_called_once()
        span_mock.set_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_feed_retry_on_timeout(
        self, mock_client: AsyncMock, tracer_mock: MagicMock
    ) -> None:
        """Ретрай при таймауте."""
        call_count = 0

        @asynccontextmanager
        async def _stream_timeout(*_args: object, **_kwargs: object) -> AsyncIterator[MagicMock]:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")
            yield MagicMock()  # type: ignore[unreachable]

        mock_client.stream = _stream_timeout

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            max_retries=3,
            tracer=tracer_mock,
        )

        with pytest.raises(SourceUnavailableError):
            await adapter.fetch_feed()

        assert call_count == 3

        # Verify tracer span recorded the error on each retry attempt
        span_mock = tracer_mock.trace.return_value.__enter__.return_value
        assert span_mock.set_error.call_count == 4  # 3 retries + 1 final

    @pytest.mark.asyncio
    async def test_fetch_feed_no_retry_on_404(
        self, mock_client: AsyncMock, tracer_mock: MagicMock
    ) -> None:
        """Нет ретрая при 404."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )
        mock_response.aread = AsyncMock(return_value=b"")

        call_count = 0

        @asynccontextmanager
        async def _stream_404(*_args: object, **_kwargs: object) -> AsyncIterator[MagicMock]:
            nonlocal call_count
            call_count += 1
            yield mock_response

        mock_client.stream = _stream_404

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            max_retries=3,
            tracer=tracer_mock,
        )

        with pytest.raises(SourceUnavailableError):
            await adapter.fetch_feed()

        # Должен быть только 1 запрос (без ретрая)
        assert call_count == 1

        # Verify tracer span recorded the error (1 per attempt + 1 final)
        span_mock = tracer_mock.trace.return_value.__enter__.return_value
        assert span_mock.set_error.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_feed_no_retry_on_403(
        self, mock_client: AsyncMock, tracer_mock: MagicMock
    ) -> None:
        """Нет ретрая при 403."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_response
        )
        mock_response.aread = AsyncMock(return_value=b"")

        call_count = 0

        @asynccontextmanager
        async def _stream_403(*_args: object, **_kwargs: object) -> AsyncIterator[MagicMock]:
            nonlocal call_count
            call_count += 1
            yield mock_response

        mock_client.stream = _stream_403

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            max_retries=3,
            tracer=tracer_mock,
        )

        with pytest.raises(SourceUnavailableError):
            await adapter.fetch_feed()

        assert call_count == 1

        # Verify tracer span recorded the error (1 per attempt + 1 final)
        span_mock = tracer_mock.trace.return_value.__enter__.return_value
        assert span_mock.set_error.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_feed_retry_on_500(
        self, mock_client: AsyncMock, tracer_mock: MagicMock
    ) -> None:
        """Ретрай при 500."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_response
        )
        mock_response.aread = AsyncMock(return_value=b"")

        call_count = 0

        @asynccontextmanager
        async def _stream_500(*_args: object, **_kwargs: object) -> AsyncIterator[MagicMock]:
            nonlocal call_count
            call_count += 1
            yield mock_response

        mock_client.stream = _stream_500

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            max_retries=3,
            tracer=tracer_mock,
        )

        with pytest.raises(SourceUnavailableError):
            await adapter.fetch_feed()

        assert call_count == 3

        # Verify tracer span recorded the error (3 retries + 1 final)
        span_mock = tracer_mock.trace.return_value.__enter__.return_value
        assert span_mock.set_error.call_count == 4

    @pytest.mark.asyncio
    async def test_fetch_feed_no_url(self, tracer_mock: MagicMock) -> None:
        """Ошибка при отсутствии URL."""
        adapter = ConcreteRSSAdapter(
            feed_url="",
            tracer=tracer_mock,
        )
        with pytest.raises(ValueError, match="feed_url is required"):
            await adapter.fetch_feed()


# ──────────────────────────────────────────────
# Tests: Context manager
# ──────────────────────────────────────────────


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self, tracer_mock: MagicMock) -> None:
        """Асинхронный контекстный менеджер закрывает внутренний клиент."""
        async with ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            tracer=tracer_mock,
        ) as adapter:
            assert adapter.source_id == "test_source"
            # Client is created lazily — trigger creation
            client = adapter._get_http_client()
            assert client is not None

        # After exiting context, the internal client should be closed
        # (we can't easily assert on it, but no error should occur)

    @pytest.mark.asyncio
    async def test_close_internal_client(self, tracer_mock: MagicMock) -> None:
        """Метод close() закрывает внутренний клиент."""
        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            tracer=tracer_mock,
        )
        # Trigger lazy client creation
        _ = adapter._get_http_client()
        assert adapter._owns_client is True
        await adapter.close()
        # Client should be set to None after close
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_close_does_not_close_external_client(self, tracer_mock: MagicMock) -> None:
        """Метод close() не закрывает внешний (инжектированный) клиент."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock()

        adapter = ConcreteRSSAdapter(
            feed_url="https://example.com/feed.xml",
            client=mock_client,
            tracer=tracer_mock,
        )
        assert adapter._owns_client is False
        await adapter.close()
        # External client should NOT be closed
        mock_client.aclose.assert_not_called()


# ──────────────────────────────────────────────
# Tests: parse_entry implementation
# ──────────────────────────────────────────────


class TestParseEntry:
    @pytest.mark.asyncio
    async def test_parse_entry_returns_dict(self, adapter: ConcreteRSSAdapter) -> None:
        """parse_entry возвращает словарь с source_id."""
        raw = {"title": "Test", "link": "https://example.com"}
        result = await adapter.parse_entry(raw)
        assert result["source"] == "test_source"
        assert result["title"] == "Test"
        assert result["link"] == "https://example.com"
