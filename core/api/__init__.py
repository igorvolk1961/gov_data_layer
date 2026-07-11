"""API layer — REST server, MCP server stub, and configuration."""

from core.api.config import ServerConfig
from core.api.rest_server import create_app
from core.api.server import serve

__all__ = [
    "ServerConfig",
    "create_app",
    "serve",
]
