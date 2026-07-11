@echo off
uv run python -m pytest tests/ -v --tb=short --cov=core --cov=adapters --cov-report=term-missing --cov-fail-under=70
