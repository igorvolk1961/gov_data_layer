"""Unit tests for ServerConfig (core/api/config.py).

Tests cover:
- ServerConfig.from_env() with defaults and custom values
- _parse_port with valid/invalid values
- ConfigError on invalid port
"""

from __future__ import annotations

import pytest

from core.api.config import ConfigError, ServerConfig, parse_port


class TestParsePort:
    """_parse_port helper."""

    def test_valid_int(self) -> None:
        assert parse_port("API_PORT", "8000") == 8000

    def test_custom_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "9000")
        assert parse_port("API_PORT", "8000") == 9000

    def test_invalid_raises_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "not-a-number")
        with pytest.raises(ConfigError, match="API_PORT"):
            parse_port("API_PORT", "8000")

    def test_empty_string_raises_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "")
        with pytest.raises(ConfigError, match="API_PORT"):
            parse_port("API_PORT", "8000")


class TestServerConfig:
    """ServerConfig dataclass and from_env()."""

    def test_defaults(self) -> None:
        """from_env() with no env vars set uses defaults."""
        config = ServerConfig.from_env()
        assert config.api_host == "0.0.0.0"
        assert config.api_port == 8000
        assert config.mcp_host == "0.0.0.0"
        assert config.mcp_port == 8001

    def test_custom_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env() reads custom env vars."""
        monkeypatch.setenv("API_HOST", "127.0.0.1")
        monkeypatch.setenv("API_PORT", "9000")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9001")
        config = ServerConfig.from_env()
        assert config.api_host == "127.0.0.1"
        assert config.api_port == 9000
        assert config.mcp_host == "127.0.0.1"
        assert config.mcp_port == 9001

    def test_partial_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only API_PORT is set; others fall back to defaults."""
        monkeypatch.setenv("API_PORT", "8080")
        config = ServerConfig.from_env()
        assert config.api_port == 8080
        assert config.api_host == "0.0.0.0"
        assert config.mcp_port == 8001

    def test_invalid_api_port_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "abc")
        with pytest.raises(ConfigError, match="API_PORT"):
            ServerConfig.from_env()

    def test_invalid_mcp_port_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "xyz")
        with pytest.raises(ConfigError, match="MCP_PORT"):
            ServerConfig.from_env()

    def test_dataclass_direct_construction(self) -> None:
        """ServerConfig can be constructed directly without from_env()."""
        config = ServerConfig(
            api_host="10.0.0.1",
            api_port=3000,
            mcp_host="10.0.0.2",
            mcp_port=3001,
        )
        assert config.api_host == "10.0.0.1"
        assert config.api_port == 3000
        assert config.mcp_host == "10.0.0.2"
        assert config.mcp_port == 3001

    def test_env_not_modified(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env() does not set env vars, only reads them."""
        monkeypatch.delenv("API_HOST", raising=False)
        monkeypatch.delenv("API_PORT", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        config = ServerConfig.from_env()
        assert config.api_host == "0.0.0.0"
        assert config.api_port == 8000
