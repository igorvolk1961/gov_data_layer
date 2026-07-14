@echo off
REM Линтеры, форматтер и тесты (без медленных тестов)
REM Запускать из корня проекта (D:\git\gov_data_layer)

echo ========================================
echo [1/4] ruff format (check only)
echo ========================================
uv run ruff format --check . || (
    echo [INFO] ruff format хочет отформатировать файлы. Запустите: uv run ruff format .
    exit /b 1
)
echo [OK] ruff format passed
echo.

echo ========================================
echo [2/4] ruff check
echo ========================================
uv run ruff check . || (
    echo [ERROR] ruff check завершился с ошибкой
    exit /b 1
)
echo [OK] ruff check passed
echo.

echo ========================================
echo [3/4] mypy
echo ========================================
uv run mypy . || (
    echo [ERROR] mypy завершился с ошибкой
    exit /b 1
)
echo [OK] mypy passed
echo.

echo ========================================
echo [4/4] pytest (without 35-page PDF)
echo ========================================
uv run pytest ./tests -k "not slow" --tb=short -q || (
    echo [ERROR] pytest завершился с ошибкой
    exit /b 1
)
echo [OK] pytest passed
echo.

echo ========================================
echo All checks passed!
echo ========================================
