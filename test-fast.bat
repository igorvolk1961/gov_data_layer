@echo off
REM ============================================================================
REM  test-fast.bat — Быстрый прогон unit-тестов (без интеграционных и slow)
REM
REM  Использование:
REM    test-fast                  — unit-тесты с длительностью топ-5
REM    test-fast -v               — unit-тесты verbose
REM    test-fast -v --durations=0 — unit-тесты с длительностью ВСЕХ тестов
REM
REM  Чтобы исключить конкретный медленный тест вручную:
REM    uv run pytest tests/ -v -k "not test_name"
REM
REM  Чтобы исключить целую группу:
REM    uv run pytest tests/ -v -k "not (integration or slow)"
REM ============================================================================

uv run python -m pytest tests/unit/ -v --tb=short --durations=5 %*
