"""Observability configuration.

Reads environment variables and provides ObservabilityConfig dataclass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
    log_file: str = "data/traces.log"

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        """Create config from environment variables.

        Variables:
            LANGFUSE_HOST
            LANGFUSE_PUBLIC_KEY
            LANGFUSE_SECRET_KEY
            LOG_LEVEL
            LOG_CLEAR_ON_START (true/false)
            LOG_FILE
        """
        return cls(
            langfuse_host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_clear_on_start=os.getenv("LOG_CLEAR_ON_START", "false").lower()
            == "true",
            log_file=os.getenv("LOG_FILE", "data/traces.log"),
        )

    @property
    def langfuse_enabled(self) -> bool:
        """LangFuse is considered enabled when both keys are set."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)
