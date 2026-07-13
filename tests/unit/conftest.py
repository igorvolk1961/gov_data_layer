"""Shared fixtures for unit tests."""

from __future__ import annotations

import pytest

from adapters.ocr.yandex_vision import YandexVisionOCR

# Test credentials — dummy values, not real secrets
_TEST_KEY_SECRET = "test-key-secret"  # pragma: allowlist secret
_TEST_FOLDER_ID = "test-folder-id"


@pytest.fixture
def ya_key_secret() -> str:
    return _TEST_KEY_SECRET


@pytest.fixture
def ya_folder_id() -> str:
    return _TEST_FOLDER_ID


@pytest.fixture
def ya_api_key() -> str:
    """API key for testing (starts with AQVN)."""
    return "AQVN-test-api-key-for-testing"


@pytest.fixture
def yandex_ocr(ya_key_secret: str, ya_folder_id: str) -> YandexVisionOCR:
    """Create a YandexVisionOCR instance with test credentials."""
    return YandexVisionOCR(
        ya_key_secret=ya_key_secret,
        ya_folder_id=ya_folder_id,
    )
