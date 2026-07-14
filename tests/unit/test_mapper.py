"""Unit tests for ModelMapper."""

from __future__ import annotations

from pydantic import BaseModel

from core.persistence.mapper import ModelMapper

# --- Test models ---


class SubModel(BaseModel):
    id: str
    name: str | None = None


class FlatModel(BaseModel):
    id: str
    title: str
    active: bool


class NestedModel(BaseModel):
    id: str
    source: SubModel
    region: str | None = None


class _FakeRecord:
    """Minimal fake for asyncpg.Record that supports dict-like access."""

    def __init__(self, **kwargs: object) -> None:
        self._data = kwargs

    def __getitem__(self, key: str) -> object:
        return self._data[key]


# --- Tests for from_row ---


class TestFromRow:
    """Tests for ModelMapper.from_row()."""

    def test_simple_fields(self) -> None:
        """Verify simple field mapping."""
        mapper = ModelMapper(
            FlatModel,
            field_map={
                "doc_id": "id",
                "doc_title": "title",
                "is_active": "active",
            },
        )
        row = _FakeRecord(doc_id="abc", doc_title="Hello", is_active=True)
        result = mapper.from_row(row)

        assert isinstance(result, FlatModel)
        assert result.id == "abc"
        assert result.title == "Hello"
        assert result.active is True

    def test_nested_fields(self) -> None:
        """Verify nested field mapping via tuple paths."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
                "region_name": "region",
            },
        )
        row = _FakeRecord(
            doc_id="d1",
            src_id="s1",
            src_name="Test Source",
            region_name="Moscow",
        )
        result = mapper.from_row(row)

        assert isinstance(result, NestedModel)
        assert result.id == "d1"
        assert result.source.id == "s1"
        assert result.source.name == "Test Source"
        assert result.region == "Moscow"

    def test_nested_field_none(self) -> None:
        """Verify nested field with None value."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
            },
        )
        row = _FakeRecord(doc_id="d1", src_id="s1", src_name=None)
        result = mapper.from_row(row)

        assert result.source.name is None

    def test_region_default_none(self) -> None:
        """Verify optional field defaults to None when not in field_map."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
            },
        )
        row = _FakeRecord(doc_id="d1", src_id="s1", src_name="Src")
        result = mapper.from_row(row)

        assert result.region is None

    def test_extra_columns_ignored(self) -> None:
        """Verify columns not in field_map are ignored."""
        mapper = ModelMapper(
            FlatModel,
            field_map={"doc_id": "id", "doc_title": "title", "is_active": "active"},
        )
        row = _FakeRecord(doc_id="abc", doc_title="Hello", is_active=True, extra_col="ignored")
        result = mapper.from_row(row)

        assert result.id == "abc"
        assert not hasattr(result, "extra_col")  # type: ignore[unused-ignore]


# --- Tests for to_insert ---


class TestToInsert:
    """Tests for ModelMapper.to_insert()."""

    def test_simple_fields(self) -> None:
        """Verify simple fields are extracted."""
        mapper = ModelMapper(
            FlatModel,
            field_map={
                "doc_id": "id",
                "doc_title": "title",
                "is_active": "active",
            },
        )
        model = FlatModel(id="abc", title="Hello", active=True)
        result = mapper.to_insert(model)

        assert result == {"doc_id": "abc", "doc_title": "Hello", "is_active": True}

    def test_nested_fields(self) -> None:
        """Verify nested Pydantic models are flattened."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
                "region_name": "region",
            },
        )
        model = NestedModel(
            id="d1",
            source=SubModel(id="s1", name="Test Source"),
            region="Moscow",
        )
        result = mapper.to_insert(model)

        assert result == {
            "doc_id": "d1",
            "src_id": "s1",
            "src_name": "Test Source",
            "region_name": "Moscow",
        }

    def test_nested_field_none(self) -> None:
        """Verify nested field with None value produces None."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
            },
        )
        model = NestedModel(id="d1", source=SubModel(id="s1", name=None))
        result = mapper.to_insert(model)

        assert result["src_name"] is None

    def test_optional_field_none(self) -> None:
        """Verify optional field set to None is included as None."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
                "region_name": "region",
            },
        )
        model = NestedModel(id="d1", source=SubModel(id="s1", name="Src"), region=None)
        result = mapper.to_insert(model)

        assert result["region_name"] is None

    def test_roundtrip(self) -> None:
        """Verify from_row(to_insert(...)) roundtrip for simple models."""
        mapper = ModelMapper(
            FlatModel,
            field_map={
                "doc_id": "id",
                "doc_title": "title",
                "is_active": "active",
            },
        )
        original = FlatModel(id="abc", title="Hello", active=True)
        insert_data = mapper.to_insert(original)
        row = _FakeRecord(**insert_data)  # type: ignore[arg-type]
        restored = mapper.from_row(row)

        assert restored == original

    def test_roundtrip_nested(self) -> None:
        """Verify from_row(to_insert(...)) roundtrip for nested models."""
        mapper = ModelMapper(
            NestedModel,
            field_map={
                "doc_id": "id",
                "src_id": ("source", "id"),
                "src_name": ("source", "name"),
                "region_name": "region",
            },
        )
        original = NestedModel(
            id="d1",
            source=SubModel(id="s1", name="Src"),
            region="Moscow",
        )
        insert_data = mapper.to_insert(original)
        row = _FakeRecord(**insert_data)  # type: ignore[arg-type]
        restored = mapper.from_row(row)

        assert restored == original
