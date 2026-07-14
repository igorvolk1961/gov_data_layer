"""Типизированные ошибки слоя.

Классификация ошибок по виду:
- InvalidInputError — некорректный ввод
- NotFoundError — не найдено
- SourceUnavailableError — источник недоступен
- InternalError — внутренняя ошибка
"""

from __future__ import annotations


class ODLBaseError(Exception):
    """Базовый класс для всех ошибок слоя."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.message = message
        self.code = code or self.__class__.__name__
        super().__init__(self.message)


class InvalidInputError(ODLBaseError):
    """Некорректные параметры запроса."""

    def __init__(self, message: str = "Invalid input parameters") -> None:
        super().__init__(message, code="INVALID_INPUT")


class NotFoundError(ODLBaseError):
    """Документ не найден в индексе."""

    def __init__(self, message: str = "Document not found") -> None:
        super().__init__(message, code="NOT_FOUND")


class SourceUnavailableError(ODLBaseError):
    """Источник данных недоступен."""

    def __init__(self, message: str = "Source is unavailable") -> None:
        super().__init__(message, code="SOURCE_UNAVAILABLE")


class InternalError(ODLBaseError):
    """Внутренняя ошибка слоя."""

    def __init__(self, message: str = "Internal error") -> None:
        super().__init__(message, code="INTERNAL_ERROR")


class OCRUnavailableError(ODLBaseError):
    """OCR-сервис недоступен."""

    def __init__(self, message: str = "OCR service is unavailable") -> None:
        super().__init__(message, code="OCR_UNAVAILABLE")


class OCRQualityError(ODLBaseError):
    """Качество распознавания OCR ниже допустимого порога."""

    def __init__(self, message: str = "OCR quality is below acceptable threshold") -> None:
        super().__init__(message, code="OCR_QUALITY")


class PersistenceUnavailableError(ODLBaseError):
    """Система персистентности (БД) недоступна.

    Используется для graceful degradation — не фатальная ошибка API,
    а сигнал о том, что метаданные не были сохранены.
    """

    def __init__(self, message: str = "Persistence layer is unavailable") -> None:
        super().__init__(message, code="PERSISTENCE_UNAVAILABLE")
