@echo off
uv run python -m pytest tests/ -v --tb=short --durations=10 -k "not slow" --cov=core --cov=adapters --cov-report=term-missing --cov-fail-under=70
