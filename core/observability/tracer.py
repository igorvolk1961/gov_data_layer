"""Unified tracing interface (Tracer Protocol).

Two implementations:
- LangFuseTracer — sends traces to LangFuse (via langfuse SDK).
- FileFallbackTracer — writes JSON logs to a file when LangFuse is unavailable.

Errors (ERROR+) are duplicated to console via logger.py.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from core.observability.config import ObservabilityConfig
from core.observability.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────
#  Внутренние типы
# ──────────────────────────────────────────────


@dataclass
class SpanData:
    """Data for a single span/trace for serialization."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: str
    end_time: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    level: str = "INFO"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "tags": self.tags,
            "level": self.level,
        }


# ──────────────────────────────────────────────
#  Span — контекстный менеджер
# ──────────────────────────────────────────────


class _Span:
    """Internal span implementation.

    Not intended for direct use — created via Tracer.
    """

    def __init__(
        self,
        name: str,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        tags: dict[str, str] | None = None,
        *,
        _write_callback: Any = None,
    ) -> None:
        self._data = SpanData(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            start_time=datetime.now(timezone.utc).isoformat(),
            tags=tags or {},
        )
        self._write_callback = _write_callback
        self._langfuse_span = None

    def set_input(self, data: dict[str, Any]) -> None:
        """Record span input data."""
        self._data.input = data
        if self._langfuse_span is not None:
            self._langfuse_span.update(input=data)

    def set_output(self, data: dict[str, Any]) -> None:
        """Record span output data."""
        self._data.output = data
        if self._langfuse_span is not None:
            self._langfuse_span.update(output=data)

    def set_error(self, error: BaseException) -> None:
        """Record span error."""
        self._data.error = f"{type(error).__name__}: {error}"
        self._data.level = "ERROR"
        if self._langfuse_span is not None:
            self._langfuse_span.update(level="ERROR", status_message=str(error))

    def __enter__(self) -> _Span:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self._data.end_time = datetime.now(timezone.utc).isoformat()
        if exc_val and not self._data.error:
            # Record all exceptions (Exception and BaseException like KeyboardInterrupt)
            self.set_error(exc_val)
        if self._write_callback:
            with contextlib.suppress(Exception):
                self._write_callback(self._data)
        # Also print to console for real-time visibility
        short = f"[{self._data.level}] {self._data.name}"
        if self._data.trace_id:
            short += f" (trace:{self._data.trace_id[:8]}"
            if self._data.parent_span_id:
                short += f" parent:{self._data.parent_span_id[:8]}"
            short += ")"
        if self._data.error:
            short += f" ERROR: {self._data.error[:100]}"
        if self._data.output:
            short += f" -> {self._data.output}"
        if self._data.input:
            short += f" <- {self._data.input}"
        print(short)


# ──────────────────────────────────────────────
#  Tracer Protocol (ABC)
# ──────────────────────────────────────────────


class Tracer(ABC):
    """Abstract base class for tracing.

    Usage:
        with tracer.trace("operation_name", query="...") as span:
            span.set_input({"query": query})
            result = do_work()
            span.set_output({"result": result})
    """

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the tracer backend is available and operational."""
        ...

    @abstractmethod
    def trace(
        self,
        name: str,
        trace_id: str | None = None,
        **tags: str,
    ) -> _Span:
        """Create a root trace (top-level operation).

        Args:
            name: Operation name (e.g. "search_documents").
            trace_id: Optional trace ID. Auto-generated if not provided.
            **tags: Metadata tags for filtering.

        Returns:
            _Span: context manager.
        """
        ...

    @abstractmethod
    def span(
        self,
        name: str,
        parent: _Span | None = None,
        **tags: str,
    ) -> _Span:
        """Create a child span inside an existing trace.

        Args:
            name: Span name.
            parent: Parent span. If None, creates a root trace.
            **tags: Metadata tags.

        Returns:
            _Span: context manager.
        """
        ...


# ──────────────────────────────────────────────
#  LangFuseTracer
# ──────────────────────────────────────────────


class LangFuseTracer(Tracer):
    """Tracer implementation via LangFuse SDK.

    Requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to be set.
    """

    _VERIFY_TTL: float = 60.0  # Re-check connection at most once per 60 seconds

    def __init__(self, config: ObservabilityConfig) -> None:
        self._config = config
        self._client: Any = None
        self._connection_verified: bool = False
        self._last_verify_time: float = 0.0
        self._init_client()

    def _init_client(self) -> None:
        """Initialize LangFuse client (lazy — no network call)."""
        if not self._config.langfuse_public_key or not self._config.langfuse_secret_key:
            logger.warning(
                "langfuse keys not set, skipping initialization (host=%s)",
                self._config.langfuse_host,
            )
            self._client = None
            return
        try:
            from langfuse import Langfuse
        except ImportError as e:
            logger.error(
                "langfuse package not installed — falling back to file tracer: %s",
                e,
            )
            self._client = None
            return

        try:
            self._client = Langfuse(
                host=self._config.langfuse_host,
                public_key=self._config.langfuse_public_key,
                secret_key=self._config.langfuse_secret_key,
            )
            logger.info(
                "langfuse client initialized (lazy) at %s",
                self._config.langfuse_host,
            )
        except (ValueError, TypeError) as e:
            logger.error(
                "langfuse configuration error (host=%s): %s",
                self._config.langfuse_host,
                e,
            )
            self._client = None

    def _verify_connection(self) -> bool:
        """Verify LangFuse connectivity with a lightweight auth check.

        Result is cached for _VERIFY_TTL seconds to avoid per-trace network calls.
        On transient failure, keeps the client and retries after TTL expires.

        Returns True if available, False otherwise.
        """
        if self._client is None:
            return False
        now = time.monotonic()
        if self._connection_verified and (now - self._last_verify_time) < self._VERIFY_TTL:
            return True
        try:
            self._client.auth_check()
            self._connection_verified = True
            self._last_verify_time = now
            return True
        except Exception as e:
            logger.error(
                "langfuse connection check failed — will retry: %s",
                e,
            )
            # Don't set self._client = None — keep client for retry after TTL
            self._connection_verified = False
            self._last_verify_time = now
            return False

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def trace(
        self,
        name: str,
        trace_id: str | None = None,
        **tags: str,
    ) -> _Span:
        tid = trace_id or uuid.uuid4().hex[:16]
        sid = uuid.uuid4().hex[:16]

        if self._verify_connection() and self._client is not None:
            lf_trace = self._client.trace(
                id=tid,
                name=name,
                input=None,
                metadata=tags or None,
            )
            lf_span = lf_trace.span(
                id=sid,
                name=name,
                input=None,
            )

            span = _Span(name, tid, sid, None, tags)
            span._langfuse_span = lf_span
            return span

        return _Span(name, tid, sid, None, tags)

    def span(
        self,
        name: str,
        parent: _Span | None = None,
        **tags: str,
    ) -> _Span:
        if parent is None:
            return self.trace(name, **tags)
        tid = parent._data.trace_id
        pid = parent._data.span_id
        sid = uuid.uuid4().hex[:16]

        if self._verify_connection() and parent._langfuse_span:
            lf_span = parent._langfuse_span.span(
                id=sid,
                name=name,
                input=None,
            )
            span = _Span(name, tid, sid, pid, tags)
            span._langfuse_span = lf_span
            return span

        return _Span(name, tid, sid, pid, tags)


# ──────────────────────────────────────────────
#  FileFallbackTracer
# ──────────────────────────────────────────────


class FileFallbackTracer(Tracer):
    """Tracer implementation that writes JSON logs to a file.

    Used when LangFuse is unavailable or not configured.
    """

    @property
    def is_available(self) -> bool:
        return True

    def __init__(self, config: ObservabilityConfig) -> None:
        self._config = config
        self._ensure_log_dir()

        if config.log_clear_on_start and os.path.exists(config.log_file):
            try:
                os.remove(config.log_file)
                logger.info("log file cleared on start: %s", config.log_file)
            except OSError as e:
                logger.error(
                    "failed to clear log file %s: %s",
                    config.log_file,
                    e,
                )

    def _ensure_log_dir(self) -> None:
        """Create log file directory if it doesn't exist."""
        log_dir = os.path.dirname(self._config.log_file)
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError as e:
                logger.error(
                    "failed to create log directory %s: %s",
                    log_dir,
                    e,
                )

    def _write(self, data: SpanData) -> None:
        """Write one span to file as a JSON line."""
        try:
            # Ensure directory exists on every write (may have been deleted at runtime)
            log_dir = os.path.dirname(self._config.log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(self._config.log_file, "a", encoding="utf-8") as f:
                line = json.dumps(data.to_dict(), ensure_ascii=False, default=str) + "\n"
                f.write(line)
        except Exception as e:
            logger.error(
                "failed to write trace log to %s: %s",
                self._config.log_file,
                e,
            )

    def trace(
        self,
        name: str,
        trace_id: str | None = None,
        **tags: str,
    ) -> _Span:
        tid = trace_id or uuid.uuid4().hex[:16]
        sid = uuid.uuid4().hex[:16]
        return _Span(name, tid, sid, None, tags, _write_callback=self._write)

    def span(
        self,
        name: str,
        parent: _Span | None = None,
        **tags: str,
    ) -> _Span:
        tid = parent._data.trace_id if parent else uuid.uuid4().hex[:16]
        pid = parent._data.span_id if parent else None
        sid = uuid.uuid4().hex[:16]
        return _Span(name, tid, sid, pid, tags, _write_callback=self._write)


# ──────────────────────────────────────────────
#  Фабрика
# ──────────────────────────────────────────────

_tracer_instance: Tracer | None = None


def create_tracer(config: ObservabilityConfig) -> Tracer:
    """Create the appropriate Tracer based on configuration.

    Priority:
    1. LangFuseTracer — if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
    2. FileFallbackTracer — if LangFuse is not configured or unavailable.

    Args:
        config: Observability configuration.

    Returns:
        Tracer: ready-to-use implementation.
    """
    if config.langfuse_enabled:
        tracer = LangFuseTracer(config)
        # Если LangFuse не инициализировался — fallback на файл
        if tracer.is_available:
            return tracer
        logger.warning("langfuse unavailable, falling back to file tracer")

    return FileFallbackTracer(config)


def get_tracer() -> Tracer:
    """Get the global Tracer instance.

    Must be created via configure() first.

    Returns:
        Tracer: global instance.

    Raises:
        RuntimeError: if Tracer was not initialized.
    """
    if _tracer_instance is None:
        raise RuntimeError("Tracer not initialized. Call configure() first.")
    return _tracer_instance


def set_tracer(tracer: Tracer) -> None:
    """Set the global Tracer instance (for testing)."""
    global _tracer_instance
    _tracer_instance = tracer
