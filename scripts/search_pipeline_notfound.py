"""Search pipeline — demo: query that SHOULD NOT find results.

Usage:
    uv run python scripts/search_pipeline_notfound.py                        # agent output
    uv run python scripts/search_pipeline_notfound.py --format human         # readable
    uv run python scripts/search_pipeline_notfound.py --format agent         # what agent gets
    uv run python scripts/search_pipeline_notfound.py --input               # JSON request body for REST API
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
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.models.models import SearchContext, SearchResponse
from core.observability import configure as configure_observability
from core.observability import get_tracer
from core.odl_service import ODLService
from core.persistence import DatabaseClient

load_dotenv()

# ── Query ──────────────────────────────────────────────────────────────
# Document 0001202012230060 is about child benefits, so a query
# about completely unrelated topics should yield no results.
QUERY = "правила дорожного движения штрафы за превышение скорости"


def _build_request_body() -> dict[str, Any]:
    """Build JSON body for POST /api/v1/search."""
    return {
        "query": QUERY,
        "offset": 0,
        "limit": 5,
        "region": None,
        "topic": None,
        "score_threshold": None,
    }


def _format_input() -> None:
    """Print JSON request body for POST /api/v1/search."""
    body = _build_request_body()
    print(json.dumps(body, indent=2, ensure_ascii=False))


def _format_human(response: SearchResponse, _response_model: dict[str, Any]) -> None:
    """Human-readable output (console-friendly)."""
    if response.results:
        print(f"\nFound {response.total_count} result(s) — expected none:\n")
        for i, r in enumerate(response.results, 1):
            print(f"  [{i}] {r.title}")
            print(f"      Snippet: {r.snippet[:200]}...")
            print(f"      Score:   {r.confidence.retrieval_relevance:.4f}")
            print()
    else:
        print("\nNo results found (expected — query is unrelated to document content).\n")


def _format_agent(_response: SearchResponse, response_model: dict[str, Any]) -> None:
    """Agent-facing output — what the agent receives from tool call."""
    print(json.dumps(response_model, indent=2, ensure_ascii=False))


_FORMATTERS: dict[str, Any] = {
    "human": _format_human,
    "agent": _format_agent,
}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search pipeline demo: query that SHOULD NOT find results"
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
        help="Instead of running search, print JSON request body for POST /api/v1/search",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.5,
        help="Minimum relevance score (0.0-1.0). Results below threshold are excluded. "
        "Default: 0.5. Pass 0 to disable filtering.",
    )
    args = parser.parse_args()

    # ── Input mode: print request body and exit ───────────────────────
    if args.input:
        _format_input()
        return

    configure_observability()
    tracer = get_tracer()
    cfg = get_config()

    # ── Connect DB ────────────────────────────────────────────────────
    db = DatabaseClient(dsn=cfg.database_url)
    await db.connect()
    print("PostgreSQL connected.", file=sys.stderr)

    # ── Connect Qdrant ────────────────────────────────────────────────
    qdrant = QdrantStore(
        host=cfg.qdrant_host, port=cfg.qdrant_port, vector_size=cfg.embedding.vector_size
    )
    embedder = Embedder(model_name=cfg.embedding.model, vector_size=cfg.embedding.vector_size)
    print("Qdrant connected.", file=sys.stderr)

    # ── Create service ────────────────────────────────────────────────
    service = ODLService(db=db, qdrant=qdrant, embedder=embedder)
    print("ODLService created.", file=sys.stderr)

    # ── Search ────────────────────────────────────────────────────────
    print(f"\nSearch query: {QUERY}", file=sys.stderr)
    print(file=sys.stderr)

    with tracer.trace("search_pipeline_notfound", query=QUERY[:100]) as root_span:
        root_span.set_input({"query": QUERY})

        context = SearchContext(
            max_results=5,
            score_threshold=args.score_threshold,
        )
        response = await service.search_documents(QUERY, context=context, parent_span=root_span)

        root_span.set_output(
            {
                "total_count": response.total_count,
                "results_count": len(response.results),
                "score_threshold": args.score_threshold,
            }
        )

    # ── Output ────────────────────────────────────────────────────────
    response_model = response.model_dump(mode="json")
    formatter = _FORMATTERS.get(args.format, _format_agent)
    formatter(response, response_model)

    await db.close()
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
