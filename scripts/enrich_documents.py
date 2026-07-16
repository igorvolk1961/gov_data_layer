"""Enrich documents with organization and document type metadata from API.

Reads raw API response from output/documents/{publish_id}/raw.json,
extracts organization IDs/names and document type IDs/names from the
pravo.gov.ru API response or via API lookup.

Output: output/enrichment/{publish_id}.json

Usage:
    uv run python scripts/enrich_documents.py
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.pravo.adapter.stub._data import (
    _STUB_PUBLISH_IDS_INITIAL,
    _STUB_PUBLISH_IDS_NEW,
)
from adapters.pravo.pravo_client import PravoClient
from adapters.pravo.pravo_parser import PravoParser

OUTPUT_DIR = Path("output/documents")
ENRICHMENT_DIR = Path("output/enrichment")


def _all_publish_ids() -> list[str]:
    return list(_STUB_PUBLISH_IDS_INITIAL) + list(_STUB_PUBLISH_IDS_NEW)


async def enrich_documents() -> None:
    """Enrich all documents with org/doc_type metadata."""
    ENRICHMENT_DIR.mkdir(parents=True, exist_ok=True)

    client = PravoClient()
    parser = PravoParser()

    publish_ids = _all_publish_ids()
    print(f"Enriching {len(publish_ids)} documents...")

    # Fetch lookup data from API
    print("Fetching authorities and document types from API...")
    await _populate_parser_caches(client, parser)
    print(f"  Authorities cached: {len(parser._authority_cache)}")
    print(f"  Doc types cached: {len(parser._doc_type_cache)}")

    for publish_id in publish_ids:
        metadata_path = OUTPUT_DIR / publish_id / "metadata.json"

        if not metadata_path.exists():
            print(f"  WARNING: metadata not found for {publish_id}, skipping")
            continue

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        # Get organization info from cached data
        org_id = metadata.get("organization_id")
        org_name = metadata.get("organization")
        if org_id and not org_name:
            org_name = parser._authority_cache.get(org_id, org_id)

        # Get document type info from cached data
        doc_type_id = metadata.get("document_type_id")
        doc_type_name = metadata.get("document_type")
        if doc_type_id and not doc_type_name:
            doc_type_name = parser._doc_type_cache.get(doc_type_id, doc_type_id)

        result = {
            "publish_id": publish_id,
            "organization_id": org_id,
            "organization_name": org_name,
            "document_type_id": doc_type_id,
            "document_type_name": doc_type_name,
        }

        out_path = ENRICHMENT_DIR / f"{publish_id}.json"
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  {publish_id}: org={org_name}, type={doc_type_name}")

    await client.close()
    print(f"\nAll enrichments saved to {ENRICHMENT_DIR.resolve()}")


async def _populate_parser_caches(
    client: PravoClient,
    parser: PravoParser,
) -> None:
    """Fetch authorities and document types from API into parser caches."""
    try:
        blocks = await client.get_public_blocks()
        if not blocks:
            print("  WARNING: No public blocks from API")
            return

        first_block = str(blocks[0].get("id", ""))
        if not first_block:
            return

        categories = await client.get_categories(block=first_block)
        if not categories:
            return

        first_category = str(categories[0].get("id", ""))
        if not first_category:
            return

        authorities = await client.get_signatory_authorities(
            block=first_block,
            category=first_category,
        )
        parser.update_authority_cache(authorities)

        if authorities:
            first_authority = str(authorities[0].get("id", ""))
            doc_types = await client.get_document_types(
                block=first_block,
                category=first_category,
                authority_id=first_authority,
            )
            parser.update_doc_type_cache(doc_types)

    except Exception as e:
        print(f"  ERROR populating caches: {e}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(enrich_documents())
