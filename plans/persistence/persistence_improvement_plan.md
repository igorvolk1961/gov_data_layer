# Implementation Plan: DatabaseClient Helpers & Repository Improvements

## Overview

Улучшение persistence-слоя без внедрения ORM. План покрывает 6 задач из раздела 5.2 анализа [`plans/orm_analysis.md`](plans/orm_analysis.md).

---

## Task 1: Generic `upsert()` helper в DatabaseClient

**Файл:** [`core/persistence/db_client.py`](core/persistence/db_client.py)

**Проблема:** Каждый репозиторий вручную пишет `INSERT ... ON CONFLICT ... DO UPDATE SET ...`. Это ~15 строк boilerplate на каждый upsert. В проекте 6+ upsert-запросов.

**Решение:** Добавить метод `upsert()` в [`DatabaseClient`](core/persistence/db_client.py:31):

```python
async def upsert(
    self,
    table: str,
    data: dict[str, Any],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    returning: str = "id",
) -> asyncpg.Record | None:
    """Generic upsert helper.

    Generates: INSERT INTO table (col1, col2, ...)
               VALUES ($1, $2, ...)
               ON CONFLICT (conflict_col1, conflict_col2)
               DO UPDATE SET col1 = EXCLUDED.col1, col2 = EXCLUDED.col2, ...
               RETURNING {returning}

    Args:
        table: Table name (validated against whitelist).
        data: Column-value mapping.
        conflict_columns: Columns that form the unique constraint.
        update_columns: Columns to update on conflict.
                        If None, updates all columns except conflict_columns.
        returning: Column to return (default: "id").

    Returns:
        Record with the requested column, or None if no row was affected.

    Raises:
        ValueError: If table name is not in the allowed whitelist.
    """
```

**Детали реализации:**
- Whitelist таблиц: `{"document", "document_section", "data_source", "document_type", "organization", "jurisdiction", "region", "topic", "rubric"}`
- Генерация параметризованного SQL с `$1, $2, ...` через `enumerate(data.values(), start=1)`
- `update_columns=None` → обновлять все колонки кроме `conflict_columns`
- Использовать `_ensure_connected()` как в существующих методах

**Потребители (будут переписаны):**
- [`document_repo.py:83-134`](core/persistence/repository/document_repo.py:83) — upsert документа
- [`reference_repo.py:231-258`](core/persistence/repository/reference_repo.py:231) — get-or-create reference tables
- [`section_repo.py:45-72`](core/persistence/repository/section_repo.py:45) — upsert секций

---

## Task 2: `transaction()` context manager в DatabaseClient

**Файл:** [`core/persistence/db_client.py`](core/persistence/db_client.py)

**Проблема:** В [`document_repo.py:83-146`](core/persistence/repository/document_repo.py:83) upsert документа и M:N записей выполняются в отдельных транзакциях. Если `_upsert_document_organizations()` упадёт, документ уже будет вставлен — частичное обновление.

**Решение:** Добавить `transaction()` context manager:

```python
@asynccontextmanager
async def transaction(self) -> AsyncIterator[DatabaseClient]:
    """Context manager for transactions.

    Usage::
        async with db.transaction():
            await db.execute("INSERT INTO ...")
            await db.execute("UPDATE ...")
        # auto-commit on success, auto-rollback on exception

    Raises:
        asyncpg.PostgresError: On query failure.
        ConnectionError: If not connected.
    """
    pool = await self._ensure_connected()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Temporarily replace self's methods to use this connection
            # OR: return a TransactionProxy that wraps the connection
            ...
```

**Вариант реализации:** Создать лёгкий `TransactionProxy`, который перехватывает вызовы `fetch`, `fetchrow`, `execute` и т.д., направляя их на конкретное соединение вместо пула.

```python
class TransactionProxy:
    """Wraps a connection to provide the same interface as DatabaseClient
    but within a transaction."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        return await self._conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        return await self._conn.fetchrow(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self._conn.execute(query, *args)
    # ... и т.д.
```

**Потребители:**
- [`document_repo.py:83-146`](core/persistence/repository/document_repo.py:83) — обернуть upsert документа + M:N в одну транзакцию
- [`odl_service.py:115-157`](core/odl_service.py:115) — `_persist_document()` (документ + секции)

---

## Task 3: `paginate()` helper в DatabaseClient

**Файл:** [`core/persistence/db_client.py`](core/persistence/db_client.py)

**Проблема:** Пагинация (LIMIT/OFFSET) используется в [`document_repo.py:340-387`](core/persistence/repository/document_repo.py:340), но нет единого helper'а. Каждый раз вручную пишется `LIMIT $n OFFSET $n+1`.

**Решение:** Добавить `paginated_fetch()`:

```python
async def paginated_fetch(
    self,
    query: str,
    *args: Any,
    limit: int,
    offset: int,
    timeout: float | None = None,
) -> list[asyncpg.Record]:
    """Execute a paginated query with LIMIT/OFFSET appended.

    The query should NOT include LIMIT/OFFSET — they are appended automatically.
    """
    paginated_query = f"{query.rstrip(';')} LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}"
    return await self.fetch(paginated_query, *args, limit, offset, timeout=timeout)
```

**Потребители:**
- [`document_repo.py:340-387`](core/persistence/repository/document_repo.py:340) — `search_documents()`

---

## Task 4: ModelMapper — утилита для Pydantic ↔ SQL маппинга

**Новый файл:** `core/persistence/mapper.py`

**Проблема:** В [`document_repo.py:261-300`](core/persistence/repository/document_repo.py:261) ручной маппинг `asyncpg.Record` → `OfficialDocument` (40 строк). Аналогично в `section_repo.py:92-104` и `change_tracking_repo.py:133-140`. Каждый маппинг — это N строк boilerplate, где N = количество полей модели.

**Решение:** Создать generic `ModelMapper`:

```python
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class ModelMapper(Generic[ModelT]):
    """Maps between asyncpg.Record and Pydantic models.

    Usage::
        mapper = ModelMapper(OfficialDocument, field_map={
            "external_id": "id",
            "source_source_id": ("source", "id"),
            "source_name": ("source", "name"),
            "doc_type_name": "document_type",
            "jurisdiction_name": "jurisdiction",
            "region_name": "region",
        })

        doc = mapper.from_row(row)  # Returns OfficialDocument
    """

    def __init__(
        self,
        model_cls: type[ModelT],
        field_map: dict[str, str | tuple[str, ...]],
    ) -> No
        self._model_cls = model_cls
        self._field_map = field_map

    def from_row(self, row: asyncpg.Record) -> ModelT:
        """Map a database row to a Pydantic model.

        Args:
            row: asyncpg.Record from a SELECT query.

        Returns:
            An instance of ModelT with fields populated from the row.
        """
        data: dict[str, Any] = {}
        for column_alias, model_field in self._field_map.items():
            value = row[column_alias]
            if isinstance(model_field, tuple):
                # Nested field: ("source", "id") → data["source"]["id"]
                parent, child = model_field
                if parent not in data:
                    data[parent] = {}
                data[parent][child] = value
            else:
                data[model_field] = value
        return self._model_cls(**data)

    def to_insert(self, model: ModelT) -> dict[str, Any]:
        """Convert a Pydantic model to a flat dict for INSERT.

        Flattens nested models: Source(id="...", name="...") → {"source_id": "...", "source_name": "..."}
        """
        ...
```

**Важно:** ModelMapper не должен покрывать 100% случаев. Для сложных маппингов (например, `_row_to_document` с дополнительными запросами organizations/topics) остаётся ручной код. ModelMapper — для простых случаев.

**Потребители:**
- [`section_repo.py:92-104`](core/persistence/repository/section_repo.py:92) — `get_sections()` маппинг
- [`change_tracking_repo.py:133-140`](core/persistence/repository/change_tracking_repo.py:133) — маппинг ModificationRecord
- [`change_tracking_repo.py:161-168`](core/persistence/repository/change_tracking_repo.py:161) — маппинг RevocationRecord

---

## Task 5: JSONB helper в DatabaseClient

**Файл:** [`core/persistence/db_client.py`](core/persistence/db_client.py)

**Проблема:** Сериализация/десериализация JSONB размазана по [`document_repo.py:390-408`](core/persistence/repository/document_repo.py:390) как модульные функции. Нет единого места для кастомизации (например, обработка `datetime`, `Decimal`).

**Решение:** Добавить в DatabaseClient статические методы:

```python
@staticmethod
def serialize_jsonb(value: dict[str, Any] | None) -> str | None:
    """Serialize dict to JSON string for JSONB column."""
    if not value:
        return None
    return json.dumps(value, default=str, ensure_ascii=False)


@staticmethod
def deserialize_jsonb(value: Any) -> dict[str, Any]:
    """Deserialize JSONB value from PostgreSQL to dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if isinstance(value, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
```

**Потребители:**
- [`document_repo.py:133`](core/persistence/repository/document_repo.py:133) — `_serialize_meta(doc.meta)` → `DatabaseClient.serialize_jsonb(doc.meta)`
- [`document_repo.py:299`](core/persistence/repository/document_repo.py:299) — `_deserialize_meta(row["meta"])` → `DatabaseClient.deserialize_jsonb(row["meta"])`
- Удалить модульные функции `_serialize_meta`, `_deserialize_meta`, `_ensure_datetime` из `document_repo.py`

---

## Task 6: Рефакторинг document_repo.py — вынести повторяющиеся JOIN

**Файл:** [`core/persistence/repository/document_repo.py`](core/persistence/repository/document_repo.py)

**Проблема:** Один и тот же SELECT с 5 JOIN повторяется в 3 методах:
- [`get_document_by_external_id()`](core/persistence/repository/document_repo.py:197) (строки 204-221)
- [`get_document_by_id()`](core/persistence/repository/document_repo.py:229) (строки 235-253)
- [`search_documents()`](core/persistence/repository/document_repo.py:340) (строки 353-374)

**Решение:** Вынести общий SELECT в константу или статический метод:

```python
_DOCUMENT_SELECT_COLUMNS = """
    d.id, d.external_id, d.title, d.url, d.summary,
    d.document_number, d.publish_id,
    d.ingest_date, d.valid_from, d.valid_to, d.publish_date,
    d.legal_status, d.meta,
    ds.source_id as source_source_id,
    ds.name as source_name,
    ds.url as source_url,
    ds.jurisdiction as source_jurisdiction,
    dt.name as doc_type_name,
    j.name as jurisdiction_name,
    r.name as region_name
"""

_DOCUMENT_FROM_JOIN = """
    FROM document d
    JOIN data_source ds ON ds.id = d.source_id
    LEFT JOIN document_type dt ON dt.id = d.document_type_id
    LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
    LEFT JOIN region r ON r.id = d.region_id
"""
```

**Потребители:** Все 3 SELECT-запроса в `document_repo.py` переписать через константы.

---

## Task 7: Тесты

### 7.1 Unit-тесты для DatabaseClient helpers

**Новый файл:** `tests/unit/test_db_client_helpers.py`

Использовать `AsyncMock` для `asyncpg.Pool` и `asyncpg.Connection`:

```python
@pytest.mark.asyncio
async def test_upsert_generates_correct_sql():
    """Verify that upsert() generates the expected SQL."""
    db = DatabaseClient(dsn="postgresql://test:test@localhost:5432/test")
    db._pool = AsyncMock(spec=asyncpg.Pool)

    conn = AsyncMock(spec=asyncpg.Connection)
    conn.fetchrow = AsyncMock(return_value=asyncpg.Record(**{"id": "some-uuid"}))
    db._pool.acquire = AsyncMock(return_value=conn)

    result = await db.upsert(
        table="document_type",
        data={"source_id": "s1", "external_id": "e1", "name": "Test"},
        conflict_columns=["source_id", "external_id"],
    )

    assert result["id"] == "some-uuid"
    # Verify SQL was generated correctly
    conn.fetchrow.assert_called_once()
    sql = conn.fetchrow.call_args[0][0]
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
```

### 7.2 Unit-тесты для ModelMapper

**В файле:** `tests/unit/test_db_client_helpers.py`

```python
def test_model_mapper_from_row():
    """Verify that ModelMapper correctly maps flat row to nested Pydantic model."""
    mapper = ModelMapper(
        OfficialDocument,
        field_map={
            "external_id": "id",
            "source_source_id": ("source", "id"),
            "source_name": ("source", "name"),
        },
    )
    row = MagicMock(spec=asyncpg.Record)
    row.__getitem__ = lambda self, key: {
        "external_id": "doc-123",
        "source_source_id": "pravo",
        "source_name": "Право РФ",
    }[key]

    doc = mapper.from_row(row)
    assert doc.id == "doc-123"
    assert doc.source.id == "pravo"
    assert doc.source.name == "Право РФ"
```

### 7.3 Интеграционные тесты

**Новый файл:** `tests/integration/test_persistence_helpers.py`

Тесты с реальным PostgreSQL (через testcontainers или существующий `metadata-db`):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_roundtrip():
    """Verify upsert + read via DatabaseClient helpers."""
    db = DatabaseClient(dsn=TEST_DSN)
    await db.connect()

    # Insert
    result = await db.upsert(
        table="document_type",
        data={"source_id": SOURCE_UUID, "external_id": "test-type", "name": "Test Type"},
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None

    # Read back
    row = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        result["id"],
    )
    assert row["name"] == "Test Type"

    # Upsert again (update)
    result2 = await db.upsert(
        table="document_type",
        data={"source_id": SOURCE_UUID, "external_id": "test-type", "name": "Updated Type"},
        conflict_columns=["source_id", "external_id"],
    )
    assert result2["id"] == result["id"]

    row2 = await db.fetchrow(
        "SELECT name FROM document_type WHERE id = $1::uuid",
        result2["id"],
    )
    assert row2["name"] == "Updated Type"

    await db.close()
```

---

## Порядок выполнения

| # | Задача | Зависимости | Файлы | Ожидаемый diff |
|---|---|---|---|---|
| 1 | `upsert()` helper | — | `db_client.py` | +~60 строк |
| 2 | `transaction()` context manager | — | `db_client.py` | +~50 строк |
| 3 | `paginate()` helper | — | `db_client.py` | +~15 строк |
| 4 | JSONB helpers | — | `db_client.py` | +~20 строк |
| 5 | ModelMapper | — | `core/persistence/mapper.py` (new) | +~100 строк |
| 6 | Рефакторинг document_repo.py | — | `document_repo.py` | -~40 строк (чистка дублирования) |
| 7 | Применение helpers в репозиториях | 1-6 | `document_repo.py`, `reference_repo.py`, `section_repo.py` | ~100 строк изменений |
| 8 | Тесты | 1-7 | `tests/unit/test_db_client_helpers.py`, `tests/integration/test_persistence_helpers.py` | +~300 строк |

**Общий объём:** ~500 строк нового кода, ~100 строк удалённого boilerplate.

---

## Критерии готовности

1. Все существующие тесты проходят без изменений
2. `upsert()` покрыт unit-тестами (3+ кейса: insert, update, invalid table)
3. `transaction()` покрыт unit-тестом (commit) и integration-тестом (rollback on exception)
4. `paginate()` покрыт unit-тестом
5. JSONB helpers покрыты unit-тестами
6. ModelMapper покрыт unit-тестами (flat mapping, nested mapping, edge cases)
7. Репозитории переписаны на helpers, старый код удалён
8. Интеграционные тесты подтверждают roundtrip через реальную БД
