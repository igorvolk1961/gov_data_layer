# План: автоопределение рубрик по запросу

## Идея

Убрать `topic` из входных параметров API/SearchContext. Вместо явной фильтрации — на лету определять релевантные запросу рубрики через семантический поиск в коллекции `topics`.

## Поток

```
запрос ("государственные пособия гражданам имеющим детей")
  → Embedder.embed_query(query)
  → QdrantStore.search_topics(query_embedding, limit=3, score_threshold=0.3)
  → [uuid1, uuid2, uuid3]
  → ctx.topic = [uuid1, uuid2, uuid3]
  → QdrantStore.search(query_embedding, context=ctx)  # с фильтром topic_ids
```

## Детальные изменения

### Шаг 1: SearchContext — убрать topic

**Файл**: [`core/models/models.py`](core/models/models.py:229-234)

Удалить поле `topic` из класса `SearchContext`.

### Шаг 2: MCP API — убрать topic

**Файл**: [`core/api/mcp_server.py`](core/api/mcp_server.py:65)

Удалить параметр `topic` из инструмента `search_documents`. Убрать `topic=topic` из конструктора `SearchContext`.

### Шаг 3: REST API — убрать topic

**Файл**: [`core/api/rest_server.py`](core/api/rest_server.py)

- Удалить `topic` из `SearchRequest` (строка 38)
- Убрать `topic` из `SearchContext()` (строка 205)
- Убрать `topic` из `get_document_detail` (строка 225)

### Шаг 4: ODLService — добавить автоопределение рубрик

**Файл**: [`core/odl_service.py`](core/odl_service.py:289-300)

Вставить между эмбеддингом запроса и поиском в Qdrant:

```python
# Определяем релевантные рубрики по семантике запроса
_auto_topics: list[str] = []
try:
    _topic_matches = await self._qdrant.search_topics(
        query_embedding=query_vector,
        limit=3,
        score_threshold=0.3,
    )
    _auto_topics = [m["topic_id"] for m in _topic_matches]
    if _auto_topics:
        ctx.topic = _auto_topics  # устанавливаем для фильтрации
except Exception:
    pass  # graceful degradation — без фильтрации по рубрикам
```

### Шаг 5: Удалить явную фильтрацию topic_ids из QdrantStore.search()

**Файл**: [`core/index/qdrant_store.py`](core/index/qdrant_store.py:381-387)

Удалить блок filter по `topic_ids`. Фильтр останется в коде, но будет срабатывать только если `context.topic` установлен — а он теперь устанавливается автоматически на шаге 4.

На самом деле код фильтра (строки 381-387) **не нужно удалять** — он просто не будет срабатывать если `context.topic = None`. А на шаге 4 мы его устанавливаем. Так что фильтр как раз и будет использоваться для авто-рубрик.

### Итоговая схема

```mermaid
flowchart LR
    A[Запрос пользователя] --> B[Embedder.embed_query]
    B --> C[query_vector]
    C --> D[QdrantStore.search_topics\nколлекция 'topics']
    D --> E[[uuid1, uuid2, uuid3]\nрелевантные рубрики]
    E --> F[ctx.topic = ...]
    F --> G[QdrantStore.search\nс фильтром topic_ids]
    G --> H[Результаты, отфильтрованные\nпо рубрикам]
```

### Файлы изменений

| Файл | Изменение |
|------|-----------|
| [`core/models/models.py`](core/models/models.py:229) | Удалить `topic` из `SearchContext` |
| [`core/api/mcp_server.py`](core/api/mcp_server.py:65) | Убрать параметр `topic` |
| [`core/api/rest_server.py`](core/api/rest_server.py:38,205,225) | Убрать `topic` из `SearchRequest` и эндпоинтов |
| [`core/odl_service.py`](core/odl_service.py:289-300) | Добавить `search_topics` по запросу, установить `ctx.topic` |
