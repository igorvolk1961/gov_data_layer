FROM python:3.10-slim AS builder

WORKDIR /app

# Установка системных зависимостей для сборки
# libpq-dev зарезервирован для будущей миграции на PostgreSQL (см. SPEC.md §7)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python (кэшируется, пока pyproject.toml не меняется)
# Dev-зависимости (pytest, ruff, mypy) не нужны в production-образе
COPY pyproject.toml ./
RUN pip install --no-cache-dir "."


FROM python:3.10-slim

WORKDIR /app

# Установка runtime-системных зависимостей (только curl для healthcheck)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование установленных пакетов из builder-стадии (только site-packages, без build-инструментов)
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Копирование исходного кода
COPY core/ ./core/
COPY adapters/ ./adapters/
COPY README.md ./

# Директория для данных (SQLite, логи)
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "core.main"]
