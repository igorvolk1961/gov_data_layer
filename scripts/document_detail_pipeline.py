"""Document detail pipeline — demo: get full document card.

Использует тот же формат document_id, что возвращает search:
    {source_id}-{publish_id}

По умолчанию фильтрует цитаты по тому же запросу, что search:
    "государственные пособия гражданам имеющим детей"
Возвращает топ-5 релевантных чанков, общая длина цитат ≤ 2000 символов.

Usage:
    uv run python scripts/document_detail_pipeline.py                          # default: agent output
    uv run python scripts/document_detail_pipeline.py --format human            # readable
    uv run python scripts/document_detail_pipeline.py --input                   # example HTTP request
    uv run python scripts/document_detail_pipeline.py --document-id pravo-0001202012230060 \\
        --query "государственные пособия" --score-threshold 0.3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from core.api.app_config import get_config
from core.errors import NotFoundError
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.models.models import DocumentDetail, SearchContext
from core.observability import ObservabilityConfig, get_tracer
from core.observability import configure as configure_observability
from core.odl_service import ODLService
from core.persistence import DatabaseClient

load_dotenv()

# ── Document ──────────────────────────────────────────────────────────
# Document 0001202012230060: child benefits payment rules (Order 668n)
DOCUMENT_ID = "pravo-0001202012230060"
QUERY = "государственные пособия гражданам имеющим детей"


def _build_request_url(doc_id: str = DOCUMENT_ID, query: str | None = None) -> str:
    """Build example URL for GET /api/v1/documents/{source_id}."""
    url = f"/api/v1/documents/{doc_id}"
    if query:
        url += f"?query={query.replace(' ', '+')}"
    return url


def _build_curl_example(doc_id: str = DOCUMENT_ID) -> str:
    """Build example curl command for the REST API."""
    return f"curl -s http://localhost:8000/api/v1/documents/{doc_id} | python -m json.tool"


def _format_input() -> None:
    """Print example HTTP request info."""
    print("─── Example HTTP Request (all citations) ───────────────")
    print(f"  GET {_build_request_url()}")
    print()
    print("─── Example HTTP Request (filtered by query) ───────────")
    print(f"  GET {_build_request_url(query=QUERY)}")
    print()
    print("─── Example curl ───────────────────────────────────────")
    print(f"  {_build_curl_example()}")
    print()
    print("─── Parameter format ───────────────────────────────────")
    print("  document-id = source_id-publish_id")
    print(f"  Example:    {DOCUMENT_ID}")
    print()


def _format_human(detail: DocumentDetail, _detail_model: dict[str, Any]) -> None:
    """Human-readable output (console-friendly)."""
    print("\n─── Document Detail ───────────────────────────────────────")
    print(f"  ID:            {detail.id}")
    print(f"  Title:         {detail.title}")
    print(f"  URL:           {detail.url}")
    print(f"  Source:        {detail.source_name}")
    print(f"  Jurisdiction:  {detail.jurisdiction or 'N/A'}")
    print(f"  Region:        {detail.region or 'N/A'}")
    print(f"  Topics:        {', '.join(detail.topic) if detail.topic else 'N/A'}")
    print(f"  Organization:  {', '.join(detail.organization) if detail.organization else 'N/A'}")
    print(f"  Legal status:  {detail.legal_status.value}")
    print(f"  Valid from:    {detail.valid_from.isoformat() if detail.valid_from else 'N/A'}")
    print(f"  Valid to:      {detail.valid_to.isoformat() if detail.valid_to else 'N/A'}")
    print(f"  Created at:    {detail.created_at.isoformat() if detail.created_at else 'N/A'}")
    print(f"  Document #:    {detail.document_number or 'N/A'}")
    print(f"  Document type: {detail.document_type or 'N/A'}")
    print()

    if detail.citations:
        total_chars = sum(len(c.text) for c in detail.citations)
        print(f"  Citations ({len(detail.citations)}, {total_chars} chars):")
        for i, c in enumerate(detail.citations, 1):
            section = " / ".join(c.section) if c.section else "(root)"
            print(f"    [{i}] Section: {section}")
            print(f"        Text: {c.text[:200]}...")
            print()
    else:
        print("  No citations.\n")


def _format_agent(_detail: DocumentDetail, detail_model: dict[str, Any]) -> None:
    """Agent-facing output — what the agent receives from tool call."""
    print(json.dumps(detail_model, indent=2, ensure_ascii=False))


_FORMATTERS: dict[str, Any] = {
    "human": _format_human,
    "agent": _format_agent,
}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Document detail pipeline demo: get full document card by document_id "
        "(same format as search returns: source_id-publish_id)"
    )
    parser.add_argument(
        "--format",
        choices=["human", "agent"],
        default="agent",
        help="Output format: agent (default, what agent receives), human (readable)",
    )
    parser.add_argument(
        "--input",
        action="store_true",
        help="Instead of fetching document, print example HTTP request info",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=DOCUMENT_ID,
        help=f"Document ID in format 'source_id-publish_id'. Default: {DOCUMENT_ID}",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=QUERY,
        help=f"Search query to filter citations. Default: '{QUERY}'",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Minimum relevance score (0.0-1.0) for citation filtering. Default: 0.5",
    )
    parser.add_argument(
        "--max-citation-length",
        type=int,
        default=2000,
        help="Maximum total citation length in chars. Default: 2000",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=5,
        help="Maximum number of chunks to fetch from Qdrant for citation filtering. Default: 5",
    )
    args = parser.parse_args()

    doc_id = args.document_id

    # ── Input mode: print example request and exit ─────────────────
    if args.input:
        _format_input()
        return

    configure_observability(ObservabilityConfig(log_level="WARNING"))
    tracer = get_tracer()
    cfg = get_config()

    # ── Connect DB ─────────────────────────────────────────────────
    db = DatabaseClient(dsn=cfg.database_url)
    await db.connect()
    print("PostgreSQL connected.", file=sys.stderr)

    # ── Connect Qdrant ─────────────────────────────────────────────
    qdrant = QdrantStore(
        host=cfg.qdrant_host, port=cfg.qdrant_port, vector_size=cfg.embedding.vector_size
    )
    embedder = Embedder(model_name=cfg.embedding.model, vector_size=cfg.embedding.vector_size)
    print("Qdrant connected.", file=sys.stderr)

    # ── Create service ─────────────────────────────────────────────
    service = ODLService(db=db, qdrant=qdrant, embedder=embedder)
    print("ODLService created.", file=sys.stderr)

    # ── Get document detail ────────────────────────────────────────
    print(f"\nDocument ID: {doc_id}", file=sys.stderr)
    if args.query:
        print(f"Query: {args.query}", file=sys.stderr)
    print(file=sys.stderr)

    with tracer.trace(
        "document_detail_pipeline", document_id=doc_id, query=args.query
    ) as root_span:
        root_span.set_input({"document_id": doc_id, "query": args.query})

        try:
            ctx = SearchContext(
                score_threshold=args.score_threshold,
                max_results=args.max_chunks,
            )
            detail = await service.get_document_detail(
                source_id=doc_id,
                query=args.query,
                context=ctx if args.query else None,
                max_citation_length=args.max_citation_length,
            )

            root_span.set_output(
                {
                    "document_id": detail.id,
                    "title": detail.title,
                    "citations_count": len(detail.citations),
                }
            )

            # ── Output ─────────────────────────────────────────────
            detail_model = detail.model_dump(mode="json")
            formatter = _FORMATTERS.get(args.format, _format_agent)
            formatter(detail, detail_model)

        except NotFoundError as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            print(file=sys.stderr)
            print("The document is not in the database.", file=sys.stderr)
            print("To ingest it first, run:", file=sys.stderr)
            print("  uv run python scripts/fixtures_ingest_pipeline.py", file=sys.stderr)
            print(file=sys.stderr)
            root_span.set_error(e)
            sys.exit(1)

    await db.close()
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
