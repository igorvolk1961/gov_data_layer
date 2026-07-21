"""Full ingest pipeline — reference data from fixtures, documents from source.

1. Loads reference tables (rubrics, document_types, organizations, regions)
   from fixtures/*.json into PostgreSQL
2. For each of 6 documents, runs the full pipeline via PravoAdapter:
   fetch metadata from API → OCR → persist to DB → chunk → embed → Qdrant

Usage: uv run python scripts/fixtures_ingest_pipeline.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from adapters.pravo.adapter import PravoAdapter
from core.api.app_config import get_config
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.observability import configure as configure_observability
from core.persistence import DatabaseClient
from core.persistence.repository import ReferenceRepository

load_dotenv()

FIXTURES_DIR = Path("fixtures")
# All 6 OCR fixture files available in fixtures/ocr_results/
PUBLISH_IDS = [
    "0001202012230060",  # 95465 chars
    "0001202206200030",  # 12280 chars
    "0001202212190143",  # 117048 chars
    "0001202606090026",  # 2938 chars
    "0001202607060006",  # 128005 chars
    "7800202607010012",  # 2753 chars
]


async def main() -> None:
    configure_observability()
    cfg = get_config()

    # Connect DB
    db = DatabaseClient(dsn=cfg.database_url)
    await db.connect()
    ref_repo = ReferenceRepository(db)
    print("PostgreSQL connected.")

    # Connect Qdrant
    qdrant = QdrantStore(
        host=cfg.qdrant_host, port=cfg.qdrant_port, vector_size=cfg.embedding.vector_size
    )
    embedder = Embedder(model_name=cfg.embedding.model, vector_size=cfg.embedding.vector_size)
    print("Qdrant connected.")

    # ── Step 1: Clean + load reference tables ────────────────────────
    print("\n=== Step 1: Cleaning and loading reference data ===")
    for table in [
        "section_topic",
        "document_topic",
        "document_section_modification",
        "document_revocation",
        "document_section",
        "document",
        "topic",
        "organization",
        "region",
        "document_type",
        "jurisdiction",
        "data_source",
    ]:
        await db.execute(f"DELETE FROM {table}")

    # Apply v004 migration: ensure organization has jurisdiction_id + region_id
    for col in ["jurisdiction_id", "region_id"]:
        with contextlib.suppress(Exception):
            await db.execute(
                f"ALTER TABLE organization ADD COLUMN IF NOT EXISTS {col} UUID "
                f"REFERENCES {col.replace('_id', '')}(id)"
            )
    await qdrant.delete_all_collections()
    print("Cleaned.")

    # Create data source
    source_uuid = await ref_repo.get_or_create_data_source(
        source_id="pravo", name="Право.ру (pravo.gov.ru)", url="https://pravo.gov.ru"
    )
    print(f"Data source: {source_uuid[:8]}...")

    # Load topics from fixtures/topic.json
    topic_path = FIXTURES_DIR / "topic.json"
    if topic_path.exists():
        topic_data = json.loads(topic_path.read_text(encoding="utf-8"))
        for r in topic_data.get("topics", []):
            uuid, created = await ref_repo.get_or_create_topic(
                source_id=source_uuid,
                external_id=r["id"],
                name=r["name"],
                qdrant=qdrant,
                embedder=embedder,
            )
            status = "created" if created else "exists"
            print(f"  topic {r['name'][:40]:40s} -> {uuid[:8]}... ({status})")

    # Load document types from fixture
    dt_path = FIXTURES_DIR / "document_types.json"
    if dt_path.exists():
        for dt in json.loads(dt_path.read_text(encoding="utf-8")):
            await ref_repo.get_or_create_document_type(
                source_id=source_uuid, external_id=dt["id"], name=dt["name"]
            )
            print(f"  doc_type: {dt['name']}")

    # Load organizations from fixture
    # jurisdiction and region are set explicitly in organizations.json
    org_path = FIXTURES_DIR / "organizations.json"
    if org_path.exists():
        for org in json.loads(org_path.read_text(encoding="utf-8")):
            # Resolve jurisdiction_id from fixture field
            jurisdiction_id = None
            jur_code = org.get("jurisdiction")
            if jur_code:
                jur_uuid = await ref_repo.get_or_create_jurisdiction(
                    source_id=source_uuid, code=jur_code, name=jur_code
                )
                jurisdiction_id = jur_uuid

            # Resolve region_id from fixture (explicit field)
            region_id = None
            region_name = org.get("region")
            if region_name:
                reg_uuid = await ref_repo.get_or_create_region(
                    source_id=source_uuid, code=region_name, name=region_name
                )
                region_id = reg_uuid

            await ref_repo.get_or_create_organization(
                source_id=source_uuid,
                external_id=org["id"],
                name=org["name"],
                jurisdiction_id=jurisdiction_id,
                region_id=region_id,
            )
            print(f"  org: {org['name'][:40]}  jur={jur_code or '-'}  reg={region_name or '-'}")

    print("Reference data loaded.")

    # ── Step 2: Full ingest for each document via PravoAdapter ───────
    print(f"\n=== Step 2: Ingesting {len(PUBLISH_IDS)} documents from source ===")

    from adapters.ocr import DemoDocProvider

    adapter = PravoAdapter(mode="stub", db=db, ocr_provider=DemoDocProvider())

    for i, publish_id in enumerate(PUBLISH_IDS, 1):
        document_id = f"pravo-{publish_id}"
        print(f"\n--- [{i}/{len(PUBLISH_IDS)}] {publish_id} ---")

        try:
            # Step 2a: Fetch metadata from API + persist to DB
            print("  Fetching from API...")
            doc = await adapter.get(document_id)
            print(f"  Title: {doc.title[:60]}...")
            print(f"  organization_id={doc.organization_id}  organization={doc.organization}")

            # Step 2b: Get OCR text + pipeline in one trace
            from core.observability import get_tracer

            proc_tracer = get_tracer()
            with proc_tracer.trace("pravo.get_content") as content_span:
                print("  Getting OCR text...")
                text = await adapter.get_content(document_id)
                print(f"  OCR text: {len(text)} chars")

                # Step 2c: Get doc_uuid from DB (UUID, not external_id!)
                doc_uuid = ""
                row = await db.fetchval(
                    "SELECT id FROM document WHERE publish_id = $1",
                    publish_id,
                )
                if row:
                    doc_uuid = str(row)
                print(f"  doc_uuid: {doc_uuid[:8] if doc_uuid else 'EMPTY'}...")

                # Step 2c: Resolve jurisdiction_id + region_id from organization
                org_region_id = None
                if doc.organization_id and doc_uuid:
                    org_row = await db.fetchrow(
                        "SELECT jurisdiction_id, region_id FROM organization "
                        "WHERE external_id = $1 AND source_id = $2::uuid",
                        doc.organization_id,
                        source_uuid,
                    )
                    if org_row:
                        jur_id = (
                            str(org_row["jurisdiction_id"]) if org_row["jurisdiction_id"] else None
                        )
                        reg_id = str(org_row["region_id"]) if org_row["region_id"] else None
                        if jur_id or reg_id:
                            await db.execute(
                                "UPDATE document SET jurisdiction_id = $1::uuid, "
                                "region_id = $2::uuid WHERE id = $3::uuid",
                                jur_id,
                                reg_id,
                                doc_uuid,
                            )
                            org_region_id = reg_id
                            print(
                                f"  jurisdiction_id={jur_id[:8] if jur_id else '-'}  region_id={reg_id[:8] if reg_id else '-'}"
                            )

                # Step 2d: Run shared pipeline as child of content_span
                from adapters.base.ingest_pipeline import process_document_text
                from core.ingest.chunker import DocStructSplitter
                from core.persistence.repository import SectionRepository

                section_repo = SectionRepository(db) if db else None
                chunker = DocStructSplitter()
                chunks, toc = await process_document_text(
                    text,
                    document_id,
                    doc_uuid,
                    chunker=chunker,
                    embedder=embedder,
                    qdrant=qdrant,
                    section_repo=section_repo,
                    region_id=org_region_id,
                    parent_span=content_span,
                )
                print(f"  Chunks: {len(chunks)}, TOC: {len(toc)}")

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback

            traceback.print_exc()
            continue

    await adapter.close()
    await db.close()

    print(f"\n{'=' * 50}")
    print(f"Pipeline complete! Processed {len(PUBLISH_IDS)} documents.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
