@echo off
chcp 65001 >nul
title ODL Server Stopper

:: Accept port as first argument, default to 8000
set PORT=%1
if "%PORT%"=="" set PORT=8000

echo Searching for ODL server on port %PORT%...

:: Use PowerShell for robust port-to-PID resolution
:: This handles varying netstat output formats across Windows versions/locales
for /f "usebackq tokens=*" %%a in (`
    powershell -NoProfile -Command ^
        "$port = %PORT%; ^
         $p = netstat -ano ^| Where-Object { $_ -match (':' + $port + '\s') -and $_ -match 'LISTENING' }; ^
         if ($p) { ($p -split '\s+')[-1] } else { Write-Output '' }"
`) do (
    set "PID=%%a"
)

if "%PID%"=="" (
    echo [INFO] No server found on port %PORT%.
    goto :end
)

:found
echo Found process PID=%PID%
echo Stopping gracefully...

:: First try graceful stop (Ctrl+C equivalent)
taskkill /PID %PID% 2>nul
if %ERRORLEVEL% equ 0 (
    echo [OK] Server stopped gracefully.
    goto :end
)

:: If graceful fails, force kill
echo Graceful stop failed, forcing...
taskkill /PID %PID% /F
if %ERRORLEVEL% equ 0 (
    echo [OK] Server forcefully stopped.
) else (
    echo [ERROR] Failed to stop server.
)

:end
echo.
pause
