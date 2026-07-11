# Official Data Layer for AI Agents

Слой официальных данных для AI-агентов — предоставляет доступ к нормативно-правовым актам и официальным данным с полной трассируемостью источников.

[![CI](https://github.com/igorvolk1961/gov_data_layer/actions/workflows/ci.yml/badge.svg)](https://github.com/igorvolk1961/gov_data_layer/actions/workflows/ci.yml)

## Исходная постановка задачи
[`task/postanovka_gov_data_layer.md`](task/postanovka_gov_data_layer.md)

## Документация

| Документ | Описание |
|----------|----------|
| [`plans/SPEC.md`](plans/SPEC.md) | Полная спецификация: цель, границы, контракты, SLO, компромиссы |
| [`plans/plan.md`](plans/plan.md) | План разработки по фазам, архитектура Dual API, детальный дизайн |
| [`plans/context.md`](plans/context.md) | C4 Context — место слоя в экосистеме AI-агентов |
| [`plans/container.md`](plans/container.md) | C4 Container — внутренняя структура: MCP + REST + ODLService |
| [`plans/adr.md`](plans/adr.md) | Архитектурные решения (ADRs) |
| [`plans/data-structures-design.md`](plans/data-structures-design.md) | Дизайн структур данных и канонической модели |
| [`examples/SKILL.md`](examples/SKILL.md) | Пример Agent Skill — инструкция для AI-агента |

## Быстрый старт

```bash
# Поднять все сервисы
docker compose up -d

# Проверить health
curl http://localhost:8000/health

# Поиск документов (REST API)
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "налоговые льготы для ИП", "context": {"max_results": 5}}'

# Получить карточку документа
curl http://localhost:8000/api/v1/documents/doc-001
```

## Статус

Проект находится в стадии разработки в рамках тестового задания.

### Что реализовано
- ✅ Инфраструктура: Docker, CI, линтеры, типы
- ✅ Спецификация: SPEC.md, ADRs, C4-диаграммы
- ✅ Каноническая модель: 12 Pydantic-моделей с тестами
- ✅ StubAdapter: демо-источник с 2 документами
- ✅ Типизированные ошибки: 5 классов ошибок
- ✅ Tracer: LangFuseTracer + FileFallbackTracer

### В разработке
- 🔄 **Фаза 5**: Dual API — MCP-сервер + OpenAPI-сервер (FastAPI) поверх ODLService
- ⏳ Фаза 3: Адаптер pravo.gov.ru
- ⏳ Фаза 4: Локальный индекс (Qdrant + PostgreSQL)
- ⏳ Фаза 7: Кэш (Redis)
- ⏳ Фаза 8: Agent Skill
