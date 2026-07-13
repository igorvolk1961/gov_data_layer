@echo off
REM Синхронизация зависимостей проекта через uv
REM Запускать из корня проекта (D:\git\gov_data_layer)

echo [1/2] Синхронизация основных + dev зависимостей...
uv sync --group dev

if %ERRORLEVEL% neq 0 (
    echo [ERROR] uv sync завершился с ошибкой (код: %ERRORLEVEL%)
    exit /b %ERRORLEVEL%
)

echo [2/2] Проверка целостности uv.lock...
uv lock --check

if %ERRORLEVEL% neq 0 (
    echo [WARN] uv lock --check выявил несоответствия. Запустите 'uv lock' для обновления.
) else (
    echo [OK] Все зависимости синхронизированы и согласованы.
)
