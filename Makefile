.PHONY: up down test lint type-check logs rebuild shell

# Поднять все сервисы
up:
	docker compose up -d

# Остановить все сервисы
down:
	docker compose down

# Прогнать тесты
test:
	docker compose exec app python -m pytest tests/ -v

# Прогнать тесты с проверкой покрытия (локально, без Docker)
test-cov:
	python -m pytest tests/ -v --tb=short \
		--cov=core --cov=adapters \
		--cov-report=term-missing \
		--cov-fail-under=70

# Линтеры
lint:
	ruff check core/ adapters/ tests/
	ruff format --check core/ adapters/ tests/

# Типы
type-check:
	mypy core/ adapters/

# Логи
logs:
	docker compose logs -f app

# Пересобрать приложение
rebuild:
	docker compose build app
	docker compose up -d app

# Открыть shell в контейнере приложения
shell:
	docker compose exec app /bin/bash

# Установить dev-зависимости локально
install-dev:
	pip install -e ".[dev]"

# Инициализировать detect-secrets baseline
secrets-init:
	detect-secrets scan > .secrets.baseline

# Запустить pre-commit на всех файлах
pre-commit-run:
	pre-commit run --all-files
