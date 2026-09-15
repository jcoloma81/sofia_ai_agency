@echo off
title Sofia Bridge - Conector para Microsoft Excel
color 0A
cls
echo ============================================================
echo           SOFIA BRIDGE - CONECTOR PARA EXCEL
echo ============================================================
echo.
echo Conectando con Sofia en la nube...
echo.

if not exist config.json (
    echo [CONFIGURACION INICIAL]
    echo No se encontro config.json. Creando uno por defecto...
    echo {"merchant_phone": "5493434991122", "server_url": "https://sofia-ai-agency.onrender.com", "excel_path": "ferreteria_demo.xlsx"} > config.json
    echo Archivo config.json creado. Editalo con tu numero si es necesario.
    echo.
)

python sofia_bridge.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error ejecutando Python. Si tienes el ejecutable Sofia_Bridge.exe,
    echo ejecutalo directamente con doble clic.
    pause
)
