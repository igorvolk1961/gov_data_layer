"""Load reference data and documents into PostgreSQL + Qdrant.

Reads configs/demo_pipeline.yaml, clears existing data,
then loads rubrics, regions, organizations, document types,
and document records.

Usage:
    uv run python scripts/load_data.py
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

from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.persistence import DatabaseClient
from core.persistence.repository import ReferenceRepository


def _load_config() -> dict[str, Any]:
    config_path = Path("configs/demo_pipeline.yaml")
    if not config_path.exists():
        print(f"ERROR: Config not found at {config_path}")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        result = yaml.safe_load(f)
        return dict(result) if result else {}


async def load_data() -> None:
    """Main data loading routine."""
    config = _load_config()
    data_dir = Path(config.get("data_dir", "output"))
    source_cfg = config.get("source", {})
    source_id = source_cfg.get("id", "pravo")

    # Initialize DB connection
    print("Connecting to PostgreSQL...")
    try:
        from core.api.app_config import get_config

        app_cfg = get_config()
        db = DatabaseClient(dsn=app_cfg.database_url)
        await db.connect()
        ref_repo = ReferenceRepository(db)
        print("  Connected.")
    except Exception as e:
        print(f"  ERROR: Cannot connect to DB: {e}")
        sys.exit(1)

    # Initialize Qdrant
    print("Connecting to Qdrant...")
    try:
        app_cfg = get_config()
        qdrant = QdrantStore(
            host=app_cfg.qdrant_host,
            port=app_cfg.qdrant_port,
            vector_size=app_cfg.embedding.vector_size,
        )
        embedder = Embedder(
            model_name=app_cfg.embedding.model,
            vector_size=app_cfg.embedding.vector_size,
        )
        print(f"  Qdrant at {app_cfg.qdrant_host}:{app_cfg.qdrant_port}")
    except Exception as e:
        print(f"  ERROR: Cannot connect to Qdrant: {e}")
        sys.exit(1)

    # ── 1. Clear existing data ────────────────────────────────────────
    print("\nClearing existing data...")
    try:
        await db.execute("DELETE FROM document_rubric")
        await db.execute("DELETE FROM document_topic")
        await db.execute("DELETE FROM document_section")
        await db.execute("DELETE FROM document")
        await db.execute("DELETE FROM topic")
        await db.execute("DELETE FROM rubric")
        await db.execute("DELETE FROM region")
        await db.execute("DELETE FROM organization")
        await db.execute("DELETE FROM document_type")
        await db.execute("DELETE FROM jurisdiction")
        await db.execute("DELETE FROM data_source")
        print("  PostgreSQL tables cleared.")
    except Exception as e:
        print(f"  ERROR clearing DB: {e}")

    try:
        await qdrant.delete_all_collections()
        print("  Qdrant collections cleared.")
    except Exception as e:
        print(f"  ERROR clearing Qdrant: {e}")

    # ── 2. Create data source ─────────────────────────────────────────
    print("\nCreating data source...")
    try:
        source_uuid = await ref_repo.get_or_create_data_source(
            source_id=source_id,
            name=source_cfg.get("name", "Право.ру"),
            url=source_cfg.get("url", "https://pravo.gov.ru"),
        )
        print(f"  Data source UUID: {source_uuid}")
    except Exception as e:
        print(f"  ERROR creating data source: {e}")
        sys.exit(1)

    # ── 3. Load rubrics into PostgreSQL + Qdrant ──────────────────────
    print("\nLoading rubrics into PostgreSQL...")
    rubric_ids: dict[str, str] = {}  # rubric external_id -> UUID
    for rubric_cfg in config.get("rubrics", []):
        rid = rubric_cfg["id"]
        name = rubric_cfg["name"]
        try:
            uuid, created = await ref_repo.get_or_create_topic(
                source_id=source_uuid,
                external_id=rid,
                name=name,
                description=rubric_cfg.get("description"),
                qdrant=qdrant,
                embedder=embedder,
            )
            rubric_ids[rid] = uuid
            status = "created" if created else "already exists"
            print(f"  {rid}: {name} -> {uuid[:8]}... ({status})")
        except Exception as e:
            print(f"  ERROR creating rubric {rid}: {e}")

    # ── 4. Load documents into PostgreSQL ─────────────────────────────
    print("\nLoading documents into PostgreSQL...")
    for doc_cfg in config.get("documents", []):
        publish_id = doc_cfg["publish_id"]
        analysis_path = data_dir / doc_cfg["analysis"]
        enrichment_path = data_dir / doc_cfg["enrichment"]
        metadata_path = data_dir / doc_cfg["metadata"]

        if not metadata_path.exists():
            print(f"  WARNING: metadata not found for {publish_id}, skipping")
            continue

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        analysis = {}
        if analysis_path.exists():
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

        enrichment = {}
        if enrichment_path.exists():
            enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))

        # Build document for upsert
        from datetime import datetime, timezone

        from core.models.models import LegalStatus, OfficialDocument, Source

        doc = OfficialDocument(
            id=f"pravo-{publish_id}",
            title=metadata.get("title", ""),
            source=Source(
                id=source_id,
                name=source_cfg.get("name", "Право.ру"),
                url=source_cfg.get("url", "https://pravo.gov.ru"),
            ),
            url=metadata.get("url", ""),
            summary=metadata.get("summary", ""),
            jurisdiction=analysis.get("jurisdiction") or metadata.get("jurisdiction"),
            region=analysis.get("region"),
            topic=analysis.get("rubrics", []),
            organization=enrichment.get("organization_name"),
            organization_id=enrichment.get("organization_id"),
            document_type=enrichment.get("document_type_name"),
            document_type_id=enrichment.get("document_type_id"),
            publish_id=publish_id,
            created_at=datetime.now(timezone.utc),
            legal_status=LegalStatus.ACTIVE,
        )

        # Parse dates
        import contextlib
        from datetime import datetime

        vf = metadata.get("valid_from")
        if vf:
            with contextlib.suppress(ValueError, TypeError):
                doc.valid_from = datetime.fromisoformat(vf)

        pd = metadata.get("publish_date")
        if pd:
            with contextlib.suppress(ValueError, TypeError):
                doc.publish_date = datetime.fromisoformat(pd)

        try:
            doc_uuid = await ref_repo._db.fetchrow(
                """
                SELECT d.id FROM data_source ds
                JOIN document d ON d.source_id = ds.id
                WHERE ds.source_id = $1 AND d.publish_id = $2
                """,
                source_id,
                publish_id,
            )
            if doc_uuid:
                print(f"  {publish_id}: already exists as {str(doc_uuid['id'])[:8]}...")
            else:
                # Use document_repo to upsert
                from core.persistence.repository import DocumentRepository

                doc_repo = DocumentRepository(db, ref_repo)
                uuid = await doc_repo.upsert_document(doc, source_uuid)
                print(f"  {publish_id}: {doc.title[:60]}... -> {uuid[:8]}...")
        except Exception as e:
            print(f"  ERROR loading document {publish_id}: {e}")

    # Cleanup
    await db.close()
    print(f"\n{'=' * 50}")
    print("Data loading complete!")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(load_data())
