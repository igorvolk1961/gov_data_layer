"""Server configuration.

Reads environment variables (already loaded by main.py via dotenv)
and provides ServerConfig dataclass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Configuration error — invalid or missing environment variable."""


def parse_port(key: str, default: str) -> int:
    """Parse a port number from an environment variable.

    Args:
        key: Environment variable name.
        default: Default value string.

    Returns:
        Parsed port number.

    Raises:
        ConfigError: If the value is not a valid integer.
    """
    val = os.getenv(key, default)
    try:
        return int(val)
    except ValueError:
        raise ConfigError(f"Environment variable {key} must be an integer, got '{val}'") from None


@dataclass
class ServerConfig:
    """Server configuration.

    Attributes:
        api_host: REST API host.
        api_port: REST API port.
        mcp_host: MCP server host.
        mcp_port: MCP server port.
    """

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Create config from environment variables.

        Expects .env to have been loaded by main.py before this is called.

        Variables:
            API_HOST (default: 0.0.0.0)
            API_PORT (default: 8000)
            MCP_HOST (default: 0.0.0.0)
            MCP_PORT (default: 8001)
        """

        return cls(
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=parse_port("API_PORT", "8000"),
            mcp_host=os.getenv("MCP_HOST", "0.0.0.0"),
            mcp_port=parse_port("MCP_PORT", "8001"),
        )


__all__ = [
    "ConfigError",
    "ServerConfig",
    "parse_port",
]
