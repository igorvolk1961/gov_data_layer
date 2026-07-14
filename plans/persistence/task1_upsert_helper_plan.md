# Task 1: Generic `upsert()` helper в DatabaseClient

## Цель

Добавить generic-метод `upsert()` в класс [`DatabaseClient`](core/persistence/db_client.py:31), чтобы устранить дублирование `INSERT ... ON CONFLICT ... DO UPDATE SET ...` в репозиториях.

---

## 1. Изменения в `core/persistence/db_client.py`

### 1.1. Добавить константу whitelist таблиц

```python
# Таблицы, разрешённые для upsert (защита от SQL-инъекций через table name)
_UPSERT_ALLOWED_TABLES: frozenset[str] = frozenset({
    "document", "document_section", "data_source",
    "document_type", "organization", "jurisdiction",
    "region", "topic", "rubric",
})
```

### 1.2. Добавить метод `upsert()` в класс `DatabaseClient`

**Сигнатура:**

```python
async def upsert(
    self,
    table: str,
    data: dict[str, Any],
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    returning: str = "id",
) -> asyncpg.Record | None:
```

**Логика генерации SQL:**

1. **Валидация table name:** проверить `table in _UPSERT_ALLOWED_TABLES`, иначе `ValueError`
2. **Экранирование имён колонок:** использовать `asyncpg`-совместимые идентификаторы (кавычки не требуются для простых имён)
3. **Генерация параметров:** `$1, $2, ..., $N` через `enumerate(data.values(), start=1)`
4. **Определение update_columns:**
   - Если `update_columns is None` → все колонки из `data.keys()` кроме `conflict_columns`
   - Иначе → только указанные колонки
5. **Формирование SQL:**
   ```sql
   INSERT INTO {table} (col1, col2, ...)
   VALUES ($1, $2, ...)
   ON CONFLICT (conflict_col1, conflict_col2)
   DO UPDATE SET col1 = EXCLUDED.col1, col2 = EXCLUDED.col2, ...
   RETURNING {returning}
   ```
6. **Выполнение:** через `_ensure_connected()` → `pool.acquire()` → `conn.fetchrow()`

**Пограничные случаи:**
- Пустой `data` → `ValueError("data must not be empty")`
- Пустой `conflict_columns` → `ValueError("conflict_columns must not be empty")`
- Колонка в `update_columns`, которой нет в `data` → `ValueError`
- `returning` не в `data` и не является служебной колонкой (id) — допустимо, т.к. `RETURNING id` не обязан быть в data

---

## 2. Потребители (будут переписаны в Task 7, НЕ в этом)

| Файл | Строки | Текущий код | После рефакторинга |
|---|---|---|---|
| [`document_repo.py`](core/persistence/repository/document_repo.py) | 83-134 | Ручной INSERT ... ON CONFLICT с 16 параметрами | `await self._db.upsert("document", data={...}, conflict_columns=["external_id"])` |
| [`reference_repo.py`](core/persistence/repository/reference_repo.py) | 231-258 | Два варианта (с weight и без) ручного upsert | `await self._db.upsert(table, data={...}, conflict_columns=["source_id", "external_id"])` |
| [`section_repo.py`](core/persistence/repository/section_repo.py) | 45-72 | Ручной INSERT ... ON CONFLICT с подзапросом для parent_id | `await self._db.upsert("document_section", data={...}, conflict_columns=["document_id", "external_id"])` |

**Важно:** Рефакторинг потребителей — это **Task 7**, не входит в объём Task 1.

---

## 3. Тесты (Task 8, но план для Task 1)

### 3.1. Unit-тесты (в `tests/unit/test_db_client_helpers.py`)

1. **`test_upsert_generates_correct_sql`** — проверить, что SQL содержит `INSERT`, `ON CONFLICT`, `DO UPDATE`, `RETURNING`
2. **`test_upsert_insert_mode`** — verify, что при отсутствии конфликта возвращается новая запись
3. **`test_upsert_update_mode`** — verify, что при конфликте обновляются поля
4. **`test_upsert_invalid_table_raises`** — `ValueError` для таблицы не из whitelist
5. **`test_upsert_empty_data_raises`** — `ValueError` для пустого data
6. **`test_upsert_empty_conflict_columns_raises`** — `ValueError` для пустого conflict_columns
7. **`test_upsert_update_columns_subset`** — обновляются только указанные колонки
8. **`test_upsert_custom_returning`** — `RETURNING` с кастомной колонкой

### 3.2. Интеграционные тесты (в `tests/integration/test_persistence_helpers.py`)

1. **`test_upsert_roundtrip`** — insert → read → upsert (update) → verify updated

---

## 4. Критерии готовности Task 1

- [x] Метод `upsert()` добавлен в [`DatabaseClient`](core/persistence/db_client.py:31)
- [x] Whitelist таблиц защищает от произвольных table name
- [x] Генерация параметризованного SQL корректна
- [x] `update_columns=None` обновляет все колонки кроме conflict_columns
- [x] Unit-тесты покрывают: insert, update, invalid table, empty data, empty conflict_columns, custom update_columns, custom returning
- [x] Все существующие тесты проходят (регрессия)
- [x] Ни один репозиторий ещё не переписан (это Task 7)

---

## 5. Порядок выполнения в Code mode

1. Открыть [`core/persistence/db_client.py`](core/persistence/db_client.py)
2. Добавить `_UPSERT_ALLOWED_TABLES` константу после `_COMMAND_TIMEOUT`
3. Добавить метод `upsert()` в класс `DatabaseClient` (после метода `execute`, перед `executemany`)
4. Создать файл `tests/unit/test_db_client_helpers.py` с unit-тестами
5. Запустить существующие тесты для проверки регрессии: `pytest tests/unit/ -x -q`
6. Запустить новые тесты: `pytest tests/unit/test_db_client_helpers.py -x -v`

---

## 6. Риски и замечания

- **COALESCE-логика в document_repo.py** (строки 101-112): текущий upsert документа использует `COALESCE(EXCLUDED.x, document.x)` для некоторых полей. Generic `upsert()` не поддерживает кастомные выражения в SET — это будет решаться в Task 7 через ручную настройку `update_columns` или оставлением части ручного SQL.
- **Подзапрос в section_repo.py** (строка 52-53): `parent_id` вычисляется через подзапрос. Generic `upsert()` не поддерживает выражения в VALUES — это останется ручным кодом.
- **Имена колонок:** предполагаются простые (без кавычек, спецсимволов). Если появятся колонки с зарезервированными словами — потребуется экранирование через `asyncpg` (но в текущей схеме таких нет).
