"""Unit tests for ServerConfig (core/api/config.py).

Tests cover:
- ServerConfig.from_env() with defaults and custom values
- _parse_port with valid/invalid values
- ConfigError on invalid port
- parse_adapters with various inputs
- instantiate_adapter with valid/invalid module paths
"""

from __future__ import annotations

import pytest

from core.api.config import (
    ConfigError,
    ServerConfig,
    instantiate_adapter,
    parse_adapters,
    parse_port,
)


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


class TestParseAdapters:
    """parse_adapters helper."""

    def test_default_when_none(self) -> None:
        """Returns default stub adapter when env var is not set."""
        result = parse_adapters(None)
        assert result == ["adapters.stub:StubAdapter"]

    def test_default_when_empty(self) -> None:
        """Returns default stub adapter when env var is empty string."""
        result = parse_adapters("")
        assert result == ["adapters.stub:StubAdapter"]

    def test_single_adapter(self) -> None:
        """Parses a single adapter spec."""
        result = parse_adapters("adapters.stub:StubAdapter")
        assert result == ["adapters.stub:StubAdapter"]

    def test_multiple_adapters(self) -> None:
        """Parses multiple comma-separated adapter specs."""
        result = parse_adapters("adapters.stub:StubAdapter,adapters.pravo:PravoAdapter")
        assert result == ["adapters.stub:StubAdapter", "adapters.pravo:PravoAdapter"]

    def test_strips_whitespace(self) -> None:
        """Strips whitespace around adapter specs."""
        result = parse_adapters("  adapters.stub:StubAdapter ,  adapters.pravo:PravoAdapter  ")
        assert result == ["adapters.stub:StubAdapter", "adapters.pravo:PravoAdapter"]

    def test_skips_empty_items(self) -> None:
        """Skips empty items from comma-separated list."""
        result = parse_adapters("adapters.stub:StubAdapter,,,adapters.pravo:PravoAdapter")
        assert result == ["adapters.stub:StubAdapter", "adapters.pravo:PravoAdapter"]


class TestInstantiateAdapter:
    """instantiate_adapter helper."""

    def test_stub_adapter(self) -> None:
        """Instantiates StubAdapter successfully."""
        from adapters.stub import StubAdapter

        adapter = instantiate_adapter("adapters.stub", "StubAdapter")
        assert isinstance(adapter, StubAdapter)
        assert adapter.source_id == "stub"

    def test_invalid_module_raises(self) -> None:
        """Raises ConfigError for non-existent module."""
        with pytest.raises(ConfigError, match="Cannot import adapter module"):
            instantiate_adapter("adapters.nonexistent", "SomeAdapter")

    def test_invalid_class_raises(self) -> None:
        """Raises ConfigError for non-existent class in existing module."""
        with pytest.raises(ConfigError, match="Adapter class 'NonExistent' not found"):
            instantiate_adapter("adapters.stub", "NonExistent")


class TestServerConfig:
    """ServerConfig dataclass and from_env()."""

    def test_defaults(self) -> None:
        """from_env() with no env vars set uses defaults."""
        config = ServerConfig.from_env()
        assert config.api_host == "0.0.0.0"
        assert config.api_port == 8000
        assert config.mcp_host == "0.0.0.0"
        assert config.mcp_port == 8001
        assert config.adapters == ["adapters.stub:StubAdapter"]

    def test_custom_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env() reads custom env vars."""
        monkeypatch.setenv("API_HOST", "127.0.0.1")
        monkeypatch.setenv("API_PORT", "9000")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9001")
        monkeypatch.setenv("ADAPTERS", "adapters.stub:StubAdapter,adapters.pravo:PravoAdapter")
        config = ServerConfig.from_env()
        assert config.api_host == "127.0.0.1"
        assert config.api_port == 9000
        assert config.mcp_host == "127.0.0.1"
        assert config.mcp_port == 9001
        assert config.adapters == [
            "adapters.stub:StubAdapter",
            "adapters.pravo:PravoAdapter",
        ]

    def test_partial_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only API_PORT is set; others fall back to defaults."""
        monkeypatch.setenv("API_PORT", "8080")
        config = ServerConfig.from_env()
        assert config.api_port == 8080
        assert config.api_host == "0.0.0.0"
        assert config.mcp_port == 8001
        assert config.adapters == ["adapters.stub:StubAdapter"]

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
            adapters=["adapters.stub:StubAdapter"],
        )
        assert config.api_host == "10.0.0.1"
        assert config.api_port == 3000
        assert config.mcp_host == "10.0.0.2"
        assert config.mcp_port == 3001
        assert config.adapters == ["adapters.stub:StubAdapter"]

    def test_env_not_modified(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env() does not set env vars, only reads them."""
        monkeypatch.delenv("API_HOST", raising=False)
        monkeypatch.delenv("API_PORT", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("ADAPTERS", raising=False)
        config = ServerConfig.from_env()
        assert config.api_host == "0.0.0.0"
        assert config.api_port == 8000


class TestAppConfig:
    """AppConfig — unified config from config.yaml + .env."""

    def test_load_defaults(self, tmp_path, monkeypatch):
        """AppConfig.load() with no config.yaml uses defaults."""
        from core.api.app_config import reload_config

        # Clear env vars that AppConfig.load() reads via os.getenv()
        monkeypatch.delenv("OCR_YA_FOLDER_ID", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("LOG_CLEAR_ON_START", raising=False)
        monkeypatch.delenv("LOG_FILE", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("QDRANT_HOST", raising=False)
        monkeypatch.delenv("QDRANT_PORT", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        monkeypatch.delenv("REDIS_PORT", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        # Point to a non-existent config file to force defaults
        cfg = reload_config(str(tmp_path / "nonexistent.yaml"))
        assert cfg.server.api_host == "0.0.0.0"
        assert cfg.server.api_port == 8000
        assert cfg.server.mcp_host == "0.0.0.0"
        assert cfg.server.mcp_port == 8001
        assert cfg.server.adapters == ["adapters.stub:StubAdapter"]
        assert cfg.ocr.provider == "stub"
        assert cfg.ocr.tesseract_lang == "rus"
        assert cfg.ocr.tesseract_timeout == 30
        assert cfg.ocr.yandex_vision_timeout == 120
        assert cfg.ocr.ya_folder_id == ""
        assert cfg.observability.langfuse_host == "http://localhost:3000"
        assert cfg.observability.langfuse_public_key is None
        assert cfg.observability.log_level == "INFO"
        assert cfg.observability.log_clear_on_start is False
        assert cfg.qdrant_host == "localhost"
        assert cfg.qdrant_port == 6333
        assert cfg.redis_host == "localhost"
        assert cfg.redis_port == 6379
        assert cfg.database_url == "sqlite:///data/official_data.db"

    def test_load_from_yaml(self, tmp_path, monkeypatch):
        """AppConfig.load() reads from a YAML file."""
        from core.api.app_config import reload_config

        # Clear env vars that AppConfig.load() reads via os.getenv()
        monkeypatch.delenv("OCR_YA_FOLDER_ID", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("LOG_CLEAR_ON_START", raising=False)
        monkeypatch.delenv("LOG_FILE", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("QDRANT_HOST", raising=False)
        monkeypatch.delenv("QDRANT_PORT", raising=False)
        monkeypatch.delenv("REDIS_HOST", raising=False)
        monkeypatch.delenv("REDIS_PORT", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        yaml_path = tmp_path / "test_config.yaml"
        yaml_path.write_text(
            """
server:
  api_host: "127.0.0.1"
  api_port: 9000
  mcp_host: "127.0.0.1"
  mcp_port: 9001
adapters:
  - "adapters.stub:StubAdapter"
  - "adapters.pravo:PravoAdapter"
ocr:
  provider: "tesseract"
  tesseract:
    lang: "eng"
    timeout: 60
  yandex_vision:
    timeout: 180
    folder_id: "test-folder"
observability:
  langfuse_host: "http://langfuse:3000"
  log_level: "DEBUG"
  log_clear_on_start: true
  log_file: "data/test.log"
qdrant:
  host: "qdrant"
  port: 6333
redis:
  host: "redis"
  port: 6379
database:
  url: "postgresql://localhost/mydb"
""",
            encoding="utf-8",
        )

        cfg = reload_config(str(yaml_path))
        assert cfg.server.api_host == "127.0.0.1"
        assert cfg.server.api_port == 9000
        assert cfg.server.mcp_host == "127.0.0.1"
        assert cfg.server.mcp_port == 9001
        assert cfg.server.adapters == ["adapters.stub:StubAdapter", "adapters.pravo:PravoAdapter"]
        assert cfg.ocr.provider == "tesseract"
        assert cfg.ocr.tesseract_lang == "eng"
        assert cfg.ocr.tesseract_timeout == 60
        assert cfg.ocr.yandex_vision_timeout == 180
        assert cfg.ocr.ya_folder_id == "test-folder"
        assert cfg.observability.langfuse_host == "http://langfuse:3000"
        assert cfg.observability.log_level == "DEBUG"
        assert cfg.observability.log_clear_on_start is True
        assert cfg.observability.log_file == "data/test.log"
        assert cfg.qdrant_host == "qdrant"
        assert cfg.qdrant_port == 6333
        assert cfg.redis_host == "redis"
        assert cfg.redis_port == 6379
        assert cfg.database_url == "postgresql://localhost/mydb"

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        """Environment variables override config.yaml values."""
        from core.api.app_config import reload_config

        yaml_path = tmp_path / "test_config.yaml"
        yaml_path.write_text(
            """
server:
  api_host: "0.0.0.0"
  api_port: 8000
observability:
  log_level: "INFO"
  log_file: "data/traces.log"
qdrant:
  host: "localhost"
  port: 6333
redis:
  host: "localhost"
  port: 6379
database:
  url: "sqlite:///data/official_data.db"
""",
            encoding="utf-8",
        )

        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("QDRANT_HOST", "qdrant-prod")
        monkeypatch.setenv("DATABASE_URL", "postgresql://prod/db")

        cfg = reload_config(str(yaml_path))
        assert cfg.observability.log_level == "DEBUG"
        assert cfg.qdrant_host == "qdrant-prod"
        assert cfg.database_url == "postgresql://prod/db"
        # Non-overridden values stay from yaml
        assert cfg.server.api_host == "0.0.0.0"
        assert cfg.server.api_port == 8000
        assert cfg.qdrant_port == 6333

    def test_get_config_lazy(self):
        """get_config() returns a singleton, reload_config() resets it."""
        from core.api.app_config import get_config, reload_config

        c1 = get_config()
        c2 = get_config()
        assert c1 is c2  # same instance

        reload_config()
        c3 = get_config()
        assert c3 is not c1  # new instance after reload
