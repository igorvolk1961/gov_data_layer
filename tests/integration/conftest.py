"""Integration tests configuration — loads .env, configures Tesseract path,
initializes observability, and provides shared async fixtures for persistence tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта, чтобы pytest видел OCR_YA_* переменные
load_dotenv(Path(__file__).parents[2] / ".env")

# Инициализируем трейсер (FileFallbackTracer) для тестов, которые используют tracer
from core.observability import configure  # noqa: E402

configure()

# Путь к Tesseract: из переменной окружения TESSERACT_CMD или стандартный для платформы
_tesseract_path = os.environ.get("TESSERACT_CMD")
if not _tesseract_path:
    if sys.platform == "win32":
        _tesseract_path = r"D:\Program Files\Tesseract-OCR\tesseract.exe"
    else:
        _tesseract_path = "/usr/bin/tesseract"

if os.path.exists(_tesseract_path):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _tesseract_path

# ── Shared async fixtures for persistence integration tests ──────────────────

import pytest_asyncio  # noqa: E402

from core.persistence.db_client import DatabaseClient  # noqa: E402

TEST_DSN = "postgresql://odl:odl@127.0.0.1:5433/odl_metadata?sslmode=disable"


@pytest_asyncio.fixture
async def db() -> DatabaseClient:
    """Create a DatabaseClient connected to the real test database."""
    client = DatabaseClient(dsn=TEST_DSN)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def source_uuid(db: DatabaseClient) -> str:
    """Insert a test data_source and return its UUID."""
    result = await db.fetchrow(
        """
        INSERT INTO data_source (id, source_id, name, url, jurisdiction)
        VALUES (gen_random_uuid(), $1, $2, $3, $4)
        ON CONFLICT (source_id) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        "test-integration-source",
        "Test Integration Source",
        "https://example.com",
        "test",
    )
    assert result is not None
    return str(result["id"])


@pytest_asyncio.fixture
async def doc_type_id(db: DatabaseClient, source_uuid: str) -> str:
    """Insert a test document_type and return its UUID."""
    result = await db.upsert(
        table="document_type",
        data={
            "source_id": source_uuid,
            "external_id": "test-type",
            "name": "Test Document Type",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None
    return str(result["id"])


@pytest_asyncio.fixture
async def jurisdiction_id(db: DatabaseClient, source_uuid: str) -> str:
    """Insert a test jurisdiction and return its UUID."""
    result = await db.upsert(
        table="jurisdiction",
        data={
            "source_id": source_uuid,
            "external_id": "test-jur",
            "name": "Test Jurisdiction",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None
    return str(result["id"])


@pytest_asyncio.fixture
async def region_id(db: DatabaseClient, source_uuid: str) -> str:
    """Insert a test region and return its UUID."""
    result = await db.upsert(
        table="region",
        data={
            "source_id": source_uuid,
            "external_id": "test-region",
            "name": "Test Region",
        },
        conflict_columns=["source_id", "external_id"],
    )
    assert result is not None
    return str(result["id"])
