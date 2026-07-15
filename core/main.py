"""Application entry point — ODL REST + MCP server.

Creates adapters from config → ODLService → RESTServer + MCPServer.
MCP server is mounted as an SSE application on the same uvicorn port
under the /mcp path, allowing both servers to run in a single process.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import cast

import uvicorn
from dotenv import load_dotenv

from adapters.base.source_adapter import SourceAdapter
from core.api.app_config import get_config
from core.api.config import ConfigError, ServerConfig, instantiate_adapter
from core.api.mcp_server import create_mcp_server
from core.api.rest_server import create_app
from core.cache import CacheClient
from core.index.qdrant_store import QdrantStore
from core.ingest.embedder import Embedder
from core.observability import configure as configure_observability
from core.observability import get_logger, get_tracer
from core.observability.logger import VALID_LOG_LEVELS, get_effective_level_name, reconfigure
from core.odl_service import ODLService
from core.persistence import DatabaseClient


async def _run_server(
    rest_server: uvicorn.Server,
    db: DatabaseClient | None = None,
) -> None:
    """Run the uvicorn server with graceful shutdown support.

    Performs a startup healthcheck: if DatabaseClient is configured, verifies
    connectivity before the server starts listening. Fail-fast on failure.

    Args:
        rest_server: The uvicorn server instance to run.
        db: Optional DatabaseClient to close on shutdown.
    """
    # Startup healthcheck — fail fast if DB is configured but unavailable
    if db is not None:
        try:
            await db.connect()
            get_logger("odl.main").info(
                "Database healthcheck passed — PostgreSQL is available",
            )
        except Exception:
            get_logger("odl.main").critical(
                "Database healthcheck FAILED — PostgreSQL is unavailable. "
                "Check database_url and ensure PostgreSQL is running.",
            )
            sys.exit(1)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        """Trigger graceful shutdown on SIGINT/SIGTERM."""
        stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue  # SIGTERM is not available on Windows
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler —
            # use call_soon_threadsafe to schedule on the event loop safely
            signal.signal(sig, lambda _signum, _frame: loop.call_soon_threadsafe(stop_event.set))

    server_task = asyncio.create_task(rest_server.serve())
    try:
        await stop_event.wait()
        rest_server.should_exit = True
        await server_task
    finally:
        # Gracefully close the database connection pool
        if db is not None and db.available:
            await db.close()
        tracer = get_tracer()
        if tracer is not None:
            with tracer.trace("server.shutdown") as span:
                span.set_output({"status": "stopped"})


def main() -> None:
    """Start the ODL REST + MCP server.

    MCP server is mounted as an SSE application under the /mcp path.
    REST API is available at /api/v1/* and /docs.
    """
    # Load .env before any config reads
    load_dotenv()

    # Re-apply LOG_LEVEL now that .env is loaded (module-level get_logger()
    # calls in tracer.py / stub_adapter.py may have triggered
    # _ensure_configured() before dotenv was available).
    reconfigure()

    configure_observability()

    logger = get_logger("odl.main")

    # Load AppConfig (config.yaml + .env) — triggers lazy load of get_config()
    try:
        from core.api.app_config import AppConfig

        AppConfig.load()  # validate config on startup
    except Exception as e:
        logger.critical("Configuration error: %s", e)
        sys.exit(1)

    try:
        config = ServerConfig.from_env()
    except ConfigError as e:
        logger.critical("Configuration error: %s", e)
        sys.exit(1)

    logger.info("Starting ODL servers...")

    # Write a startup trace to verify file logging works
    tracer = get_tracer()
    with tracer.trace("server.startup") as span:
        span.set_input({"host": config.api_host, "port": config.api_port})
        span.set_output({"status": "started"})

    # Create adapters from config → service → servers
    adapters: list[SourceAdapter] = [
        cast(SourceAdapter, instantiate_adapter(*adapter_path.rsplit(":", 1)))
        for adapter_path in config.adapters
    ]
    logger.info(
        "Loaded adapters: %s",
        [a.source_id for a in adapters],
    )

    # Create cache client (lazy — no connection attempt until first use)
    app_config = get_config()
    cache = CacheClient(host=app_config.redis_host, port=app_config.redis_port)
    logger.info(
        "Cache client created (Redis at %s:%s — lazy connect)",
        app_config.redis_host,
        app_config.redis_port,
    )

    # Create database client (lazy — no connection attempt until first use)
    db: DatabaseClient | None = None
    if app_config.database_url:
        db = DatabaseClient(dsn=app_config.database_url)
        logger.info(
            "Database client created (PostgreSQL — lazy connect)",
        )

    # Create Qdrant vector store
    qdrant_store = QdrantStore(
        host=app_config.qdrant_host,
        port=app_config.qdrant_port,
        vector_size=app_config.embedding.vector_size,
    )
    logger.info(
        "QdrantStore created (%s:%s, vector_size=%d)",
        app_config.qdrant_host,
        app_config.qdrant_port,
        app_config.embedding.vector_size,
    )

    # Create embedder
    embedder = Embedder(
        model_name=app_config.embedding.model,
        vector_size=app_config.embedding.vector_size,
    )
    logger.info(
        "Embedder created (model=%s, vector_size=%d)",
        app_config.embedding.model,
        app_config.embedding.vector_size,
    )

    service = ODLService(
        adapters=adapters, cache=cache, db=db, qdrant=qdrant_store, embedder=embedder
    )

    # Create FastAPI app (REST) with cache and db for health check
    app = create_app(service, cache=cache, db=db)

    # Create MCP server and mount as SSE app under /mcp
    mcp_server = create_mcp_server(service)
    mcp_sse_app = mcp_server.sse_app(mount_path="/mcp")
    app.mount("/mcp", mcp_sse_app)

    logger.info(
        "Starting server on http://%s:%s",
        config.api_host,
        config.api_port,
    )
    logger.info("Swagger UI: http://localhost:%s/docs", config.api_port)
    logger.info("MCP SSE endpoint: http://localhost:%s/mcp", config.api_port)

    # Reuse the effective log level from core.observability.logger
    _uvicorn_level = get_effective_level_name().lower()
    if _uvicorn_level not in VALID_LOG_LEVELS:
        _uvicorn_level = "error"

    rest_config = uvicorn.Config(
        app,
        host=config.api_host,
        port=config.api_port,
        log_level=_uvicorn_level,
    )
    rest_server = uvicorn.Server(rest_config)

    asyncio.run(_run_server(rest_server, db=db))


if __name__ == "__main__":
    main()
