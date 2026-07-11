"""Server configuration.

Reads environment variables (already loaded by main.py via dotenv)
and provides ServerConfig dataclass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module


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


def parse_adapters(adapters_str: str | None) -> list[str]:
    """Parse ADAPTERS env var into a list of fully-qualified class paths.

    Format: comma-separated list of module:ClassName pairs.
    Example: "adapters.stub:StubAdapter,adapters.pravo:PravoAdapter"

    Args:
        adapters_str: Raw value of ADAPTERS env var.

    Returns:
        List of "module:ClassName" strings.
    """
    if not adapters_str:
        return ["adapters.stub:StubAdapter"]
    return [item.strip() for item in adapters_str.split(",") if item.strip()]


def instantiate_adapter(module_path: str, class_name: str) -> object:
    """Dynamically import and instantiate an adapter class.

    Args:
        module_path: Dotted module path (e.g. 'adapters.stub').
        class_name: Name of the adapter class (e.g. 'StubAdapter').

    Returns:
        An instance of the adapter class.

    Raises:
        ConfigError: If the module or class cannot be loaded.
    """
    try:
        module = import_module(module_path)
    except ImportError as e:
        raise ConfigError(f"Cannot import adapter module '{module_path}': {e}") from None
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise ConfigError(
            f"Adapter class '{class_name}' not found in module '{module_path}': {e}"
        ) from None
    return cls()


@dataclass
class ServerConfig:
    """Server configuration.

    Attributes:
        api_host: REST API host.
        api_port: REST API port.
        mcp_host: MCP server host.
        mcp_port: MCP server port.
        adapters: List of "module:ClassName" strings for source adapters.
    """

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    adapters: list[str] = field(default_factory=lambda: ["adapters.stub:StubAdapter"])

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Create config from environment variables.

        Expects .env to have been loaded by main.py before this is called.

        Variables:
            API_HOST (default: 0.0.0.0)
            API_PORT (default: 8000)
            MCP_HOST (default: 0.0.0.0)
            MCP_PORT (default: 8001)
            ADAPTERS (default: adapters.stub:StubAdapter)
                Comma-separated list of "module:ClassName" pairs.
                Example: "adapters.stub:StubAdapter,adapters.pravo:PravoAdapter"
        """

        return cls(
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=parse_port("API_PORT", "8000"),
            mcp_host=os.getenv("MCP_HOST", "0.0.0.0"),
            mcp_port=parse_port("MCP_PORT", "8001"),
            adapters=parse_adapters(os.getenv("ADAPTERS")),
        )


__all__ = [
    "ConfigError",
    "ServerConfig",
    "instantiate_adapter",
    "parse_adapters",
    "parse_port",
]
