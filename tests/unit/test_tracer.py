"""Unit tests for observability tracing (core/observability/tracer.py).

Tests cover:
- _Span context manager: enter/exit, set_input, set_output, error handling
- FileFallbackTracer: trace, span with/without parent, file writing
- LangFuseTracer: initialization without keys, fallback behavior
- create_tracer factory: selection logic
- ObservabilityConfig: from_env, langfuse_enabled
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator

import pytest

from core.observability.config import ObservabilityConfig
from core.observability.tracer import (
    FileFallbackTracer,
    LangFuseTracer,
    SpanData,
    _Span,
    create_tracer,
    get_tracer,
    set_tracer,
)

# ──────────────────────────────────────────────
#  SpanData
# ──────────────────────────────────────────────


class TestSpanData:
    def test_minimal(self) -> None:
        data = SpanData(
            name="test",
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id=None,
            start_time="2026-01-01T00:00:00",
        )
        assert data.name == "test"
        assert data.end_time is None
        assert data.level == "INFO"

    def test_to_dict(self) -> None:
        data = SpanData(
            name="test",
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id="parent-1",
            start_time="2026-01-01T00:00:00",
            end_time="2026-01-01T00:00:01",
            input={"key": "value"},
            output={"result": 42},
            tags={"env": "test"},
            level="ERROR",
        )
        d = data.to_dict()
        assert d["name"] == "test"
        assert d["parent_span_id"] == "parent-1"
        assert d["input"] == {"key": "value"}
        assert d["level"] == "ERROR"


# ──────────────────────────────────────────────
#  _Span
# ──────────────────────────────────────────────


class TestSpan:
    def test_enter_exit_sets_end_time(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        assert span._data.end_time is None
        with span:
            pass
        assert span._data.end_time is not None

    def test_set_input(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        span.set_input({"query": "test"})
        assert span._data.input == {"query": "test"}

    def test_set_output(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        span.set_output({"result": "ok"})
        assert span._data.output == {"result": "ok"}

    def test_set_error(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        span.set_error(ValueError("bad value"))
        assert "ValueError: bad value" in span._data.error  # type: ignore[operator]
        assert span._data.level == "ERROR"

    def test_exception_in_context_sets_error(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        with pytest.raises(RuntimeError), span:
            raise RuntimeError("something went wrong")
        assert span._data.error is not None
        assert "RuntimeError" in span._data.error
        assert span._data.level == "ERROR"

    def test_exception_in_context_sets_end_time(self) -> None:
        span = _Span("test", "trace-1", "span-1", None)
        with pytest.raises(ValueError), span:
            raise ValueError("fail")
        assert span._data.end_time is not None

    def test_set_error_with_base_exception(self) -> None:
        """set_error should accept BaseException (not just Exception)."""
        span = _Span("test", "trace-1", "span-1", None)
        span.set_error(KeyboardInterrupt())
        assert "KeyboardInterrupt" in span._data.error  # type: ignore[operator]
        assert span._data.level == "ERROR"

    def test_keyboard_interrupt_recorded_as_error(self) -> None:
        """Non-Exception BaseExceptions should be recorded as errors."""
        span = _Span("test", "trace-1", "span-1", None)
        with pytest.raises(KeyboardInterrupt), span:
            raise KeyboardInterrupt()
        assert span._data.error is not None
        assert span._data.level == "ERROR"

    def test_parent_span_id(self) -> None:
        child = _Span("child", "trace-1", "span-2", "span-1")
        assert child._data.parent_span_id == "span-1"

    def test_tags(self) -> None:
        span = _Span("test", "trace-1", "span-1", None, tags={"env": "test", "version": "1"})
        assert span._data.tags == {"env": "test", "version": "1"}

    def test_write_callback_called_on_exit(self) -> None:
        written: list[SpanData] = []

        def callback(data: SpanData) -> None:
            written.append(data)

        span = _Span("test", "trace-1", "span-1", None, _write_callback=callback)
        with span:
            span.set_input({"x": 1})
        assert len(written) == 1
        assert written[0].name == "test"
        assert written[0].input == {"x": 1}


# ──────────────────────────────────────────────
#  FileFallbackTracer
# ──────────────────────────────────────────────


@pytest.fixture
def temp_log_file() -> Generator[str, None, None]:
    """Create a temporary file path for trace logs."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def file_tracer(temp_log_file: str) -> FileFallbackTracer:
    config = ObservabilityConfig(log_file=temp_log_file, log_clear_on_start=False)
    return FileFallbackTracer(config)


class TestFileFallbackTracer:
    def test_is_available(self, file_tracer: FileFallbackTracer) -> None:
        assert file_tracer.is_available is True

    def test_trace_creates_span(self, file_tracer: FileFallbackTracer) -> None:
        span = file_tracer.trace("op1")
        assert isinstance(span, _Span)
        assert span._data.name == "op1"
        assert span._data.parent_span_id is None

    def test_trace_with_tags(self, file_tracer: FileFallbackTracer) -> None:
        span = file_tracer.trace("op1", source="stub", env="test")
        assert span._data.tags == {"source": "stub", "env": "test"}

    def test_trace_with_trace_id(self, file_tracer: FileFallbackTracer) -> None:
        span = file_tracer.trace("op1", trace_id="my-trace")
        assert span._data.trace_id == "my-trace"

    def test_span_with_parent(self, file_tracer: FileFallbackTracer) -> None:
        parent = file_tracer.trace("parent")
        child = file_tracer.span("child", parent=parent)
        assert child._data.parent_span_id == parent._data.span_id
        assert child._data.trace_id == parent._data.trace_id

    def test_span_without_parent_creates_root(self, file_tracer: FileFallbackTracer) -> None:
        span = file_tracer.span("orphan")
        assert span._data.parent_span_id is None

    def test_writes_to_file_on_exit(
        self, file_tracer: FileFallbackTracer, temp_log_file: str
    ) -> None:
        with file_tracer.trace("write-test") as span:
            span.set_input({"key": "value"})
            span.set_output({"result": "done"})

        assert os.path.exists(temp_log_file)
        with open(temp_log_file, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["name"] == "write-test"
        assert record["input"] == {"key": "value"}
        assert record["output"] == {"result": "done"}
        assert record["end_time"] is not None

    def test_writes_multiple_spans(
        self, file_tracer: FileFallbackTracer, temp_log_file: str
    ) -> None:
        with file_tracer.trace("first"):
            pass
        with file_tracer.trace("second"):
            pass

        with open(temp_log_file, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_clear_on_start(self, temp_log_file: str) -> None:
        # Write something first
        with open(temp_log_file, "w", encoding="utf-8") as f:
            f.write("old data\n")

        config = ObservabilityConfig(log_file=temp_log_file, log_clear_on_start=True)
        tracer = FileFallbackTracer(config)
        with tracer.trace("new"):
            pass

        with open(temp_log_file, encoding="utf-8") as f:
            content = f.read()
        assert "old data" not in content
        assert "new" in content


# ──────────────────────────────────────────────
#  LangFuseTracer
# ──────────────────────────────────────────────


class TestLangFuseTracer:
    def test_without_keys_is_not_available(self) -> None:
        config = ObservabilityConfig(langfuse_public_key=None, langfuse_secret_key=None)
        tracer = LangFuseTracer(config)
        assert tracer.is_available is False

    def test_without_keys_trace_creates_span(self) -> None:
        config = ObservabilityConfig(langfuse_public_key=None, langfuse_secret_key=None)
        tracer = LangFuseTracer(config)
        span = tracer.trace("op1")
        assert isinstance(span, _Span)
        # No langfuse span attached
        assert span._langfuse_span is None

    def test_without_keys_span_creates_span(self) -> None:
        config = ObservabilityConfig(langfuse_public_key=None, langfuse_secret_key=None)
        tracer = LangFuseTracer(config)
        parent = tracer.trace("parent")
        child = tracer.span("child", parent=parent)
        assert child._data.parent_span_id == parent._data.span_id

    def test_without_keys_span_without_parent(self) -> None:
        config = ObservabilityConfig(langfuse_public_key=None, langfuse_secret_key=None)
        tracer = LangFuseTracer(config)
        span = tracer.span("orphan")
        assert span._data.parent_span_id is None


# ──────────────────────────────────────────────
#  create_tracer factory
# ──────────────────────────────────────────────


class TestCreateTracer:
    def test_langfuse_disabled_returns_file_tracer(self) -> None:
        config = ObservabilityConfig(langfuse_public_key=None, langfuse_secret_key=None)
        tracer = create_tracer(config)
        assert isinstance(tracer, FileFallbackTracer)

    def test_langfuse_enabled_but_no_keys_returns_file_tracer(self) -> None:
        """langfuse_enabled is True only when both keys are set."""
        config = ObservabilityConfig(
            langfuse_public_key=None,
            langfuse_secret_key=None,
        )
        assert config.langfuse_enabled is False
        tracer = create_tracer(config)
        assert isinstance(tracer, FileFallbackTracer)

    def test_langfuse_enabled_with_keys_returns_langfuse_tracer(self) -> None:
        """With keys set, LangFuseTracer is created (but may be unavailable)."""
        config = ObservabilityConfig(
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
        )
        assert config.langfuse_enabled is True
        tracer = create_tracer(config)
        # LangFuseTracer is created, but is_available may be False
        # (no real LangFuse server running in tests)
        assert isinstance(tracer, LangFuseTracer)


# ──────────────────────────────────────────────
#  ObservabilityConfig
# ──────────────────────────────────────────────


class TestObservabilityConfig:
    def test_defaults(self) -> None:
        config = ObservabilityConfig()
        assert config.langfuse_host == "http://localhost:3000"
        assert config.langfuse_public_key is None
        assert config.langfuse_secret_key is None
        assert config.log_level == "INFO"
        assert config.log_clear_on_start is False
        assert config.log_file == "data/traces.log"

    def test_langfuse_enabled_false_by_default(self) -> None:
        config = ObservabilityConfig()
        assert config.langfuse_enabled is False

    def test_langfuse_enabled_true_with_keys(self) -> None:
        config = ObservabilityConfig(
            langfuse_public_key="pk-xxx",
            langfuse_secret_key="sk-xxx",
        )
        assert config.langfuse_enabled is True

    def test_langfuse_enabled_false_with_only_one_key(self) -> None:
        config = ObservabilityConfig(
            langfuse_public_key="pk-xxx",
            langfuse_secret_key=None,
        )
        assert config.langfuse_enabled is False

    def test_from_env_without_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without env vars, from_env should return defaults."""
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("LOG_FILE", raising=False)
        config = ObservabilityConfig.from_env()
        assert config.langfuse_host == "http://localhost:3000"
        assert config.langfuse_public_key is None
        assert config.log_level == "INFO"

    def test_from_env_with_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-env")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-env")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LOG_FILE", "/tmp/test.log")
        monkeypatch.setenv("LOG_CLEAR_ON_START", "true")
        config = ObservabilityConfig.from_env()
        assert config.langfuse_host == "https://langfuse.example.com"
        assert config.langfuse_public_key == "pk-env"
        assert config.langfuse_secret_key == "sk-env"
        assert config.log_level == "DEBUG"
        assert config.log_file == "/tmp/test.log"
        assert config.log_clear_on_start is True
        assert config.langfuse_enabled is True


# ──────────────────────────────────────────────
#  Global tracer (set_tracer / get_tracer)
# ──────────────────────────────────────────────


class TestGlobalTracer:
    @pytest.fixture(autouse=True)
    def _save_global_tracer(self) -> Generator[None, None, None]:
        """Save and restore the global tracer to avoid leaking state between tests."""
        try:
            saved = get_tracer()
        except RuntimeError:
            saved = None
        yield
        if saved is not None:
            set_tracer(saved)

    def test_set_and_get(self) -> None:
        config = ObservabilityConfig(log_file="test.jsonl", log_clear_on_start=False)
        tracer = FileFallbackTracer(config)
        set_tracer(tracer)
        retrieved = get_tracer()
        assert retrieved is tracer

    def test_get_without_set_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("core.observability.tracer._tracer_instance", None)
        with pytest.raises(RuntimeError, match="not initialized"):
            get_tracer()
