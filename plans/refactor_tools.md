# Рефакторинг: замена `get_grounded_answer` на `list_topics` + `get_toc`

## Мотивация

`get_grounded_answer` дублирует `search_official_sources` по сути — оба ищут по запросу
и возвращают структурированный ответ. Разница только в степени агрегации, что сбивает
агента с толку.

Вместо этого добавляем два инструмента, которые **расширяют возможности** агента:

- **Рубрикатор** — агент может исследовать иерархию тем/рубрик, чтобы точнее
  фильтровать поиск. Агент изначально не знает рубрики, по которым может задавать
  фильтры.
- **Оглавление** — агент может навигироваться по структуре больших документов
  (кодексы, уставы, многостраничные НПА).

## Изменения

### 1. [`core/models/models.py`](../core/models/models.py)

**Удалить:**
- `GroundedAnswer` — полностью

**Добавить:**

```python
class TopicNode(BaseModel):
    """Узел иерархического рубрикатора."""
    id: str = Field(description="Уникальный идентификатор рубрики")
    name: str = Field(description="Название рубрики")
    parent_id: str = Field(description="ID родительской рубрики")
    description: str | None = Field(default=None, description="Описание рубрики")
    child_count: int = Field(default=0, description="Количество дочерних рубрик")
    document_count: int = Field(default=0, description="Количество документов в рубрике")

class TocNode(BaseModel):
    """Узел оглавления документа."""
    id: str = Field(description="Идентификатор раздела")
    document_id: str = Field(description="ID документа")
    title: str = Field(description="Заголовок раздела")
    parent_id: str = Field(description="ID родительского раздела")
    level: int = Field(ge=0, description="Уровень вложенности (0 = корень)")
    child_count: int = Field(default=0, description="Количество дочерних разделов")
```

### 2. [`adapters/base/__init__.py`](../adapters/base/__init__.py)

**Удалить:**
- Импорт `GroundedAnswer`
- Метод `get_grounded_answer()` из протокола

**Не добавлять** `list_topics` и `get_toc` — они реализуются в роутере/индексе (SQLite),
не в адаптерах источников.

### 3. [`core/api/__init__.py`](../core/api/__init__.py)

Обновить TODO-список инструментов:

```python
# TODO: Phase 5 — implement MCP server with tools:
#   - search_official_sources(query, context)
#   - get_source(source_id)
#   - list_topics(parent_id, query)
#   - get_toc(document_id, section_id)
```

### 4. [`core/router/__init__.py`](../core/router/__init__.py)

Обновить TODO:

```python
# TODO: Phase 5 — implement router logic:
#   - route search to appropriate adapters
#   - route list_topics to topic index (SQLite)
#   - route get_toc to document structure index (SQLite)
```

### 5. [`SPEC.md`](../SPEC.md)

**Раздел 3.5 Gen-AI ready API** — заменить список инструментов:

```markdown
Инструменты MCP-сервера:

1. `search_official_sources(query, context)` — компактные процитированные попадания
2. `get_source(source_id)` — полная карточка/текст акта
3. `list_topics(parent_id, query)` — исследование иерархического рубрикатора
4. `get_toc(document_id, section_id)` — навигация по оглавлению больших документов
```

**Токен-бюджет ответа** — обновить:

```markdown
- `search_official_sources`: до 10 результатов, каждый до 500 токенов
- `get_source`: до 4000 токенов (полный текст акта)
- `list_topics`: до 50 рубрик, каждая до 100 токенов
- `get_toc`: до 50 разделов, каждый до 100 токенов
```

### 6. [`plan.md`](../plan.md)

**Фаза 2** — обновить список моделей:
- Убрать `GroundedAnswer` из списка
- Добавить `TopicNode`, `TocNode`

**Фаза 4** — уточнить про SQLite:
- Иерархический рубрикатор (темы, регионы, ведомства с parent-child)
- Хранение структуры документов (TOC)

**Фаза 5** — обновить список инструментов MCP:
- Убрать `get_grounded_answer`
- Добавить `list_topics`, `get_toc`

### 7. [`adapters/stub/`](../adapters/stub/) — StubAdapter

При реализации StubAdapter `get_grounded_answer` не нужен.

### 8. [`examples/SKILL.md`](../examples/SKILL.md)

При написании Agent Skill описать новые инструменты вместо `get_grounded_answer`.

## Сводка изменений по файлам

| Файл | Что меняем |
|------|-----------|
| `core/models/models.py` | Удалить `GroundedAnswer`. Добавить `TopicNode`, `TocNode`. |
| `core/models/__init__.py` | Обновить `__all__`. |
| `adapters/base/__init__.py` | Удалить импорт `GroundedAnswer`. Удалить `get_grounded_answer()`. |
| `core/api/__init__.py` | Обновить TODO. |
| `core/router/__init__.py` | Обновить TODO. |
| `SPEC.md` | Раздел 3.5: список инструментов + токен-бюджет. |
| `plan.md` | Фазы 2, 4, 5. |
