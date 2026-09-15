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
echo Compilando tools\sofia_bridge.py en un unico archivo .EXE...
pyinstaller --onefile --name "Sofia_Bridge" --icon=NONE tools\sofia_bridge.py
echo.
if exist dist\Sofia_Bridge.exe (
    echo ============================================================
    echo    COMPILACION EXITOSA: dist\Sofia_Bridge.exe
    echo ============================================================
    echo Puedes copiar ese archivo y compartirlo por WhatsApp o pendrive.
) else (
    echo Hubo un problema al compilar. Revisa los mensajes anteriores.
)
pause
