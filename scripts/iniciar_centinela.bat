@echo off
title Sofia Centinela - Sincronizador de Turnos
color 0B
cls
echo ============================================================
echo   INICIANDO SOFIA CENTINELA
echo ============================================================
echo.

if exist "%~dp0Sofia_Centinela.exe" (
    "%~dp0Sofia_Centinela.exe"
) else (
    python "%~dp0..\sofia_desktop_sync.py"
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un cierre inesperado de Sofia Centinela.
    pause
)
