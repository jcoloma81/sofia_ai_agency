@echo off
title Compilar Sofia Centinela a .EXE
color 0B
cls
echo ============================================================
echo      COMPILADOR DE SOFIA CENTINELA A EJECUTABLE (.EXE)
echo ============================================================
echo.
echo 1. Instalando / Verificando dependencias necesarias en Windows...
pip install pyinstaller openpyxl
echo.

set SCRIPT_DIR=%~dp0..
set SCRIPT_FILE=%SCRIPT_DIR%\sofia_desktop_sync.py

if not exist "%SCRIPT_FILE%" (
    echo [ERROR] No se encontro %SCRIPT_FILE%.
    echo Asegurate de ejecutar este script desde la carpeta scripts.
    pause
    exit /b 1
)

echo 2. Compilando Sofia Centinela en un unico archivo .EXE...
pyinstaller --noconfirm --onefile --name "Sofia_Centinela" --console "%SCRIPT_FILE%"

echo.
if exist dist\Sofia_Centinela.exe (
    echo ============================================================
    echo    COMPILACION EXITOSA: dist\Sofia_Centinela.exe
    echo ============================================================
    echo.
    echo 3. Preparando el paquete listo para el cliente en dist\...
    
    if exist "%SCRIPT_DIR%\centinela_config.json" (
        copy /Y "%SCRIPT_DIR%\centinela_config.json" dist\centinela_config.json >nul
    )
    copy /Y "%~dp0instalar_en_inicio_windows.bat" dist\instalar_en_inicio_windows.bat >nul
    copy /Y "%~dp0desinstalar_de_inicio_windows.bat" dist\desinstalar_de_inicio_windows.bat >nul
    
    echo.
    echo [LISTO] La carpeta "dist" contiene todo el paquete para la clinica:
    echo  - Sofia_Centinela.exe
    echo  - centinela_config.json
    echo  - instalar_en_inicio_windows.bat
    echo  - desinstalar_de_inicio_windows.bat
    echo.
    echo Solo copia esa carpeta dist a un pendrive y llevala a la clinica!
) else (
    echo [ERROR] Hubo un problema al compilar. Revisa los mensajes anteriores.
)
echo.
pause
