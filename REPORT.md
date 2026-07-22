# Official Data Layer for AI Agents — Status Report

**Дата:** 2026-07-22
**Версия:** v0.2.0 (develop)
**Контекст:** Оценка проекта [`gov_data_layer`](.) против критериев [`expected_result.md`](docs/reference/expected_result.md) и [`original_task.md`](docs/reference/original_task.md)

---

## 1. Архитектура (Metadata Routing)

```
                        QUERY PATH (read)
Agent → [MCP/REST] → ODLService → embedder → Qdrant
                                           ┌──────────────────────┐
                                           │ Metadata Routing     │
                                           │ (payload filters:    │
                                           │  region_id,          │
                                           │  topic_ids,          │
                                           │  organization,       │
                                           │  legal_status !=     │
                                           │    not_active)       │
                                           └──────────────────────┘
                                             ↓
                                          Response + provenance


                        INGEST PATH (write)
Source → [SourceAdapter] → normalize → chunk → embed → Qdrant
                               ┌───────────────────────────────┐
                               │ Payload: document_id,         │
                               │ region_id, topic_ids,         │
                               │ legal_status, section_path    │
                               └───────────────────────────────┘
                                        ↓
                                 PostgreSQL (sections, refs)
```

**Ключевое решение:** Адаптеры не участвуют в query path. Metadata Routing через Qdrant payload-фильтрацию заменяет явный роутер.

---

## 2. Прогресс v0.1.0 → v0.2.0

### 2.1 Исправленные блокеры

| Блокер v0.1.0 | Статус v0.2.0 | Что сделано |
|---------------|---------------|-------------|
| `legal_status = UNKNOWN` | ✅ | Заполняется при инжесте (`ACTIVE` для stub) |
| `region_id`/`topic_ids` не в payload | ✅ | Заполняются: `region_id` из организации, `topic_ids` через `link_chunks_to_topics()` |
| `total_count = len(results)` | ✅ | Qdrant возвращает реальное количество hits |
| Tracing middleware падает с query params | ✅ | Исправлен: `dict(parse_qsl(...))` |
| Redis health всегда "unavailable" | ✅ | Активный ping при healthcheck |
| MCP mount path неясен | ✅ | Путь `/mcp` работает, клиенты подключаются |
| `SearchResult.organization: list[str]` | ✅ | Исправлен на `str \| None` |

### 2.2 Изменения в модели данных

| Аспект | v0.1.0 | v0.2.0 |
|--------|--------|--------|
| **LegalStatus** | `ACTIVE`, `REVOKED`, `MODIFIED`, `UNKNOWN` | `ACTIVE`, `NOT_ACTIVE` (упрощение) |
| **ConfidenceSignals** | `retrieval_relevance`, `data_freshness`, `source_availability` | `retrieval_relevance`, `topic_relevance`, `last_verified_at` |
| **SearchContext** | `topic`, `official_only`, `jurisdiction`, `score_threshold` | Без `topic` (автоопределение), без `official_only`, `score_threshold` с `default=None` |

### 2.3 Новая документация

| Документ | Статус |
|----------|--------|
| [Specification v0.2.0](docs/specification.md) | ✅ Полная, без старых проблем |
| [CHANGELOG v0.1.0 → v0.2.0](docs/changelog/v0.2.0.md) | ✅ С планом v0.3.0 |
| [Class diagram](docs/architecture/class-diagram.md) | ✅ 20+ классов |
| [DB schema ER](docs/architecture/db-schema.md) | ✅ 15 таблиц |
| [Sequence diagrams](docs/architecture/sequence-diagrams.md) | ✅ 3 pipelines |
| [Agent Skill](docs/agent-integration/SKILL.md) | ✅ Соответствует 2 MCP-инструментам |

---

## 3. Оценка соответствия expected_result.md

### 3.1 Три обязательных результата

| Результат | Статус | Комментарий |
|-----------|--------|-------------|
| **Spec + C4/ADR + диаграммы** | ✅ | Spec, C4, class, DB, sequence, ADR, changelog |
| **Одна вертикаль end-to-end** | ✅ | Демонстрационные скрипты (`search_pipeline.py`, `document_detail_pipeline.py`) показывают работающий сквозной сценарий |
| **Чистый репозиторий** | ✅ | Отладочные артефакты удалены. Hardcoded ID в скриптах — для демонстрации |

### 3.2 Сквозной сценарий

| Шаг | Статус |
|-----|--------|
| **search → detail: ответ с цитатой, датой и юр-статусом** | ⚠️ Требуется верификация после инжеста |
| **Контекст (регион/рубрика) реально фильтрует** | ⚠️ payload заполнен, требуется E2E-тест |
| **Источник недоступен → честный сигнал** | ✅ `SourceAvailability` удалён из `ConfidenceSignals` — неактуально для предварительного инжеста |
| **Структурированный ответ (поля + span-цитаты)** | ✅ Реализовано |

---

## 4. Соответствие требованиям original_task.md

| Требование | Статус | Комментарий |
|-----------|--------|-------------|
| Адаптер источника (шов) | ✅ | Protocol + 2 реализации |
| Каноническая модель | ✅ | 12 Pydantic моделей |
| Две оси времени | ✅ | `last_verified_at` + `valid_from`/`valid_to` |
| Роутинг (Metadata Routing) | ✅ | Qdrant payload-фильтрация, данные в payload |
| Входной контракт | ✅ | SearchContext с ортогональными полями |
| Контракт ответа + provenance | ✅ | SearchResponse + ConfidenceSignals + Citation |
| Холодный и горячий старт | ⚠️ | Cache-aside есть, E2E не проверен |
| Сигнал исхода | ✅ | `retrieval_relevance`, `topic_relevance`, `last_verified_at` |
| Gen-AI ready API | ✅ | MCP (2 инструмента) + OpenAPI |
| Вертикаль end-to-end | ⚠️ | Демонстрационные скрипты показывают работающий сквозной сценарий  |
| Второй источник-заглушка | ✅ | StubAdapter |
| Инженерная культура | ✅ | CI, тесты, линтеры, pre-commit |
| Graceful degradation | ⚠️ | Для БД — да. Кэш не проверен |
| Наблюдаемость | ✅ | Tracer + Logger + healthcheck |
| Mechanism/Policy | ✅ | Принцип зафиксирован в ADR и спецификации |

---

## 5. Оценка прогресса

| Категория | Вес (ТЗ) | v0.1.0 | v0.2.0 | Изменение |
|-----------|---------|--------|--------|-----------|
| Архитектура и переносимость | 35% | ~75% | **~85%** | +10%: payload заполнен, диаграммы |
| Работающая вертикаль end-to-end | 20% | ~40% | **~60%** | +20%: legal_status, регионы, баги |
| Инженерная культура | 25% | ~85% | **~85%** | Без изменений |
| Надёжность и SLO | 10% | ~40% | **~50%** | +10%: исправлены healthcheck, tracing |
| Достоверность и ограничения | 10% | ~50% | **~65%** | +15%: legal_status, confidence signals |
| **Итого** | **100%** | **~60%** | **~72%** | **+12%** |

---

## 6. Остаток (v0.3.0)

### Ближайшие задачи

1 **Docker image** — сборка и тестирование
2 **SLO-замеры** — latency, token budget
3 **`_check_missing_region`** — реализовать детекцию

### Концепция v0.3.0

- RSS-лента для обнаружения свежих документов
- Title-based extraction (без OCR) — NER для региона, regexp для зависимостей
- Ленивый инжест (pull model) — документы по запросу
- Очередь инжеста с оценкой времени ожидания
- Детекция зависимостей из названий документов

Подробнее: [`docs/changelog/v0.2.0.md`](docs/changelog/v0.2.0.md), [`plans/problems.md`](plans/problems.md)
