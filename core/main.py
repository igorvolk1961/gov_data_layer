"""Application entry point — ODL REST + MCP server.

Создаёт адаптеры из конфига → ODLService → RESTServer (+ MCPServer).
Запуск REST и MCP параллельно через asyncio.gather.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import cast

import uvicorn
from dotenv import load_dotenv

from adapters.base.source_adapter import SourceAdapter
from core.api.config import ConfigError, ServerConfig, instantiate_adapter
from core.api.rest_server import create_app
from core.observability import configure as configure_observability
from core.observability import get_logger, get_tracer
from core.observability.logger import VALID_LOG_LEVELS, get_effective_level_name, reconfigure
from core.odl_service import ODLService


async def _run_rest_server(
    app: uvicorn.Server,
    logger: logging.Logger,
) -> None:
    """Run REST server until shutdown is requested."""
    logger.info("REST server started")
    await app.serve()
    logger.info("REST server stopped")


async def _run_mcp_server(
    logger: logging.Logger,
) -> None:
    """Run MCP server (placeholder — will be implemented in Phase 5)."""
    logger.info(
        "MCP server placeholder — not yet implemented (Phase 5)",
    )
    # TODO: Phase 5 — replace with actual MCP server
    # from core.api.server import serve as mcp_serve
    # await mcp_serve()
    await asyncio.Event().wait()  # sleep forever until cancelled


async def _run_servers(
    rest_server: uvicorn.Server,
    logger: logging.Logger,
) -> None:
    """Run REST and MCP servers concurrently."""
    tasks = [
        asyncio.create_task(_run_rest_server(rest_server, logger)),
        #        asyncio.create_task(_run_mcp_server(logger)),
    ]
    _, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )
    # If one server finished (e.g. MCP placeholder cancelled), cancel the other
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    """Start the ODL REST server (and MCP server when implemented)."""
    # Load .env before any config reads
    load_dotenv()

    # Re-apply LOG_LEVEL now that .env is loaded (module-level get_logger()
    # calls in tracer.py / stub_adapter.py may have triggered
    # _ensure_configured() before dotenv was available).
    reconfigure()

    configure_observability()

    logger = get_logger("odl.main")

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
    service = ODLService(adapters=adapters)

    # Create FastAPI app
    app = create_app(service)

    # Run REST server
    logger.info(
        "Starting REST server on http://%s:%s",
        config.api_host,
        config.api_port,
    )
    logger.info("Swagger UI: http://localhost:%s/docs", config.api_port)

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

    try:
        asyncio.run(_run_servers(rest_server, logger))
    finally:
        with tracer.trace("server.shutdown") as span:
            span.set_output({"status": "stopped"})


if __name__ == "__main__":
    main()
