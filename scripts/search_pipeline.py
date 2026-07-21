"""Search pipeline — demo with query from file.

Usage:
    uv run python scripts/search_pipeline.py                          # uses scripts/queries/found.txt
    uv run python scripts/search_pipeline.py --not-found              # uses scripts/queries/notfound.txt
    uv run python scripts/search_pipeline.py --query-file PATH        # uses arbitrary file
    uv run python scripts/search_pipeline.py --format human           # readable output
    uv run python scripts/search_pipeline.py --format agent           # what agent gets (default)
    uv run python scripts/search_pipeline.py --input                  # JSON request body for REST API
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
from core.observability import ObservabilityConfig, get_tracer
from core.observability import configure as configure_observability
from core.odl_service import ODLService
from core.persistence import DatabaseClient

load_dotenv()

QUERIES_DIR = Path(__file__).resolve().parent / "queries"


def _read_query(path: Path) -> str:
    """Read and return the first non-empty line from *path*."""
    text = path.read_text(encoding="utf-8").strip()
    return text.splitlines()[0] if text else ""


def _build_request_body(query: str) -> dict[str, Any]:
    """Build JSON body for POST /api/v1/search."""
    return {
        "query": query,
        "offset": 0,
        "limit": 5,
        "region": None,
        "topic": None,
        "score_threshold": None,
    }


def _format_input(query: str) -> None:
    """Print JSON request body for POST /api/v1/search."""
    body = _build_request_body(query)
    print(json.dumps(body, indent=2, ensure_ascii=False))


def _format_human(response: SearchResponse, _response_model: dict[str, Any], query: str) -> None:
    """Human-readable output (console-friendly)."""
    if response.results:
        print(f"\nQuery: {query}")
        print(f"Found {response.total_count} result(s):\n")
        for i, r in enumerate(response.results, 1):
            print(f"  [{i}] {r.title}")
            print(f"      Snippet: {r.snippet[:200]}...")
            print(f"      Source:  {r.source_name}")
            print(f"      URL:     {r.url}")
            print(f"      Score:   {r.confidence.retrieval_relevance:.4f}")
            print()
    else:
        print(f"\nQuery: {query}")
        print("No results found (expected if query is unrelated to document content).\n")


def _format_agent(_response: SearchResponse, response_model: dict[str, Any], _query: str) -> None:
    """Agent-facing output — what the agent receives from tool call."""
    print(json.dumps(response_model, indent=2, ensure_ascii=False))


_FORMATTERS: dict[str, Any] = {
    "human": _format_human,
    "agent": _format_agent,
}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Search pipeline demo — query read from file")
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

    # Query source group
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--not-found",
        action="store_true",
        help="Use query from queries/notfound.txt (expected to find nothing)",
    )
    group.add_argument(
        "--query-file",
        type=str,
        default=None,
        help="Path to file containing the search query",
    )
    args = parser.parse_args()

    # Resolve query
    if args.query_file:
        query_path = Path(args.query_file)
    elif args.not_found:
        query_path = QUERIES_DIR / "notfound.txt"
    else:
        query_path = QUERIES_DIR / "found.txt"

    query = _read_query(query_path)
    if not query:
        print(f"Error: query file {query_path} is empty or not readable.", file=sys.stderr)
        sys.exit(1)

    # ── Input mode: print request body and exit ───────────────────────
    if args.input:
        _format_input(query)
        return

    configure_observability(ObservabilityConfig(log_level="WARNING"))
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
    print(f"\nQuery: {query}", file=sys.stderr)
    print(file=sys.stderr)

    with tracer.trace("search_pipeline", query=query[:100]) as root_span:
        root_span.set_input({"query": query})

        context = SearchContext(
            max_results=5,
            score_threshold=args.score_threshold,
        )
        response = await service.search_documents(query, context=context, parent_span=root_span)

        root_span.set_output(
            {
                "total_count": response.total_count,
                "results_count": len(response.results),
            }
        )

    # ── Output ────────────────────────────────────────────────────────
    response_model = response.model_dump(mode="json")
    formatter = _FORMATTERS.get(args.format, _format_agent)
    formatter(response, response_model, query)

    await db.close()
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
