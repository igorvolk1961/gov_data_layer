"""Application entry point — ODL MCP server."""

from __future__ import annotations

from core.observability import configure, get_logger


def main() -> None:
    """Start the ODL MCP server."""
    # Configure observability first
    configure()

    logger = get_logger("odl.main")
    logger.info("Starting ODL MCP server...")

    # TODO: Phase 5 — start MCP server
    # from core.api.server import serve
    # asyncio.run(serve())
    raise NotImplementedError("MCP server not yet implemented — Phase 5")


if __name__ == "__main__":
    main()
