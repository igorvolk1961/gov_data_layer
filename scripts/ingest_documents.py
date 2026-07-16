"""Ingest documents using the shared pipeline (chunk → embed → Qdrant).

Reads configs/demo_pipeline.yaml, processes each document through
process_document_text() directly (no worker needed).

Usage:
    uv run python scripts/ingest_documents.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.base.ingest_pipeline import process_document_text
from core.index.qdrant_store import QdrantStore
from core.ingest.chunker import DocStructSplitter
from core.ingest.embedder import Embedder
from core.persistence import DatabaseClient
from core.persistence.repository import SectionRepository


def _load_config() -> dict[str, Any]:
    config_path = Path("configs/demo_pipeline.yaml")
    if not config_path.exists():
        print(f"ERROR: Config not found at {config_path}")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        result = yaml.safe_load(f)
        return dict(result) if result else {}


async def ingest_documents() -> None:
    """Ingest all documents via the shared pipeline."""
    config = _load_config()
    data_dir = Path(config.get("data_dir", "output"))
    source_id = config.get("source", {}).get("id", "pravo")

    # Initialize services
    print("Initializing services...")
    try:
        from core.api.app_config import get_config

        app_cfg = get_config()
    except Exception as e:
        print(f"  ERROR loading config: {e}")
        sys.exit(1)

    # DB connection
    db: DatabaseClient | None = None
    section_repo: SectionRepository | None = None
    try:
        db = DatabaseClient(dsn=app_cfg.database_url)
        await db.connect()
        section_repo = SectionRepository(db)
        print("  PostgreSQL connected.")
    except Exception as e:
        print(f"  WARNING: DB unavailable ({e}), proceeding without section persistence")

    # Qdrant + Embedder
    qdrant = QdrantStore(
        host=app_cfg.qdrant_host,
        port=app_cfg.qdrant_port,
        vector_size=app_cfg.embedding.vector_size,
    )
    embedder = Embedder(
        model_name=app_cfg.embedding.model,
        vector_size=app_cfg.embedding.vector_size,
    )
    chunker = DocStructSplitter()
    print("  Services initialized.")

    # Ensure collections exist
    try:
        await qdrant.ensure_collection()
        await qdrant.ensure_topic_collection()
        print("  Qdrant collections ready.")
    except Exception as e:
        print(f"  WARNING: Qdrant collection setup failed ({e})")

    # Process each document
    for doc_cfg in config.get("documents", []):
        publish_id = doc_cfg["publish_id"]
        document_id = f"pravo-{publish_id}"
        ocr_text_path = data_dir / doc_cfg["ocr_text"]
        analysis_path = data_dir / doc_cfg["analysis"]

        print(f"\n{'=' * 50}")
        print(f"Processing: {publish_id}")

        if not ocr_text_path.exists():
            print("  WARNING: OCR text not found, skipping")
            continue

        text = ocr_text_path.read_text(encoding="utf-8")
        print(f"  OCR text: {len(text)} chars")

        # Get doc_uuid from PostgreSQL
        doc_uuid = ""
        if db is not None:
            try:
                row = await db.fetchrow(
                    """
                    SELECT d.id FROM data_source ds
                    JOIN document d ON d.source_id = ds.id
                    WHERE ds.source_id = $1 AND d.publish_id = $2
                    """,
                    source_id,
                    publish_id,
                )
                if row:
                    doc_uuid = str(row["id"])
                    print(f"  doc_uuid: {doc_uuid[:8]}...")
                else:
                    print("  WARNING: Document not found in DB, proceeding without UUID")
            except Exception as e:
                print(f"  WARNING: DB lookup failed ({e})")

        # Get region info from analysis
        analysis = {}
        if analysis_path.exists():
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

        region = analysis.get("region")
        region_id = None
        # Resolve region_id if region is specified
        if region and db is not None:
            try:
                from core.persistence.repository import ReferenceRepository

                ref_repo = ReferenceRepository(db)
                resolved = await ref_repo.search_region_id(region)
                if resolved:
                    region_id = resolved[0]
                    print(f"  region: {region} -> {region_id[:8]}...")
            except Exception:
                print(f"  WARNING: Could not resolve region_id for {region}")

        # Run the shared pipeline
        try:
            chunks, toc = await process_document_text(
                text=text,
                document_id=document_id,
                doc_uuid=doc_uuid,
                chunker=chunker,
                embedder=embedder,
                qdrant=qdrant,
                section_repo=section_repo,
                region=region,
                region_id=region_id,
            )
            print(f"  Chunks: {len(chunks)}, TOC nodes: {len(toc)}")
        except Exception as e:
            print(f"  ERROR in pipeline: {e}")
            import traceback

            traceback.print_exc()
            continue

    # Cleanup
    if db is not None:
        await db.close()

    print(f"\n{'=' * 50}")
    print("Ingestion complete!")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(ingest_documents())
