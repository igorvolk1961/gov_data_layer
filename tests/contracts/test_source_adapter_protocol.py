"""Contract tests for SourceAdapter Protocol (adapters/base/__init__.py).

Tests cover:
- runtime_checkable: StubAdapter satisfies the protocol
- Classes with wrong signatures do NOT satisfy the protocol
- Classes with missing methods do NOT satisfy the protocol
- Protocol cannot be instantiated directly
"""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints

import pytest

from adapters.base import SourceAdapter
from adapters.stub import StubAdapter


def _assert_conforms_to_protocol(cls: type, protocol: type) -> None:
    """Verify all protocol methods exist with matching signatures.

    This helper checks that a concrete class implements all methods
    defined in the protocol with the same parameter names (excluding
    'self') and that async methods in the protocol are also async
    in the implementation. This catches signature drift that
    runtime_checkable Protocol does not detect.
    """
    for name, proto_method in inspect.getmembers(protocol, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        impl_method = getattr(cls, name, None)
        if impl_method is None:
            pytest.fail(f"{cls.__name__} is missing method '{name}' required by {protocol.__name__}")
        # Verify async consistency
        if inspect.iscoroutinefunction(proto_method) and not inspect.iscoroutinefunction(impl_method):
            pytest.fail(
                f"'{name}' in {cls.__name__} must be async "
                f"(defined as async in {protocol.__name__})"
            )
        proto_sig = inspect.signature(proto_method)
        impl_sig = inspect.signature(impl_method)
        proto_params = list(proto_sig.parameters.keys())[1:]  # skip 'self'
        impl_params = list(impl_sig.parameters.keys())[1:]
        assert proto_params == impl_params, (
            f"Signature mismatch for '{name}': "
            f"protocol expects {proto_params}, got {impl_params}"
        )


class TestProtocolContract:
    """Verify that SourceAdapter is a proper Protocol."""

    def test_is_protocol(self) -> None:
        """SourceAdapter should be a Protocol, not a regular ABC."""
        assert issubclass(SourceAdapter, Protocol)

    def test_cannot_instantiate_directly(self) -> None:
        """Protocol cannot be instantiated directly."""
        with pytest.raises(TypeError):
            SourceAdapter()  # type: ignore[abstract]

    def test_is_runtime_checkable(self) -> None:
        """SourceAdapter should be runtime_checkable."""
        # If it's runtime_checkable, isinstance works
        assert isinstance(StubAdapter(), SourceAdapter)


class TestStubAdapterConformance:
    """Verify that StubAdapter conforms to SourceAdapter protocol."""

    def test_isinstance_check(self) -> None:
        assert isinstance(StubAdapter(), SourceAdapter)

    def test_has_source_id_property(self) -> None:
        assert hasattr(StubAdapter, "source_id")
        # Should be a property, not a method
        assert isinstance(inspect.getattr_static(StubAdapter, "source_id"), property)

    def test_has_search_method(self) -> None:
        assert hasattr(StubAdapter, "search")
        assert callable(StubAdapter.search)

    def test_has_get_method(self) -> None:
        assert hasattr(StubAdapter, "get")
        assert callable(StubAdapter.get)

    def test_has_normalize_method(self) -> None:
        assert hasattr(StubAdapter, "normalize")
        assert callable(StubAdapter.normalize)

    def test_has_ingest_method(self) -> None:
        assert hasattr(StubAdapter, "ingest")
        assert callable(StubAdapter.ingest)

    def test_all_methods_are_async(self) -> None:
        """All protocol methods except source_id should be async."""
        adapter = StubAdapter()
        assert inspect.iscoroutinefunction(adapter.search)
        assert inspect.iscoroutinefunction(adapter.get)
        assert inspect.iscoroutinefunction(adapter.normalize)
        assert inspect.iscoroutinefunction(adapter.ingest)

    def test_signatures_match_protocol(self) -> None:
        """StubAdapter method signatures should match SourceAdapter protocol."""
        _assert_conforms_to_protocol(StubAdapter, SourceAdapter)


class TestNonConformingClasses:
    """Verify that classes with wrong signatures are rejected.

    NOTE: runtime_checkable Protocol only checks that methods exist,
    NOT their signatures or whether they're async. These tests verify
    what isinstance() can and cannot detect.
    """

    def test_missing_method_fails_isinstance(self) -> None:
        class MissingMethod:
            @property
            def source_id(self) -> str:
                return "test"

            async def search(self, query: str, context=None) -> list:
                return []

            async def get(self, document_id: str) -> dict:
                return {}

            async def normalize(self, raw: dict) -> dict:
                return {}

            # missing ingest()

        assert not isinstance(MissingMethod(), SourceAdapter)

    def test_missing_source_id_fails_isinstance(self) -> None:
        class MissingSourceId:
            async def search(self, query: str, context=None) -> list:
                return []

            async def get(self, document_id: str) -> dict:
                return {}

            async def normalize(self, raw: dict) -> dict:
                return {}

            async def ingest(self) -> int:
                return 0

        assert not isinstance(MissingSourceId(), SourceAdapter)

    def test_wrong_signature_passes_isinstance(self) -> None:
        """runtime_checkable does NOT check method signatures.

        A class with wrong parameter names still passes isinstance check.
        This is a known limitation of Protocols.
        """
        class WrongSignature:
            @property
            def source_id(self) -> str:
                return "test"

            async def search(self, q: str, context=None) -> list:  # type: ignore[override]
                return []

            async def get(self, document_id: str) -> dict:
                return {}

            async def normalize(self, raw: dict) -> dict:
                return {}

            async def ingest(self) -> int:
                return 0

        # isinstance passes because all method names exist
        assert isinstance(WrongSignature(), SourceAdapter)

    def test_non_async_method_passes_isinstance(self) -> None:
        """runtime_checkable does NOT check if methods are async.

        A class with sync methods still passes isinstance check.
        This is a known limitation of Protocols.
        """
        class SyncMethod:
            @property
            def source_id(self) -> str:
                return "test"

            def search(self, query: str, context=None) -> list:  # type: ignore[override]
                return []

            async def get(self, document_id: str) -> dict:
                return {}

            async def normalize(self, raw: dict) -> dict:
                return {}

            async def ingest(self) -> int:
                return 0

        # isinstance passes because all method names exist
        assert isinstance(SyncMethod(), SourceAdapter)


class TestProtocolMethodSignatures:
    """Verify method signatures match the protocol definition."""

    def test_search_signature(self) -> None:
        sig = inspect.signature(SourceAdapter.search)
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "context" in params

    def test_get_signature(self) -> None:
        sig = inspect.signature(SourceAdapter.get)
        params = list(sig.parameters.keys())
        assert "document_id" in params

    def test_normalize_signature(self) -> None:
        sig = inspect.signature(SourceAdapter.normalize)
        params = list(sig.parameters.keys())
        assert "raw" in params

    def test_ingest_signature(self) -> None:
        sig = inspect.signature(SourceAdapter.ingest)
        # ingest should only have 'self'
        assert len(sig.parameters) == 1  # only self
