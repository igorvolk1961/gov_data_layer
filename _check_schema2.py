"""Check actual DB schema for reference tables."""

from __future__ import annotations

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from core.persistence.db_client import DatabaseClient  # noqa: E402


async def main() -> None:
    client = DatabaseClient(dsn="postgresql://odl:odl@127.0.0.1:5433/odl_metadata?sslmode=disable")
    await client.connect()
    for table in [
        "organization",
        "document_type",
        "jurisdiction",
        "region",
        "topic",
        "data_source",
    ]:
        print(f"\n=== {table} ===")
        rows = await client.fetch(
            """
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
        """,
            table,
        )
        for r in rows:
            length = f"({r['character_maximum_length']})" if r["character_maximum_length"] else ""
            print(f"  {r['column_name']:30s} {r['data_type']}{length}")
    await client.close()


asyncio.run(main())
