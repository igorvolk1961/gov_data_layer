"""Full ingest pipeline — reference data from fixtures, documents from source.

1. Loads reference tables (rubrics, document_types, organizations, regions)
   from fixtures/*.json into PostgreSQL
2. For each of 6 documents, runs the full pipeline via PravoAdapter:
   fetch metadata from API → OCR → persist to DB → chunk → embed → Qdrant

Usage: uv run python scripts/fixtures_ingest_pipeline.py
"""

from __future__ import annotations

import asyncio
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
PUBLISH_IDS = ["0001202012230060"]  # Demo: 1 document (all rubrics load)


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
        "document_rubric",
        "document_topic",
        "document_section",
        "document",
        "topic",
        "rubric",
        "region",
        "organization",
        "document_type",
        "jurisdiction",
        "data_source",
    ]:
        await db.execute(f"DELETE FROM {table}")
    await qdrant.delete_all_collections()
    print("Cleaned.")

    # Create data source
    source_uuid = await ref_repo.get_or_create_data_source(
        source_id="pravo", name="Право.ру (pravo.gov.ru)", url="https://pravo.gov.ru"
    )
    print(f"Data source: {source_uuid[:8]}...")

    # Load rubrics from fixtures/rubrics.json
    rubrics_path = FIXTURES_DIR / "rubrics.json"
    if rubrics_path.exists():
        rubrics_data = json.loads(rubrics_path.read_text(encoding="utf-8"))
        for r in rubrics_data.get("rubrics", []):
            uuid, created = await ref_repo.get_or_create_topic(
                source_id=source_uuid,
                external_id=r["id"],
                name=r["name"],
                qdrant=qdrant,
                embedder=embedder,
            )
            status = "created" if created else "exists"
            print(f"  rubric {r['name'][:40]:40s} -> {uuid[:8]}... ({status})")

    # Load document types from fixture
    dt_path = FIXTURES_DIR / "document_types.json"
    if dt_path.exists():
        for dt in json.loads(dt_path.read_text(encoding="utf-8")):
            await ref_repo.get_or_create_document_type(
                source_id=source_uuid, external_id=dt["id"], name=dt["name"]
            )
            print(f"  doc_type: {dt['name']}")

    # Load organizations from fixture
    org_path = FIXTURES_DIR / "organizations.json"
    if org_path.exists():
        for org in json.loads(org_path.read_text(encoding="utf-8")):
            await ref_repo.get_or_create_organization(
                source_id=source_uuid, external_id=org["id"], name=org["name"]
            )
            print(f"  org: {org['name'][:40]}")

    # Load regions from fixture
    reg_path = FIXTURES_DIR / "regions.json"
    if reg_path.exists():
        for reg in json.loads(reg_path.read_text(encoding="utf-8")):
            await ref_repo.get_or_create_region(
                source_id=source_uuid, code=reg["id"], name=reg["name"]
            )
            print(f"  region: {reg['name']}")

    print("Reference data loaded.")

    # ── Step 2: Full ingest for each document via PravoAdapter ───────
    print(f"\n=== Step 2: Ingesting {len(PUBLISH_IDS)} documents from source ===")

    adapter = PravoAdapter(mode="stub", db=db)

    for i, publish_id in enumerate(PUBLISH_IDS, 1):
        document_id = f"pravo-{publish_id}"
        print(f"\n--- [{i}/{len(PUBLISH_IDS)}] {publish_id} ---")

        try:
            # Step 2a: Fetch metadata from API + persist to DB
            print("  Fetching from API...")
            doc = await adapter.get(document_id)
            print(f"  Title: {doc.title[:60]}...")

            # Step 2b: Get OCR text + pipeline in one trace
            from core.observability import get_tracer

            proc_tracer = get_tracer()
            with proc_tracer.trace("pravo.get_content") as content_span:
                print("  OCR via Yandex Vision...")
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

                # Step 2d: Run shared pipeline as child of content_span
                from adapters.base.ingest_pipeline import (
                    link_sections_to_topics,
                    process_document_text,
                )
                from core.persistence.repository import SectionRepository, SectionTopicRepository

                section_repo = SectionRepository(db) if db else None
                chunks, toc = await process_document_text(
                    text,
                    document_id,
                    doc_uuid,
                    embedder=embedder,
                    qdrant=qdrant,
                    section_repo=section_repo,
                    parent_span=content_span,
                )
                print(f"  Chunks: {len(chunks)}, TOC: {len(toc)}")

                # Step 2e: Link sections to rubrics (topics) via semantic similarity
                if chunks and db:
                    st_repo = SectionTopicRepository(db)
                    links = await link_sections_to_topics(
                        chunks,
                        embedder=embedder,
                        qdrant=qdrant,
                        section_topic_repo=st_repo,
                        parent_span=content_span,
                    )
                    print(f"  Section-topic links: {links}")

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
