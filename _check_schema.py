"""Check actual DB schema for document table."""

from __future__ import annotations

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from core.persistence.db_client import DatabaseClient  # noqa: E402


async def main() -> None:
    client = DatabaseClient(dsn="postgresql://odl:odl@127.0.0.1:5433/odl_metadata?sslmode=disable")
    await client.connect()
    rows = await client.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'document'
        ORDER BY ordinal_position
    """
    )
    for r in rows:
        print(f"{r['column_name']:30s} {r['data_type']}")
    await client.close()


asyncio.run(main())
