"""Observability configuration.

Reads from AppConfig (config.yaml + .env) and provides ObservabilityConfig dataclass.
Legacy from_env() is kept for backward compatibility but delegates to AppConfig.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _resolve_log_file(path: str) -> str:
    """Resolve a (possibly relative) log file path against the project root.

    The project root is determined by walking up from this file's location
    until ``pyproject.toml`` is found.  This ensures the log file lands in
    the expected location regardless of the process working directory.
    """
    p = Path(path)
    if p.is_absolute():
        return str(p)
    # Walk up from core/observability/ to find the project root
    here = Path(__file__).resolve().parent  # core/observability/
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").is_file():
            return str(parent / p)
    # Fallback: resolve against CWD
    return str(Path.cwd() / p)


@dataclass
class ObservabilityConfig:
    """Observability configuration.

    Attributes:
        langfuse_host: URL of self-hosted LangFuse.
        langfuse_public_key: LangFuse public key (None disables LangFuse).
        langfuse_secret_key: LangFuse secret key.
        log_level: Logging level (DEBUG/INFO/WARNING/ERROR).
        log_clear_on_start: Clear traces.log on application start.
        log_file: Path to fallback log file (used when LangFuse is unavailable).
    """

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    log_level: str = "INFO"
    log_clear_on_start: bool = False
    log_file: str = "logs/traces.log"

    def __post_init__(self) -> None:
        """Resolve relative log_file path to an absolute path."""
        self.log_file = _resolve_log_file(self.log_file)

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        """Create config from AppConfig (config.yaml + .env).

        If legacy env vars (LANGFUSE_HOST, LOG_LEVEL, etc.) are set, uses them directly.
        Otherwise, delegates to the global AppConfig singleton loaded from config.yaml.
        """
        # Check if legacy env vars are set
        has_legacy = any(
            os.getenv(k) is not None
            for k in ("LANGFUSE_HOST", "LOG_LEVEL", "LOG_CLEAR_ON_START", "LOG_FILE")
        )
        if has_legacy:
            return cls(
                langfuse_host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
                langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
                log_clear_on_start=os.getenv("LOG_CLEAR_ON_START", "false").lower() == "true",
                log_file=os.getenv("LOG_FILE", "logs/traces.log"),
            )

        # Use AppConfig (config.yaml + .env)
        try:
            # Lazy import to avoid circular dependency:
            # core.observability.config -> core.api.app_config -> core.api.rest_server -> core.observability
            from core.api.app_config import get_config

            app_cfg = get_config()
            obs = app_cfg.observability
            return cls(
                langfuse_host=obs.langfuse_host,
                langfuse_public_key=obs.langfuse_public_key,
                langfuse_secret_key=obs.langfuse_secret_key,
                log_level=obs.log_level,
                log_clear_on_start=obs.log_clear_on_start,
                log_file=obs.log_file,
            )
        except Exception:
            # Ultimate fallback: hardcoded defaults
            return cls()

    @property
    def langfuse_enabled(self) -> bool:
        """LangFuse is considered enabled when both keys are set."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)
