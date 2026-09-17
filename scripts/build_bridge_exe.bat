@echo off
title Compilar Sofia Bridge a .EXE
color 0B
cls
echo ============================================================
echo        COMPILADOR DE SOFIA BRIDGE A EJECUTABLE (.EXE)
echo ============================================================
echo.
echo Instalando dependencias necesarias...
pip install pyinstaller openpyxl httpx pywin32
echo.
set SCRIPT_FILE=sofia_bridge.py
if not exist "%SCRIPT_FILE%" (
    if exist "tools\sofia_bridge.py" (
        set SCRIPT_FILE=tools\sofia_bridge.py
    )
)

echo Compilando %SCRIPT_FILE% en un unico archivo .EXE...
pyinstaller --noconfirm --onefile --name "Sofia_Bridge" --icon=NONE "%SCRIPT_FILE%"
echo.
if exist dist\Sofia_Bridge.exe (
    echo ============================================================
    echo    COMPILACION EXITOSA: dist\Sofia_Bridge.exe
    echo ============================================================
    echo Puedes copiar ese archivo junto a config.json y compartirlo.
) else (
    echo Hubo un problema al compilar. Revisa los mensajes anteriores.
)
pause
