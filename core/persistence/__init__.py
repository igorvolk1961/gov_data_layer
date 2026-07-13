"""Persistence — PostgreSQL-backed storage for canonical models.

Provides DatabaseClient (asyncpg wrapper with graceful degradation)
and repository classes for documents, sections, reference data,
and change tracking.
"""

from __future__ import annotations

from core.persistence.db_client import DatabaseClient

__all__ = [
    "DatabaseClient",
]
