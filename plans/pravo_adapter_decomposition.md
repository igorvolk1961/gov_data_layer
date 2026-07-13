# PravoAdapter Decomposition History

## Phase 1: Initial Decomposition (Mixins)

**Goal:** Split the monolithic [`adapters/pravo/pravo_adapter.py`](adapters/pravo/pravo_adapter.py) (~800 lines, 18.6 KB) into a subpackage `adapters/pravo/adapter/` with clearly separated responsibilities.

### Original Structure

`pravo_adapter.py` contained:

| Responsibility | Lines | Description |
|---|---|---|
| Module-level constants | 39-65 | `_SOURCE_URL`, `_DOCUMENT_URL_TEMPLATE`, `_STALE_CACHE_TTL`, `_CACHE_POPULATE_TTL`, `_INGEST_PAGE_SIZE`, stub data lists |
| `_build_stub_documents()` | 68-149 | Factory function creating 3 fixed `OfficialDocument` instances |
| `PravoAdapter.__init__()` | 159-234 | Constructor with mode, client, parser, ocr_provider, tracer params; initializes cache, stub data, topics |
| `source_id` property | 236-238 | Returns `"pravo"` |
| `search()` | 242-273 | Delegates to `_stub_search()` or `_production_search()` |
| `get()` | 275-336 | Fetches document by ID; stale cache fallback |
| `normalize()` | 338-350 | Delegates to `self._parser.parse_document()` |
| `ingest()` | 352-398 | Stub returns count; production fetches via API |
| `list_topics()` | 400-439 | Stub returns fixed topics; production via API |
| `get_toc()` | 441-460 | Stub — always returns empty list |
| `get_content()` | 462-522 | Stub returns placeholder; production downloads PDF + OCR |
| `close()` / `__aenter__` / `__aexit__` | 526-534 | Resource management |
| `parse_entry()` | 538-548 | RSSAdapter protocol — stub |
| `_extract_publish_id()` | 552-567 | Utility: `"pravo-XXX"` → `"XXX"` |
| `_get_stale_cached()` | 569-587 | Cache lookup with TTL check |
| `_ensure_caches_populated()` | 589-644 | Fetches authorities/doc types from API |
| `_get_ocr_provider()` | 646-684 | Lazy OCR provider creation from config |
| `_stub_search()` | 686-745 | Search over `_stub_documents` |
| `_production_search()` | 747-764 | Stub — returns empty list |
| `_blocks_to_topics()` | 766-796 | Static: API blocks → `TopicNode` list |

### First Module Layout (Mixins)

```
adapters/pravo/adapter/
├── __init__.py          # Re-exports PravoAdapter (multiple inheritance)
├── constants.py         # Module-level constants
├── base.py              # PravoAdapterBase — shared logic (init, cache, utils, resource mgmt)
├── stub.py              # StubMixin — stub mode methods
└── production.py        # ProductionMixin — production mode methods
```

### Why Multiple Inheritance Was Chosen Initially

The `PravoAdapter` class needed to be a single class because:
1. Tests import `PravoAdapter` directly and instantiate it
2. The `SourceAdapter` protocol expects a class, not a factory
3. `RSSAdapter.__init__()` must be called via `super()`

Using mixins with multiple inheritance kept the class hierarchy flat and testable.

### Problem Discovered

**MRO bug:** `StubMixin` came before `ProductionMixin` in the MRO, so production-mode tests calling `get()` hit `StubMixin.get()` instead of `ProductionMixin.get()`. Fixed by adding `self._mode` checks in all `StubMixin` methods — if mode is "production", delegate to `super()` (next class in MRO). This was a workaround, not a clean solution.

---

## Phase 2: Strategy Pattern (Final Architecture)

**Goal:** Isolate stub code so it can be painlessly removed. No stub data in production classes.

### Problem with Mixins

1. **Stub code mixed with production** — `StubMixin` had `if self._mode == "production"` checks
2. **MRO fragility** — order of base classes matters
3. **Hard to remove stub** — need to edit mixin classes

### New Architecture

```
adapters/pravo/adapter/
├── __init__.py              # PravoAdapter — facade with strategy selection
├── base.py                  # PravoAdapterBase — constructor, cache, normalize, close, utilities
├── constants.py             # Constants (URL, TTL, page size)
│
├── handlers/                # Abstract base handlers (ABC)
│   ├── __init__.py
│   ├── search.py            # BaseSearchHandler
│   ├── get.py               # BaseGetHandler
│   ├── ingest.py            # BaseIngestHandler
│   ├── list_topics.py       # BaseListTopicsHandler
│   ├── get_content.py       # BaseGetContentHandler
│   └── get_toc.py           # BaseGetTocHandler
│
├── production/              # Production implementations
│   ├── __init__.py
│   ├── search.py            # ProductionSearchHandler
│   ├── get.py               # ProductionGetHandler
│   ├── ingest.py            # ProductionIngestHandler
│   ├── list_topics.py       # ProductionListTopicsHandler
│   └── get_content.py       # ProductionGetContentHandler
│
└── stub/                    # Stub implementations (can be deleted entirely)
    ├── __init__.py
    ├── _data.py             # Shared stub data (_build_stub_documents())
    ├── search.py            # StubSearchHandler
    ├── get.py               # StubGetHandler
    ├── ingest.py            # StubIngestHandler
    ├── list_topics.py       # StubListTopicsHandler
    ├── get_content.py       # StubGetContentHandler
    └── get_toc.py           # StubGetTocHandler
```

### How It Works

```python
# adapter/__init__.py
class PravoAdapter(PravoAdapterBase):
    def __init__(self, mode="stub", *, client=None, parser=None, ocr_provider=None, tracer=None):
        super().__init__(client=client, parser=parser, ocr_provider=ocr_provider, tracer=tracer)
        self._search, self._get, self._ingest, self._list_topics, self._get_content, self._get_toc = \
            self._build_handlers(mode)

    def _build_handlers(self, mode):
        if mode == "stub":
            from adapters.pravo.adapter.stub import ...
            return StubSearchHandler(self), StubGetHandler(self), ...
        else:
            from adapters.pravo.adapter.production import ...
            return ProductionSearchHandler(self), ProductionGetHandler(self), ...

    async def search(self, query, context=None):
        return await self._search.search(query, context)
    # ... etc.
```

### What Each Handler Gets

Each handler receives a reference to the adapter (`self._adapter`) and through it has access to:
- `self._adapter._pravo_client` — HTTP client
- `self._adapter._parser` — parser
- `self._adapter._document_cache` — document cache
- `self._adapter._get_stale_cached(document_id)` — stale cache fallback
- `self._adapter._ensure_caches_populated()` — cache population
- `self._adapter._get_ocr_provider()` — OCR provider factory
- `self._adapter._extract_publish_id(document_id)` — utility
- `self._adapter._blocks_to_topics(blocks, parent_id)` — utility
- `self._adapter.tracer` — tracer
- `self._adapter.source_id` — source identifier

Stub handlers additionally create stub data **only in the stub subpackage** (`stub/_data.py`), not in `PravoAdapterBase`.

### What Changed in PravoAdapterBase

**Removed:**
- `_stub_documents` → moved to `StubSearchHandler`, `StubGetHandler`, etc.
- `_stub_topics` → moved to `StubListTopicsHandler`
- `_stub_search()` → moved to `StubSearchHandler`
- `_production_search()` → moved to `ProductionSearchHandler`

**Kept:**
- Constructor (`_mode`, `_pravo_client`, `_parser`, `_ocr_provider`, `_document_cache`, `_cache_populated_at`)
- `source_id`
- `normalize()`
- `close()`, `__aenter__`, `__aexit__`
- `parse_entry()`
- `_extract_publish_id()`
- `_get_stale_cached()`
- `_ensure_caches_populated()`
- `_get_ocr_provider()`
- `_blocks_to_topics()`

### Pros

1. **Stub isolated** — `rm -rf adapters/pravo/adapter/stub/` and done. No stub references in production code.
2. **Small files** — each handler 20-50 lines.
3. **No MRO** — pure composition.
4. **No `if self._mode`** — strategy selection happens once in constructor.
5. **Easy to test** — can mock individual handlers.
6. **Easy to add new strategies** — e.g. `CachedSearchHandler` that checks Redis first.

### Cons

1. **More files** — ~18 files instead of 5.
2. **Adapter reference in each handler** — circular reference, but fine in Python.
3. **PravoAdapter becomes thin facade** — each method just delegates to a handler.

### Deleting Stub

When stub is no longer needed:
1. Delete `adapters/pravo/adapter/stub/` folder
2. In `adapter/__init__.py`, remove `if mode == "stub"` branch
3. Delete `_build_stub_documents()` from `stub/_data.py`
4. Delete stub tests
5. Done. No changes to production code.

### Consumer Impact

| File | Old Import | New Import |
|---|---|---|
| [`adapters/pravo/__init__.py`](adapters/pravo/__init__.py) | `from adapters.pravo.pravo_adapter import PravoAdapter` | `from adapters.pravo.adapter import PravoAdapter` |
| [`tests/unit/test_pravo_adapter_production.py`](tests/unit/test_pravo_adapter_production.py) | `from adapters.pravo.pravo_adapter import PravoAdapter` | `from adapters.pravo.adapter import PravoAdapter` |
| [`tests/unit/test_pravo_adapter_cache.py`](tests/unit/test_pravo_adapter_cache.py) | `from adapters.pravo.pravo_adapter import _STALE_CACHE_TTL, PravoAdapter` | `from adapters.pravo.adapter.constants import _STALE_CACHE_TTL` + `from adapters.pravo.adapter import PravoAdapter` |
| [`tests/integration/test_pravo_production.py`](tests/integration/test_pravo_production.py) | `from adapters.pravo.pravo_adapter import PravoAdapter` | `from adapters.pravo.adapter import PravoAdapter` |

The old [`adapters/pravo/pravo_adapter.py`](adapters/pravo/pravo_adapter.py) was rewritten as a thin re-export facade for backward compatibility.
