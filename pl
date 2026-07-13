# Strategy Pattern Decomposition for PravoAdapter

## Цель

Изолировать stub-код так, чтобы его можно было удалить безболезненно.
Никаких stub-данных в production-классах.

## Архитектура

```
adapters/pravo/adapter/
├── __init__.py              # PravoAdapter — собирает всё вместе
├── base.py                  # PravoAdapterBase — конструктор, кэш, normalize, close, утилиты
├── constants.py             # Константы (URL, TTL, page size)
│
├── handlers/                # Abstract base handlers (protocols/ABC)
│   ├── __init__.py
│   ├── search.py            # BaseSearchHandler (ABC)
│   ├── get.py               # BaseGetHandler (ABC)
│   ├── ingest.py            # BaseIngestHandler (ABC)
│   ├── list_topics.py       # BaseListTopicsHandler (ABC)
│   └── get_content.py       # BaseGetContentHandler (ABC)
│
├── production/              # Production-реализации
│   ├── __init__.py
│   ├── search.py            # ProductionSearchHandler
│   ├── get.py               # ProductionGetHandler
│   ├── ingest.py            # ProductionIngestHandler
│   ├── list_topics.py       # ProductionListTopicsHandler
│   └── get_content.py       # ProductionGetContentHandler
│
└── stub/                    # Stub-реализации (можно удалить целиком)
    ├── __init__.py
    ├── search.py            # StubSearchHandler
    ├── get.py               # StubGetHandler
    ├── ingest.py            # StubIngestHandler
    ├── list_topics.py       # StubListTopicsHandler
    ├── get_content.py       # StubGetContentHandler
    └── get_toc.py           # StubGetTocHandler
```

## Принцип работы

```python
# adapter/__init__.py
class PravoAdapter(PravoAdapterBase):
    def __init__(self, mode="stub", *, client=None, parser=None, ocr_provider=None, tracer=None):
        super().__init__(client=client, parser=parser, ocr_provider=ocr_provider, tracer=tracer)

        # Выбор стратегий в зависимости от режима
        if mode == "stub":
            from adapters.pravo.adapter.stub import (
                StubSearchHandler, StubGetHandler, StubIngestHandler,
                StubListTopicsHandler, StubGetContentHandler, StubGetTocHandler,
            )
            self._search = StubSearchHandler(self)
            self._get = StubGetHandler(self)
            self._ingest = StubIngestHandler(self)
            self._list_topics = StubListTopicsHandler(self)
            self._get_content = StubGetContentHandler(self)
            self._get_toc = StubGetTocHandler(self)
        else:
            from adapters.pravo.adapter.production import (
                ProductionSearchHandler, ProductionGetHandler, ProductionIngestHandler,
                ProductionListTopicsHandler, ProductionGetContentHandler,
            )
            self._search = ProductionSearchHandler(self)
            self._get = ProductionGetHandler(self)
            self._ingest = ProductionIngestHandler(self)
            self._list_topics = ProductionListTopicsHandler(self)
            self._get_content = ProductionGetContentHandler(self)

    async def search(self, query, context=None):
        return await self._search.search(query, context)

    async def get(self, document_id):
        return await self._get.get(document_id)
    # ... и т.д.
```

## Что получает handler от PravoAdapter

Каждый handler получает ссылку на адаптер (`self`) и через неё имеет доступ к:

- `self._pravo_client` — HTTP клиент
- `self._parser` — парсер
- `self._document_cache` — кэш документов
- `self._get_stale_cached(document_id)` — метод для stale cache fallback
- `self._ensure_caches_populated()` — метод для заполнения кэшей парсера
- `self._get_ocr_provider()` — метод для получения OCR
- `self._extract_publish_id(document_id)` — утилита
- `self._blocks_to_topics(blocks, parent_id)` — утилита
- `self.tracer` — трейсер
- `self.source_id` — идентификатор источника

Stub-хендлеры дополнительно получают stub-данные через адаптер. Но эти данные создаются **только в stub-хендлерах**, не в `PravoAdapterBase`.

## Что меняется в PravoAdapterBase

Из `PravoAdapterBase` убираем:
- `_stub_documents` → переезжает в `StubSearchHandler`, `StubGetHandler` и т.д.
- `_stub_topics` → переезжает в `StubListTopicsHandler`
- `_stub_search()` → переезжает в `StubSearchHandler`
- `_production_search()` → переезжает в `ProductionSearchHandler`
- `_blocks_to_topics()` → остаётся в `PravoAdapterBase` (нужна и production, и stub может не нуждаться)

В `PravoAdapterBase` остаётся:
- Конструктор (`_mode`, `_pravo_client`, `_parser`, `_ocr_provider`, `_document_cache`, `_cache_populated_at`)
- `source_id`
- `normalize()`
- `get_toc()` — можно оставить заглушку в base, а StubGetTocHandler будет просто делегировать
- `close()`, `__aenter__`, `__aexit__`
- `parse_entry()`
- `_extract_publish_id()`
- `_get_stale_cached()`
- `_ensure_caches_populated()`
- `_get_ocr_provider()`
- `_blocks_to_topics()`

## Плюсы

1. **Stub изолирован** — `rm -rf adapters/pravo/adapter/stub/` и всё. Никаких ссылок на stub в production-коде.
2. **Маленькие файлы** — каждый handler 20-50 строк.
3. **Нет MRO** — чистая композиция.
4. **Нет `if self._mode`** — выбор стратегии происходит один раз в конструкторе.
5. **Легко тестировать** — можно замокать отдельный handler.
6. **Легко добавлять новые стратегии** — например `CachedSearchHandler`, который сначала проверяет Redis.

## Минусы

1. **Больше файлов** — ~18 файлов вместо 5.
2. **Нужно прокидывать `self` (адаптер) в каждый handler** — handler получает ссылку на адаптер и через неё имеет доступ ко всем зависимостям. Это циклическая ссылка, но в Python это нормально.
3. **PravoAdapter становится тонким фасадом** — каждый метод просто делегирует handler'у.

## Поток создания handler'ов

```python
# handlers/search.py
from abc import ABC, abstractmethod

class BaseSearchHandler(ABC):
    def __init__(self, adapter):
        self._adapter = adapter

    @abstractmethod
    async def search(self, query: str, context: SearchContext | None = None) -> list[SearchResult]:
        ...

# production/search.py
class ProductionSearchHandler(BaseSearchHandler):
    async def search(self, query, context=None):
        with self._adapter.tracer.trace("pravo.search", ...) as span:
            # Использует self._adapter._pravo_client, self._adapter._parser
            ...

# stub/search.py
class StubSearchHandler(BaseSearchHandler):
    def __init__(self, adapter):
        super().__init__(adapter)
        self._stub_documents = _build_stub_documents()  # из constants.py

    async def search(self, query, context=None):
        # Поиск по self._stub_documents
        ...
```

## Удаление stub

Когда stub больше не нужен:
1. Удалить папку `adapters/pravo/adapter/stub/`
2. В `adapter/__init__.py` убрать `if mode == "stub"` ветку
3. Удалить `_build_stub_documents()` из `constants.py`
4. Удалить stub-тесты
5. Готово. Никаких изменений в production-коде.
