@echo off
title Desinstalar Sofia Centinela del Inicio de Windows
color 0C
cls
echo ============================================================
echo   DESINSTALADOR DE SOFIA CENTINELA DEL INICIO AUTOMATICO
echo ============================================================
echo.
set SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Sofia_Centinela.lnk

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [OK] El acceso directo de inicio automatico fue eliminado.
    echo Sofia Centinela ya NO arrancara al encender la computadora.
) else (
    echo [INFO] No se encontro el acceso directo en la carpeta de Inicio.
    echo Sofia Centinela no estaba configurado para inicio automatico.
)

echo.
pause
