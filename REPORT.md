# Official Data Layer for AI Agents — Status Report

**Дата:** 2026-07-17
**Контекст:** Анализ проекта [`gov_data_layer`](.) против критериев [`expected_result.md`](docs/reference/expected_result.md) и [`original_task.md`](docs/reference/original_task.md)

---

## 1. Архитектура (как задумано)

```
┌─────────────────────────────────────────────────────────────────┐
│                      QUERY PATH (read)                          │
│                                                                 │
│  Agent → [MCP/REST] → ODLService → embedder → Qdrant           │
│                                          ┌───────────────────┐  │
│                                          │ Metadata Routing  │  │
│                                          │ (payload filters: │  │
│                                          │  region, topic,   │  │
│                                          │  organization,    │  │
│                                          │  legal_status)    │  │
│                                          └───────────────────┘  │
│                                            ↓                    │
│                                         Response + provenance   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     INGEST PATH (write)                         │
│                                                                 │
│  Source → [SourceAdapter] → normalize → chunk → embed → Qdrant │
│                              ┌──────────────────────────────┐  │
│                              │ Payload: metadata, sections, │  │
│                              │ legal_status, region, topic  │  │
│                              └──────────────────────────────┘  │
│                                       ↓                        │
│                                PostgreSQL (sections, refs)     │
└─────────────────────────────────────────────────────────────────┘
```

**Ключевое решение:** Адаптеры не участвуют в query path — это особенность, а не баг. Metadata Routing через Qdrant payload-фильтрацию заменяет явный роутер (source router), следуя принципу **механизм/политика**:

- **Механизм (слой):** инжест через адаптеры → нормализация → индексация с метаданными → векторный поиск с фильтрацией по метаданным
- **Политика (агент):** регион, рубрика, порог уверенности, «не отдавать отменённое» — декларативные ограничения в `SearchContext`

Это обеспечивает:
- **Переносимость:** добавление источника = новый адаптер + инжест, ядро не трогается
- **Производительность:** query path без сетевых вызовов к источнику
- **Проверяемость:** новое требование (e.g. «не отдавать отменённое») трогает только Qdrant filter (край), не ядро

---

## 2. Что сделано (сильные стороны)

### 2.1 Архитектура и спецификация ✅
| Компонент | Статус | Файл |
|-----------|--------|------|
| C4 Context diagram | ✅ Готов | [`docs/architecture/c4-context.md`](docs/architecture/c4-context.md) |
| C4 Container diagram | ✅ Готов | [`docs/architecture/c4-container.md`](docs/architecture/c4-container.md) |
| Спецификация | ✅ Готов | [`docs/specification.md`](docs/specification.md) |
| ADR (17 решений) | ✅ Готов | [`docs/adr.md`](docs/adr.md) |
| Agent Skill | ⚠️ Черновик | [`docs/agent-integration/SKILL.md`](docs/agent-integration/SKILL.md) |

### 2.2 Каноническая модель данных ✅
- 12 Pydantic v2 моделей: `OfficialDocument`, `SearchContext`, `SearchResult`, `SearchResponse`, `DocumentDetail`, `ConfidenceSignals`, `Citation`, `TopicNode`, `TocNode`, `DocumentChunk`, `Source`, `LegalStatus`, `SourceAvailability`
- Типизированные ошибки: 5 классов (`NotFoundError`, `SourceUnavailableError`, `InvalidInputError`, `InternalError`, `PersistenceUnavailableError`)
- Полные unit-тесты: [`tests/unit/test_models.py`](tests/unit/test_models.py)

### 2.3 Dual API (MCP + REST) ✅
- MCP-сервер (FastMCP): 4 инструмента ([`core/api/mcp_server.py`](core/api/mcp_server.py))
- REST API (FastAPI + OpenAPI): 5 эндпоинтов + /health + 3 admin ([`core/api/rest_server.py`](core/api/rest_server.py))
- Единый core-класс [`ODLService`](core/odl_service.py) — transport-agnostic, работает через [`ODLServiceProtocol`](core/odl_service_protocol.py)

### 2.4 Persistence-слой ✅
- PostgreSQL (asyncpg), 10+ таблиц, 8 Liquibase-миграций v001
- Репозитории: [`DocumentRepository`](core/persistence/repository/document_repo.py), [`ReferenceRepository`](core/persistence/repository/reference_repo.py), [`SectionRepository`](core/persistence/repository/section_repo.py), [`ChangeTrackingRepository`](core/persistence/repository/change_tracking_repo.py)
- QdrantStore: upsert, search, build_filter (payload-фильтрация), deactivate_sections ([`core/index/qdrant_store.py`](core/index/qdrant_store.py))

### 2.5 Ingest-пайплайн ✅
- `DocStructSplitter` — структурный чанкинг русских НПА
- `Embedder` — сменяемая модель (bge-m3 / paraphrase-multilingual-MiniLM)
- OCR: Yandex Vision + Tesseract + Stub
- Circuit Breaker + Progressive Backoff для внешних API

### 2.6 Адаптеры источников ✅
- [`SourceAdapter` Protocol](adapters/base/source_adapter.py) — 7 методов
- [`PravoAdapter`](adapters/pravo/) — production (реальная интеграция с publication.pravo.gov.ru) + stub (3 документа Минтруда)
- [`StubAdapter`](adapters/stub/stub_adapter.py) — демо-источник с 2 документами
- [`RSSAdapter`](adapters/base/rss_adapter.py) — базовый класс для RSS-источников

### 2.7 Инженерная культура ✅
- GitHub CI (ruff, mypy, pytest, coverage threshold 70%)
- Pre-commit (ruff, mypy, detect-secrets)
- Покрытие тестами ~78%
- `.env.example` / `.secrets.baseline`
- Docker Compose (Qdrant, Redis, PostgreSQL, LangFuse)
- Наблюдаемость: LangFuseTracer + FileFallbackTracer, структурированные логи, trace_id

---

## 3. Оценка соответствия expected_result.md

### 3.1 Три обязательных результата

| Результат | Статус | Комментарий |
|-----------|--------|-------------|
| **Spec + C4/ADR** | ✅ | Полная спецификация, 2 C4-диаграммы, 17 ADR |
| **Одна вертикаль end-to-end через архитектуру** (adapter → routing → contract) | ⚠️ | Архитектура верна, но **данные не проходят сквозной путь с корректным provenance**: legal_status = UNKNOWN, регионы/рубрики не заполнены, SourceAvailability не вычисляется |
| **Чистый репозиторий** | ⚠️ | Есть артефакты: `output/document_details.json`, hardcoded ID в скриптах, TODO-баги |

### 3.2 Первоочередные шаги

| Шаг из [`expected_result.md`](docs/reference/expected_result.md) | Путь в архитектуре | Статус | Что нужно |
|-----|---------------------|--------|-----------|
| **search → detail: ответ с цитатой, датой и юр-статусом (не UNKNOWN)** | Ingest → payload → Qdrant → filter → response | ⚠️ | `legal_status` не заполняется при инжесте (всегда `UNKNOWN`). `data_freshness` корректно берёт `valid_from or created_at` — это юридическая дата, а не дата инжеста |
| **Контекст (регион/рубрика) реально фильтрует** | SearchContext.region/topic → Qdrant payload filter | ⚠️ | Фильтры Qdrant настроены в `build_filter()`, но **регионы и рубрики не заполнены** в payload чанков и в PostgreSQL |
| **Источник недоступен → SOURCE_UNAVAILABLE** | Ingest health → payload метка `last_available` → check at query time | ❌ | `SourceAvailability` всегда `AVAILABLE`. Нет механизма детекции недоступности источника через TTL/пульс |
| **Структурированный ответ (поля + span-цитаты)** | DocumentDetail → Citation.section, span_start/end | ✅ | Реализовано в `get_document_detail()` |
| **Новое требование (другой охват, "не отдавать отменённое") впитывается** | Добавить payload filter по `legal_status != 'revoked'` → трогает Qdrant filter (край), не ядро | ⚠️ | Требует заполненного `legal_status` в payload. Архитектурно — край, трогает `build_filter()` |

---

## 4. Технический долг (что БЛОКИРУЕТ сквозной сценарий)

### 4.1 Блокеры сквозного сценария 🔴 P0

| # | Проблема | Описание | Файлы |
|---|----------|----------|-------|
| **E2E-1** | **legal_status = UNKNOWN при инжесте** | Ни StubAdapter, ни PravoAdapter (stub) не заполняют `legal_status` в `OfficialDocument`. Приходит `UNKNOWN` по умолчанию. Для сквозного сценария нужно хотя бы для stub-документов выставить `ACTIVE` | [`adapters/stub/stub_adapter.py`](adapters/stub/stub_adapter.py), [`adapters/pravo/adapter/stub/ingest.py`](adapters/pravo/adapter/stub/ingest.py) |
| **E2E-2** | **Регионы/рубрики не в payload** | Chunk'и в Qdrant не содержат `region_id`, `topic`, `organization` — Metadata Routing фильтрует по пустым полям. Нужно заполнять payload при инжесте | [`adapters/base/ingest_pipeline.py`](adapters/base/ingest_pipeline.py), [`core/index/qdrant_store.py`](core/index/qdrant_store.py) |
| **E2E-3** | **SourceAvailability не детектируется** | В ответе всегда `AVAILABLE`. Для честного `SOURCE_UNAVAILABLE` нужен механизм: TTL последнего успешного инжеста + метка в Qdrant payload | [`core/odl_service.py`](core/odl_service.py), [`core/models/models.py`](core/models/models.py) |
| **E2E-4** | **total_count неточный** | `len(results)` вместо реального подсчёта в Qdrant. Пагинация не работает для >1 страницы | [`core/odl_service.py`](core/odl_service.py) |
| **E2E-5** | **MCP SSE endpoint — неясен путь** | Клиент `scripts/mcp_list_tools.py` не может подключиться. Путь монтирования /mcp конфликтует | [`core/main.py:183`](core/main.py:183), [`TODO.md`](TODO.md) |

### 4.2 Инфраструктурные блокеры 🟡 P1

| # | Проблема | Описание | Файлы |
|---|----------|----------|-------|
| E2E-6 | **Redis health: всегда "unavailable"** | CacheClient lazy — `_available` не проверяется при `/health`. Нужен активный ping | [`core/api/rest_server.py:158`](core/api/rest_server.py:158), [`core/cache/__init__.py`](core/cache/__init__.py) |
| E2E-7 | **Tracing middleware падает с query params** | `dict(scope["query_string"].decode())` → ValueError. Нужен `parse_qsl` | [`core/api/rest_server.py:85`](core/api/rest_server.py:85) |
| E2E-8 | **Cache-aside не проверен** | Кэширование в `search_documents()` и `get_document_detail()` есть, но не протестировано end-to-end | [`core/odl_service.py`](core/odl_service.py) |

### 4.3 Инженерный долг 🔵 P2/P3

| # | Проблема | Приоритет |
|---|----------|-----------|
| TD-1 | C4-диаграммы в mermaid — нет экспорта в draw.io | P2 |
| TD-2 | `OfficialDocument.organization: str` vs `SearchResult.organization: list[str]` — несоответствие | P2 |
| TD-3 | Два источника истины для схемы БД: Liquibase + Python get-or-create | P2 |
| TD-4 | Hardcoded document IDs в pipeline-скриптах | P2 |
| TD-5 | Нет SLO-замеров (латентность, токен-бюджет, свежесть) | P2 |
| TD-6 | `output/document_details.json` — отладочный артефакт в репозитории | P2 |
| TD-7 | Stub PravoAdapter использует только 3 документа Минтруда | P3 |
| TD-8 | Нет мониторинга (Prometheus/Grafana) | P3 |
| TD-9 | Нет rate limiting | P3 |
| TD-10 | Единый процесс — точка отказа | P3 |

---

## 5. Соответствие требованиям original_task.md

| Требование | Статус | Комментарий |
|-----------|--------|-------------|
| Адаптер источника (шов) | ✅ | Protocol + 2 реализации. Добавление не трогает ядро |
| Каноническая модель | ✅ | 12 Pydantic моделей |
| Две оси времени | ✅ | Разделены: `data_freshness` = `valid_from` (юридическая дата), TTL = свежесть копии |
| Роутинг (source routing) | ⚠️ | **Metadata Routing** — верный подход, но данные в payload не заполнены |
| Входной контракт | ✅ | SearchContext с ортогональными полями |
| Контракт ответа + provenance | ✅ | SearchResponse + ConfidenceSignals + Citation |
| Холодный и горячий старт | ⚠️ | Cache-aside реализован, но health не проходит |
| Сигнал исхода | ⚠️ | retrieval_relevance есть, source_availability не детектируется |
| Gen-AI ready API | ✅ | MCP + OpenAPI |
| Вертикаль end-to-end | ⚠️ | Компоненты готовы, **данные не проходят с корректным provenance** (legal_status, регионы) |
| Второй источник-заглушка | ✅ | StubAdapter |
| Инженерная культура | ✅ | CI, тесты (78%), линтеры, pre-commit |
| Graceful degradation | ⚠️ | Для БД — да. Для источника — нет (SourceAvailability не детектируется) |
| Наблюдаемость | ✅ | Tracer + Logger + healthcheck |
| Mechanism/Policy | ✅ | ADR 1, 2, 7 — принцип зафиксирован |
| Токен-осознанность | ⚠️ | Пагинация есть. Token budget не измерен |

---

## 6. Оценка прогресса

| Категория | Вес (ТЗ) | Прогресс | Комментарий |
|-----------|---------|----------|-------------|
| Архитектура и переносимость | 35% | **~75%** | Metadata Routing — сильное решение. Минус: не все payload-данные заполняются при инжесте |
| Работающая вертикаль end-to-end | 20% | **~40%** | Query path работает, но provenance неполный: legal_status = UNKNOWN |
| Инженерная культура | 25% | **~85%** | Без изменений |
| Надёжность и SLO | 10% | **~40%** | Graceful degradation на источнике не реализован, кэш не подключён |
| Достоверность и ограничения | 10% | **~50%** | legal_status не заполнен, source_unavailable не детектируется |
| **Итого** | **100%** | **~60-65%** | **Основной долг — данные в Metadata Routing payload, а не архитектура** |

---

## 7. Ключевой вывод

**Архитектура (Metadata Routing) верна и переносима.** Сквозной сценарий **не работает** не из-за архитектурного gap, а из-за того, что **данные в Metadata Routing payload не заполнены**:

- `legal_status` = `UNKNOWN` → provenance неполный
- `region_id`/`topic` не в payload → фильтрация не работает
- `SourceAvailability` всегда `AVAILABLE` → graceful degradation не проверен

**Что не нужно делать:**
- Не добавлять SourceRouter — Metadata Routing через Qdrant payload-фильтрацию решает задачу переносимости. Это прямое применение принципа механизм/политика
- Не трогать адаптеры в query path — архитектура сознательно отделяет инжест (write) от поиска (read)
- Не расширять ширину (новые источники, OCR) — глубина одной вертикали важнее

**Что нужно для сквозного сценария:**
1. Заполнить `legal_status` при инжесте (stub-адаптеры → `ACTIVE`, production — парсить из XML)
2. Заполнить `region_id`, `topic`, `organization` в payload чанков — тогда Metadata Routing начнёт реально фильтровать
3. Реализовать детекцию недоступности источника (TTL последнего успешного инжеста → метка в payload)
4. Починить инфраструктурные блокеры: MCP mount path, Redis healthcheck, tracing middleware

После этого одна вертикаль (search → detail с цитатой, датой и `legal_status ≠ UNKNOWN`) заработает честно через архитектуру: `SourceAdapter (ingest) → Metadata Routing (Qdrant payload filter) → контракт ответа`.
