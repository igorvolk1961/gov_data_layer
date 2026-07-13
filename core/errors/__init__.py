"""Типизированные ошибки слоя."""

from core.errors.errors import (
    InternalError,
    InvalidInputError,
    NotFoundError,
    OCRQualityError,
    OCRUnavailableError,
    ODLBaseError,
    SourceUnavailableError,
)

__all__ = [
    "InternalError",
    "InvalidInputError",
    "NotFoundError",
    "OCRQualityError",
    "OCRUnavailableError",
    "ODLBaseError",
    "SourceUnavailableError",
]
