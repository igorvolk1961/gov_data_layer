# Official Data Layer for AI Agents

Слой официальных данных для AI-агентов — предоставляет доступ к нормативно-правовым актам и официальным данным с полной трассируемостью источников.

[![CI](https://github.com/igorvolk1961/gov_data_layer/actions/workflows/ci.yml/badge.svg)](https://github.com/igorvolk1961/gov_data_layer/actions/workflows/ci.yml)

## Исходная постановка задачи
[`task/postanovka_gov_data_layer.md`](docs/reference/original_task.md)

# Промежуточный отчет о проделанной работе и техническом долге

**Дата:** 2026-07-15
**Автор:** Architect Mode
**Контекст:** Анализ проекта gov_data_layer (Official Data Layer for AI Agents)

---

## 1. Что сделано (за 5-6 рабочих дней)

### 1.1 Архитектура и спецификация ✅
| Компонент | Статус |
|-----------|--------|
| C4 Context diagram | ✅ Готов |
| C4 Container diagram | ✅ Готов |
| SPEC.md — полная спецификация | ✅ Готов |
| ADR — 17 архитектурных решений | ✅ Готов |
| Планы persistence-слоя (5 файлов) | ✅ Готовы |
| План Phase 6 (end-to-end вертикаль) | ✅ Готов |
| План Phase 7 (кэш/резильентность) | ✅ Готов |
| Пример Agent Skill (SKILL.md) | ✅ Черновик |

### 1.2 Каноническая модель данных ✅
- 12 Pydantic v2 моделей: `OfficialDocument`, `SearchContext`, `SearchResult`, `SearchResponse`, `DocumentDetail`, `ConfidenceSignals`, `Citation`, `TopicNode`, `TocNode`, `DocumentChunk`, `Source`, `LegalStatus`, `SourceAvailability`
- Типизированные ошибки: 5 классов (`NotFoundError`, `SourceUnavailableError`, `InvalidInputError`, `InternalError`, `PersistenceUnavailableError`)
- Полные unit-тесты моделей: [`tests/unit/test_models.py`](tests/unit/test_models.py) (24K)

### 1.3 Адаптеры источников ✅
| Адаптер | Статус | Описание |
|---------|--------|----------|
| `SourceAdapter` Protocol | ✅ | 7 методов: search, get, normalize, ingest, list_topics, get_toc, get_content |
| `RSSAdapter` (ABC) | ✅ | Базовый класс для RSS-источников: fetch_feed, parse_feed, retry с backoff |
| `PravoAdapter` (production) | ✅ | Реальная интеграция с publication.pravo.gov.ru |
| `PravoAdapter` (stub) | ✅ | 3 фиксированных документа Минтруда для демонстрации |
| `StubAdapter` | ✅ | Демо-источник с 2 документами, изоляция шва адаптера |
| `OCRProvider` Protocol | ✅ | Yandex Vision, Tesseract, Stub — сменяемый OCR |

### 1.4 Dual API ✅
| Интерфейс | Статус | Технология |
|-----------|--------|------------|
| MCP-сервер | ✅ | FastMCP, 4 инструмента: search_documents, get_document_detail, list_topics, get_toc |
| REST API (OpenAPI) | ✅ | FastAPI, те же 4 эндпоинта + /health |
| Единый core-класс ODLService | ✅ | Transport-agnostic бизнес-логика |
| Swagger UI | ✅ | Автоматически на /docs |

### 1.5 Ingest Pipeline ✅
| Компонент | Статус |
|-----------|--------|
| DocStructSplitter (smart_chunker) | ✅ | Структурный чанкинг русских НПА |
| Embedder (bge-m3 / paraphrase-multilingual-MiniLM) | ✅ | Сменяемая модель эмбеддингов |
| OCR: Yandex Vision + Tesseract + Stub | ✅ | 3 реализации OCRProvider |
| Circuit Breaker + Progressive Backoff | ✅ | Для внешних API и БД |

### 1.6 Persistence-слой ✅
| Компонент | Статус |
|-----------|--------|
| PostgreSQL схема (Liquibase, 10+ таблиц) | ✅ | 8 миграций v001 |
| DatabaseClient (asyncpg pool) | ✅ | Lazy connect, healthcheck, graceful shutdown |
| Репозитории: DocumentRepository | ✅ | Upsert с ON CONFLICT, COALESCE |
| Репозитории: ReferenceRepository | ✅ | Get-or-create, whitelist-валидация |
| Репозитории: SectionRepository | ✅ | Иерархия разделов, self-referencing FK |
| Репозитории: ChangeTrackingRepository | ✅ | История изменений + анализ фактов |
| ModelMapper | ✅ | Pydantic ↔ SQL маппинг |
| Стратегия отказа БД | ✅ | Fail-fast на старте, graceful degradation в API, Circuit Breaker в инжесте |

### 1.9 Vector Store Qdrant ✅
| Компонент | Статус |
|-----------|--------|
| QdrantStore — `upsert_chunks()` | ✅ | Запись чанков с эмбеддингами и payload |
| QdrantStore — `search()` | ✅ | Векторный поиск с payload-фильтрами |
| QdrantStore — `build_filter()` | ✅ | Фильтр `not_actual_since IS EMPTY OR > now()` |
| QdrantStore — `deactivate_sections()` | ✅ | Установка not_actual_since на чанки |
| QdrantStore — `_payload_to_chunk()` | ✅ | Обратное преобразование payload в модель |
| Payload index: not_actual_since | ✅ | Числовой индекс для фильтрации |

### 1.7 Инженерная культура ✅
| Компонент | Статус |
|-----------|--------|
| GitHub CI (ruff, mypy, pytest) | ✅ | Порог покрытия 70% |
| Pre-commit (ruff, mypy, detect-secrets) | ✅ | |
| Текущее покрытие тестами | ✅ | 78% |
| .env.example / .secrets.baseline | ✅ | |
| Docker Compose (Qdrant, Redis, PostgreSQL, LangFuse) | ✅ | |
| Makefile / lint-test.bat / test-fast.bat | ✅ | |

### 1.8 Наблюдаемость ✅
| Компонент | Статус |
|-----------|--------|
| Tracer (LangFuseTracer + FileFallbackTracer) | ✅ |
| Структурированные логи | ✅ |
| Сквозной идентификатор запроса (trace_id) | ✅ |
| Health endpoint (/health) | ✅ |

---

## 2. Технический долг (Tech Debt)

### 2.1. Критический долг ⚠️

| #    | Проблема | Описание | Статус | Файлы |
|------|----------|----------|--------|-------|
| TD-2 | **QdrantStore: hybrid_search** | `upsert_chunks`, `search`, `build_filter` работают. Нет dense+sparse. | ⚠️ | [`core/index/qdrant_store.py`](core/index/qdrant_store.py) |
| TD-3 | **Кэш (Redis) не используется** | CacheClient создаётся, но не передаётся в ODLService методы кэширования. | ❌ | [`core/cache/`](core/cache/), [`core/odl_service.py`](core/odl_service.py) |
| TD-13 | **End-to-end query pipeline не собран** | Query → фильтры → гибридный поиск → реранкинг → сборка ответа. | ❌ | TD-2, TD-12 |

### 2.2. Долг функциональности 🔶

| # | Проблема | Описание | Статус | Зависимости |
|---|----------|----------|--------|-------------|
| TD-6 | **Рубрикатор не заполнен данными** | Таблица `rubric` пуста. Нужен государственный классификатор социальных услуг. | ❌ | PostgreSQL |
| TD-7 | **Таблица регионов не заполнена** | Нет государственного классификатора регионов. | ❌ | PostgreSQL |
| TD-9 | **Семантический анализ разделов** | Regexp-паттерны для русских НПА. Stub + инфраструктура готовы. | ⚠️ Stub | TD-8 |
| TD-10 | **Определение рубрик документа** | LLM или векторная близость. | ❌ | TD-6 |
| TD-13 | **End-to-end query pipeline не собран** | Query → фильтры → гибридный поиск → реранкинг → сборка ответа. | ❌ | TD-2, TD-12 |
| TD-14 | **MCP/REST endpoints не связаны с ODLService** | Используются заглушки вместо реального сервиса. | ❌ | TD-13 |
| TD-15 | **Jurisdiction и region не сохраняются** | Поля есть в модели, но не пишутся в БД. | ❌ | TD-8 |

### 2.3. Инженерный долг 🛠️

| # | Проблема | Описание |
|---|----------|----------|
| TD-16 | **C4-диаграммы в mermaid, не в draw.io** | Нужен экспорт для читаемого вида. |
| TD-17 | **Code Review всей кодовой базы** | 106 файлов, ~20K строк. Не было комплексного review. |
| TD-18 | **SKILL.md — черновик** | Требует доработки. |
| TD-19 | **Нет SLO-замеров** | Латентность, токен-бюджет, свежесть не измерены. |
| TD-20 | **Нет нагрузочного тестирования** | Graceful degradation не проверен под нагрузкой. |
| TD-21 | **Нет документации по развёртыванию** | docker-compose есть, но нет пошагового guide. |

### 2.4. Архитектурный риск 🏗️

| # | Проблема | Описание |
|---|----------|----------|
| TD-23 | **Одна точка отказа — ODLService** | При падении процесса теряются и REST, и MCP. |
| TD-24 | **Нет мониторинга и алертинга** | Наблюдаемость есть, но нет метрик для Prometheus/Grafana. |
| TD-25 | **Нет rate limiting** | API не защищён от abuse. |

---

## 3. Соответствие требованиям задания

| Требование | Статус | Комментарий |
|-----------|--------|-------------|
| Адаптер источника (шов) | ✅ | SourceAdapter Protocol, StubAdapter демонстрирует |
| Каноническая модель | ✅ | OfficialDocument + SearchContext + SearchResult + DocumentDetail |
| Две оси времени | ✅ | created_at (свежесть копии) + valid_from/valid_to (юр. статус) |
| Роутинг запроса к источнику | ❌ TD-3 | Не реализован (заглушка) |
| Структурированный входной контракт | ✅ | SearchContext со всеми полями |
| Контракт ответа | ✅ | SearchResponse + ConfidenceSignals + Citation.section |
| Холодный и горячий старт | ❌ TD-5 | Кэш (Redis) создан, но не используется |
| Сигнал исхода (нашёл/не нашёл) | ⚠️ | ConfidenceSignals есть, но retrieval_relevance не вычисляется (нужен query pipeline TD-13) |
| Gen-AI ready API | ✅ | MCP (FastMCP) + OpenAPI (FastAPI) |
| Вертикаль end-to-end | ❌ TD-13 | Отдельные компоненты готовы, но pipeline не собран |
| Второй источник-заглушка | ✅ | StubAdapter работает |
| Инженерная культура | ✅ | CI, тесты (78%), линтеры, pre-commit |
| Graceful degradation | ⚠️ | Для БД — да (TD-5 решён). Для источника — нет. |
| Структурированные логи | ✅ | Tracer + Logger |
| Модель-агностичность | ✅ | Сменяемые OCR, embedder, LLM |
| Токен-осознанность | ⚠️ | Пагинация (offset+max_results) есть. Token budget не измерен. |
| Mechanism/Policy разделение | ✅ | ADR 1, ADR 2, ADR 7 |

---

## 4. Итоговая оценка прогресса

**Общий прогресс:** ~65-70% от целевого состояния

| Категория | Вес (из ТЗ) | Прогресс |
|-----------|------------|----------|
| Архитектура и переносимость | 35% | ~80% |
| Работающая вертикаль end-to-end | 20% | ~40% |
| Инженерная культура | 25% | ~85% |
| Надёжность и SLO | 10% | ~50% |
| Достоверность и ограничения | 10% | ~60% |

**Ключевой вывод:** Архитектурная база прочная. Основной долг — в сборке end-to-end пайплайна (TD-2, TD-3, TD-5, TD-13) и наполнении данными (TD-6, TD-7).
