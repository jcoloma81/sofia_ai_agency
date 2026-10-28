@echo off
title Instalar Sofia Centinela en Inicio de Windows
color 0A
cls
echo ============================================================
echo   INSTALADOR DE SOFIA CENTINELA EN INICIO AUTOMATICO
echo ============================================================
echo.
echo Este script configurara Sofia Centinela para que se abra
echo automaticamente cada vez que se prenda esta computadora.
echo.

set TARGET_EXE=%~dp0Sofia_Centinela.exe
if not exist "%TARGET_EXE%" (
    if exist "%~dp0sofia_desktop_sync.py" (
        set TARGET_EXE=%~dp0iniciar_centinela.bat
    ) else (
        echo [ERROR] No se encontro Sofia_Centinela.exe en esta carpeta.
        echo Asegurate de ejecutar este instalador dentro de la misma
        echo carpeta donde esta Sofia_Centinela.exe.
        echo.
        pause
        exit /b 1
    )
)

echo Creando acceso directo en la carpeta de Inicio de Windows...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup', 'Sofia_Centinela.lnk')); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'Centinela de Sincronizacion Sofia AI'; $s.Save()"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo   [OK] INSTALACION EXITOSA!
    echo ============================================================
    echo A partir de ahora, cuando se prenda la computadora,
    echo Sofia Centinela arrancara solo en segundo plano.
    echo.
    echo Deseas iniciar el Centinela ahora mismo?
    choice /M "Presiona S para SI o N para NO"
    if errorlevel 2 goto fin
    if errorlevel 1 goto arrancar
) else (
    echo.
    echo [AVISO] No se pudo crear el acceso automatico con PowerShell.
    echo Puedes crearlo manualmente:
    echo 1. Haz clic derecho en Sofia_Centinela.exe y elige "Crear acceso directo".
    echo 2. Presiona Windows + R, escribe "shell:startup" y presiona Enter.
    echo 3. Pega el acceso directo en esa carpeta.
    echo.
)

:arrancar
echo.
echo Iniciando Sofia Centinela...
start "" "%TARGET_EXE%"
goto fin

:fin
echo.
pause
