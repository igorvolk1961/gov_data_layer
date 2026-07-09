"""Unit tests for typed error hierarchy (core/errors/errors.py).

Tests cover:
- All error classes inherit from ODLBaseError
- Default error codes per class
- Custom error codes and messages
- Default messages
- isinstance checks
"""

from __future__ import annotations

import pytest

from core.errors import (
    InternalError,
    InvalidInputError,
    NotFoundError,
    ODLBaseError,
    SourceUnavailableError,
)


class TestODLBaseError:
    def test_is_base_class(self) -> None:
        """ODLBaseError should be the base for all errors."""
        assert issubclass(InvalidInputError, ODLBaseError)
        assert issubclass(NotFoundError, ODLBaseError)
        assert issubclass(SourceUnavailableError, ODLBaseError)
        assert issubclass(InternalError, ODLBaseError)

    def test_custom_code(self) -> None:
        err = ODLBaseError("test", code="CUSTOM_CODE")
        assert err.code == "CUSTOM_CODE"
        assert err.message == "test"

    def test_default_code_is_class_name(self) -> None:
        err = ODLBaseError("test")
        assert err.code == "ODLBaseError"


class TestInvalidInputError:
    def test_default_message(self) -> None:
        err = InvalidInputError()
        assert err.message == "Invalid input parameters"

    def test_default_code(self) -> None:
        err = InvalidInputError()
        assert err.code == "INVALID_INPUT"

    def test_custom_message(self) -> None:
        err = InvalidInputError("Custom message")
        assert err.message == "Custom message"
        assert err.code == "INVALID_INPUT"

    def test_is_instance(self) -> None:
        assert isinstance(InvalidInputError(), ODLBaseError)
        assert isinstance(InvalidInputError(), Exception)


class TestNotFoundError:
    def test_default_message(self) -> None:
        err = NotFoundError()
        assert err.message == "Document not found"

    def test_default_code(self) -> None:
        err = NotFoundError()
        assert err.code == "NOT_FOUND"

    def test_custom_message(self) -> None:
        err = NotFoundError("Doc-123 not found")
        assert str(err) == "Doc-123 not found"

    def test_is_instance(self) -> None:
        assert isinstance(NotFoundError(), ODLBaseError)


class TestSourceUnavailableError:
    def test_default_message(self) -> None:
        err = SourceUnavailableError()
        assert err.message == "Source is unavailable"

    def test_default_code(self) -> None:
        err = SourceUnavailableError()
        assert err.code == "SOURCE_UNAVAILABLE"

    def test_is_instance(self) -> None:
        assert isinstance(SourceUnavailableError(), ODLBaseError)


class TestInternalError:
    def test_default_message(self) -> None:
        err = InternalError()
        assert err.message == "Internal error"

    def test_default_code(self) -> None:
        err = InternalError()
        assert err.code == "INTERNAL_ERROR"

    def test_is_instance(self) -> None:
        assert isinstance(InternalError(), ODLBaseError)


class TestErrorHierarchy:
    """Cross-cutting hierarchy tests."""

    def test_all_errors_have_unique_codes(self) -> None:
        codes = {
            InvalidInputError: "INVALID_INPUT",
            NotFoundError: "NOT_FOUND",
            SourceUnavailableError: "SOURCE_UNAVAILABLE",
            InternalError: "INTERNAL_ERROR",
        }
        for cls, expected_code in codes.items():
            assert cls().code == expected_code
        # Verify all codes are unique
        assert len(set(codes.values())) == len(codes)

    def test_all_errors_are_exceptions(self) -> None:
        for err in [
            InvalidInputError(),
            NotFoundError(),
            SourceUnavailableError(),
            InternalError(),
        ]:
            assert isinstance(err, Exception)

    def test_catch_base_class(self) -> None:
        """Catching ODLBaseError should catch all typed errors."""
        errors: list[ODLBaseError] = [
            InvalidInputError(),
            NotFoundError(),
            SourceUnavailableError(),
            InternalError(),
        ]
        for err in errors:
            try:
                raise err
            except ODLBaseError as caught:
                assert caught is err
                assert caught.code is not None
