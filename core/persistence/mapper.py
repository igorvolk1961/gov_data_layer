"""ModelMapper — generic utility for mapping between asyncpg.Record and Pydantic models.

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

from __future__ import annotations

from typing import Any, Generic, TypeVar, cast

import asyncpg
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

# A field map entry maps a column alias (SQL result key) to either:
# - A simple field name:  "external_id" → "id"
# - A nested field path:  "source_name" → ("source", "name")
FieldMap = dict[str, str | tuple[str, ...]]


class ModelMapper(Generic[ModelT]):
    """Maps between asyncpg.Record and Pydantic models.

    ``field_map`` defines how SQL column aliases map to model fields.
    Simple fields map directly; nested fields use a tuple path
    (e.g. ``("source", "id")`` → ``data["source"]["id"]``).

    The mapper is intentionally limited to straightforward cases.
    Complex mappings (e.g. with additional sub-queries for
    organizations/topics) should remain as hand-written code.
    """

    def __init__(
        self,
        model_cls: type[ModelT],
        field_map: FieldMap,
    ) -> None:
        self._model_cls = model_cls
        self._field_map = field_map

    def from_row(self, row: asyncpg.Record) -> ModelT:
        """Map a database row to a Pydantic model instance.

        Args:
            row: asyncpg.Record from a SELECT query.

        Returns:
            An instance of ``ModelT`` with fields populated from the row.
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
        """Convert a Pydantic model to a flat dict suitable for INSERT.

        Flattens nested Pydantic models into column aliases using the
        reverse of ``field_map``::

            Source(id="src1", name="Source Name")
            → {"source_source_id": "src1", "source_name": "Source Name"}

        Non-Pydantic nested values (e.g. plain dicts, lists) are
        serialized via ``DatabaseClient.serialize_jsonb()`` to avoid
        circular imports; callers may override serialization as needed.

        Args:
            model: A Pydantic model instance.

        Returns:
            Flat dict keyed by column aliases.
        """
        from core.persistence.db_client import DatabaseClient

        result: dict[str, Any] = {}
        for column_alias, model_field in self._field_map.items():
            if isinstance(model_field, tuple):
                # Nested field: ("source", "id") → model.source.id
                parent, child = model_field
                parent_val = getattr(model, parent, None)
                if isinstance(parent_val, BaseModel):
                    value = getattr(parent_val, child, None)
                elif isinstance(parent_val, dict):
                    value = parent_val.get(child)
                else:
                    value = None
            else:
                value = getattr(model, model_field, None)

            # Serialize non-trivial nested objects as JSONB
            if value is not None and not isinstance(value, (str, int, float, bool, type(None))):
                if isinstance(value, BaseModel):
                    value = value.model_dump()
                if isinstance(value, (dict, list)):
                    value = DatabaseClient.serialize_jsonb(
                        value if isinstance(value, dict) else cast("dict[str, Any]", value)
                    )

            result[column_alias] = value

        return result
