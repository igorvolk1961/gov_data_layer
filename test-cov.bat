@echo off
uv run python -m pytest tests/ -v --tb=short -k "not test_yandex_vision_multi_page_pdf" --cov=core --cov=adapters --cov-report=term-missing --cov-fail-under=70
