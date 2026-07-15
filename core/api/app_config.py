"""AppConfig — единая конфигурация приложения.

Читает:
- config.yaml — все не-секретные настройки (сервер, OCR, БД, observability)
- .env — только секреты (API-ключи, пароли)

Порядок приоритета (от высшего к низшему):
1. .env (секреты)
2. config.yaml (основные настройки)
3. Значения по умолчанию в коде
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Путь к config.yaml по умолчанию (относительно корня проекта)
_DEFAULT_CONFIG_PATH = "config.yaml"


class ConfigError(ValueError):
    """Configuration error — invalid or missing config."""


def _find_project_root() -> Path:
    """Find project root by looking for pyproject.toml."""
    here = Path(__file__).resolve().parent  # core/api/
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and return as dict."""
    p = Path(path)
    if not p.is_absolute():
        p = _find_project_root() / p
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a nested dict value."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, {})
    return d if d != {} else default


@dataclass
class OCRConfig:
    """OCR configuration."""

    provider: str = "stub"
    tesseract_lang: str = "rus"
    tesseract_timeout: int = 30
    yandex_vision_timeout: int = 120
    ya_folder_id: str = ""


@dataclass
class EmbeddingConfig:
    """Embedding model configuration."""

    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    vector_size: int = 384


@dataclass
class ServerConfig:
    """Server configuration."""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    adapters: list[str] = field(default_factory=lambda: ["adapters.stub:StubAdapter"])


@dataclass
class ObservabilityConfig:
    """Observability configuration."""

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    log_level: str = "INFO"
    log_clear_on_start: bool = False
    log_file: str = "data/traces.log"


@dataclass
class AppConfig:
    """Единая конфигурация приложения.

    Объединяет настройки из config.yaml и .env.
    Секреты из .env имеют приоритет над config.yaml.
    """

    server: ServerConfig = field(default_factory=ServerConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    redis_host: str = "localhost"
    redis_port: int = 6379
    database_url: str = "sqlite:///data/official_data.db"

    @classmethod
    def load(cls, config_path: str | None = None) -> AppConfig:
        """Load configuration from config.yaml and .env.

        Args:
            config_path: Path to config.yaml. If None, uses default 'config.yaml'.

        Returns:
            Populated AppConfig instance.
        """
        cfg = _load_yaml(config_path or _DEFAULT_CONFIG_PATH)

        # --- Server ---
        server_cfg = cfg.get("server", {})
        adapters_raw = cfg.get("adapters")
        adapters_list: list[str] = ["adapters.stub:StubAdapter"]
        if adapters_raw and isinstance(adapters_raw, list):
            adapters_list = [str(a) for a in adapters_raw if a]

        server = ServerConfig(
            api_host=str(server_cfg.get("api_host", "0.0.0.0")),
            api_port=int(server_cfg.get("api_port", 8000)),
            mcp_host=str(server_cfg.get("mcp_host", "0.0.0.0")),
            mcp_port=int(server_cfg.get("mcp_port", 8001)),
            adapters=adapters_list,
        )

        # --- OCR ---
        ocr_cfg = cfg.get("ocr", {})
        tesseract_cfg = ocr_cfg.get("tesseract", {})
        yandex_cfg = ocr_cfg.get("yandex_vision", {})

        # folder_id: config.yaml > .env > default
        ya_folder_id = str(yandex_cfg.get("folder_id", "")) or os.getenv("OCR_YA_FOLDER_ID", "")

        ocr = OCRConfig(
            provider=str(ocr_cfg.get("provider", "stub")),
            tesseract_lang=str(tesseract_cfg.get("lang", "rus")),
            tesseract_timeout=int(tesseract_cfg.get("timeout", 30)),
            yandex_vision_timeout=int(yandex_cfg.get("timeout", 120)),
            ya_folder_id=ya_folder_id,
        )

        # --- Observability ---
        obs_cfg = cfg.get("observability", {})

        # Secrets from .env override config.yaml
        langfuse_public_key = (
            os.getenv("LANGFUSE_PUBLIC_KEY") or obs_cfg.get("langfuse_public_key") or None
        )
        langfuse_secret_key = (
            os.getenv("LANGFUSE_SECRET_KEY") or obs_cfg.get("langfuse_secret_key") or None
        )

        observability = ObservabilityConfig(
            langfuse_host=str(obs_cfg.get("langfuse_host", "http://localhost:3000")),
            langfuse_public_key=str(langfuse_public_key) if langfuse_public_key else None,
            langfuse_secret_key=str(langfuse_secret_key) if langfuse_secret_key else None,
            log_level=str(os.getenv("LOG_LEVEL", obs_cfg.get("log_level", "INFO"))).upper(),
            log_clear_on_start=(
                os.getenv(
                    "LOG_CLEAR_ON_START", str(obs_cfg.get("log_clear_on_start", "false"))
                ).lower()
                == "true"
            ),
            log_file=str(os.getenv("LOG_FILE", obs_cfg.get("log_file", "data/traces.log"))),
        )

        # --- Qdrant ---
        qdrant_cfg = cfg.get("qdrant", {})
        qdrant_host = str(os.getenv("QDRANT_HOST", qdrant_cfg.get("host", "localhost")))
        qdrant_port = int(os.getenv("QDRANT_PORT", qdrant_cfg.get("port", 6333)))

        # --- Redis ---
        redis_cfg = cfg.get("redis", {})
        redis_host = str(os.getenv("REDIS_HOST", redis_cfg.get("host", "localhost")))
        redis_port = int(os.getenv("REDIS_PORT", redis_cfg.get("port", 6379)))

        # --- Database ---
        db_cfg = cfg.get("database", {})
        database_url = str(
            os.getenv("DATABASE_URL", db_cfg.get("url", "sqlite:///data/official_data.db"))
        )

        # --- Embedding ---
        emb_cfg = cfg.get("embedding", {})
        embedding = EmbeddingConfig(
            model=str(
                emb_cfg.get("model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            ),
            vector_size=int(emb_cfg.get("vector_size", 384)),
        )

        return cls(
            server=server,
            ocr=ocr,
            embedding=embedding,
            observability=observability,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            redis_host=redis_host,
            redis_port=redis_port,
            database_url=database_url,
        )


# Global config instance (lazy-loaded)
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Get the global AppConfig instance (lazy-loaded)."""
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config


def reload_config(config_path: str | None = None) -> AppConfig:
    """Reload configuration (useful for tests)."""
    global _config
    _config = AppConfig.load(config_path)
    return _config


__all__ = [
    "AppConfig",
    "ConfigError",
    "EmbeddingConfig",
    "OCRConfig",
    "ObservabilityConfig",
    "ServerConfig",
    "get_config",
    "reload_config",
]
