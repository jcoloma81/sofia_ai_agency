@echo off
title Sofia Centinela - Instalacion Automatica
color 0A
cls
echo ============================================================
echo   INSTALANDO SOFIA CENTINELA EN ESTA COMPUTADORA...
echo ============================================================
echo.

set TARGET_EXE=%~dp0Sofia_Centinela.exe
if not exist "%TARGET_EXE%" (
    if exist "%~dp0sofia_desktop_sync.py" (
        set TARGET_EXE=%~dp0iniciar_centinela.bat
    ) else (
        echo [ERROR] No se encontro Sofia_Centinela.exe en esta carpeta.
        echo Asegurate de descomprimir todos los archivos juntos.
        echo.
        pause
        exit /b 1
    )
)

echo [1/2] Configurando inicio automatico con Windows...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup', 'Sofia_Centinela.lnk')); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'Centinela de Sincronizacion Sofia AI'; $s.Save()"

echo [2/2] Iniciando Sofia Centinela en segundo plano...
start "" "%TARGET_EXE%"

echo.
echo ============================================================
echo   LISTO! INSTALACION COMPLETADA CON EXITO.
echo ============================================================
echo Sofia Centinela ya esta activo y vigilando tu Excel.
echo Arrancara automaticamente cada vez que prendas la PC.
echo.
echo Esta ventana se cerrara sola en 3 segundos...
timeout /t 3 >nul
exit
