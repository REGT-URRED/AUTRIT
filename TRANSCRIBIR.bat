@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title TRANSCRIPTOR AUTOMATICO (Listo para usar con o sin GPU)
color 0B

set "WSLD=Ubuntu"
set "MODE=none"
set "WIN_PY="

set "DRV=%~d0"
set "DRV=!DRV::=!"
for %%A in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do if /i "!DRV!"=="%%A" set "DRV=%%A"
set "PTH=%~p0"
set "PTH_WSL=!PTH:\=/!"
set "SCRIPT_WSL=/mnt/!DRV!!PTH_WSL!transcribe_cli.py"
set "SETUP_WSL=/mnt/!DRV!!PTH_WSL!setup_env.py"
set "SCRIPT_WIN=%~dp0transcribe_cli.py"
set "SETUP_WIN=%~dp0setup_env.py"

if not defined TRANSCRIPTOR_BACKEND set "TRANSCRIPTOR_BACKEND=auto"
if not defined TRANSCRIPTOR_DEVICE set "TRANSCRIPTOR_DEVICE=auto"

echo ============================================================
echo   TRANSCRIPTOR AUTOMATICO DE AUDIO Y VIDEO   (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧
echo   Funciona automaticamente con Tarjeta de Video o Procesador
echo   Tus textos listos se guardan en: %~dp0salidas\
echo ============================================================
echo.

:: 1) Detectar entorno: WSL Ubuntu -> Python nativo Windows -> Auto-instalar Python
where wsl.exe >nul 2>&1
if not errorlevel 1 (
  wsl.exe -d %WSLD% -- test -x /usr/bin/python3 >nul 2>&1
  if not errorlevel 1 (
    set "MODE=wsl"
    goto entorno_ok
  )
)

:buscar_py_win
where py >nul 2>&1
if not errorlevel 1 (
  py -3 --version >nul 2>&1
  if not errorlevel 1 (
    set "MODE=win"
    set "WIN_PY=py -3"
    goto entorno_ok
  )
)

where python >nul 2>&1
if not errorlevel 1 (
  python --version >nul 2>&1
  if not errorlevel 1 (
    set "MODE=win"
    set "WIN_PY=python"
    goto entorno_ok
  )
)

:: Revisar rutas tipicas donde Windows instala Python aunque aun no refresque el PATH
for %%P in (
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
) do (
  if exist %%~P (
    set "MODE=win"
    set "WIN_PY="%%~P""
    goto entorno_ok
  )
)

echo [PREPARANDO] Esta computadora no tiene Python instalado todavia.
where winget >nul 2>&1
if not errorlevel 1 (
  echo Instalando Python automaticamente, por favor espera unos segundos...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%ProgramFiles%\Python312\python.exe"
  ) do (
    if exist %%~P (
      set "MODE=win"
      set "WIN_PY="%%~P""
      goto entorno_ok
    )
  )
)

echo [AVISO] Descargando instalador oficial de Python...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '$env:TEMP\py_setup.exe'; Start-Process -FilePath '$env:TEMP\py_setup.exe' -ArgumentList '/passive InstallAllUsers=0 PrependPath=1 Include_test=0' -Wait"
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  set "MODE=win"
  set "WIN_PY="%LocalAppData%\Programs\Python\Python312\python.exe""
  goto entorno_ok
)

echo [ERROR] No se pudo instalar Python automaticamente. Verifica tu conexion a internet.
goto final

:entorno_ok
if "%MODE%"=="wsl" (
  wsl.exe -d %WSLD% -- /usr/bin/python3 "!SETUP_WSL!" --check >nul 2>&1
  if errorlevel 1 (
    echo [PRIMERA VEZ] Preparando todo automaticamente para tu computadora...
    wsl.exe -d %WSLD% -- /usr/bin/python3 "!SETUP_WSL!"
    if errorlevel 1 (
      echo [AVISO] Reintentando reparacion automatica...
      wsl.exe -d %WSLD% -- /usr/bin/python3 "!SETUP_WSL!" --repair
    )
  )
) else (
  %WIN_PY% "!SETUP_WIN!" --check >nul 2>&1
  if errorlevel 1 (
    echo [PRIMERA VEZ] Preparando todo automaticamente para tu computadora...
    %WIN_PY% "!SETUP_WIN!"
    if errorlevel 1 (
      echo [AVISO] Reintentando reparacion automatica...
      %WIN_PY% "!SETUP_WIN!" --repair
    )
  )
)

:: Si el usuario arrastro archivos sobre el icono, procesarlos de inmediato sin preguntar nada
if not "%~1"=="" goto procesar_args

:: Si hizo doble clic, darle 4 segundos: si no toca nada, arranca solo en modo automatico
echo.
echo ============================================================
echo   ¿QUE DESEAS HACER?
echo   [Enter] Transcribir ahora (Automatico)
echo   [2]     Cambiar formato / idioma (Texto, Subtitulos, etc.)
echo   [3]     Cambiar modelo de Inteligencia Artificial
echo   [4]     Reparar programa automaticamente
echo ============================================================
choice /c 1234 /n /t 4 /d 1 /m "Iniciando automaticamente en 4 segundos (o presiona 2, 3, 4): "
set "CH=%errorlevel%"

if "%CH%"=="2" (
  call :run_setup_cmd --prefs
  goto modo_auto
)
if "%CH%"=="3" (
  call :run_setup_cmd --force
  goto modo_auto
)
if "%CH%"=="4" (
  call :run_setup_cmd --repair
  goto modo_auto
)

:modo_auto
echo.
if "%MODE%"=="wsl" (
  wsl.exe -d %WSLD% -- /usr/bin/python3 "!SCRIPT_WSL!" --auto-run --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE%
) else (
  set "PY_BIN=%~dp0.venv_win\Scripts\python.exe"
  if exist "!PY_BIN!" (
    "!PY_BIN!" "!SCRIPT_WIN!" --auto-run --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE%
  ) else (
    %WIN_PY% "!SCRIPT_WIN!" --auto-run --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE%
  )
)
goto final

:procesar_args
set "EXTRA_FLAGS="
if defined TRANSCRIPTOR_PRESET set "EXTRA_FLAGS=!EXTRA_FLAGS! --preset %TRANSCRIPTOR_PRESET%"
if defined TRANSCRIPTOR_FORMAT set "EXTRA_FLAGS=!EXTRA_FLAGS! --format %TRANSCRIPTOR_FORMAT%"
set /a TOTAL=0
for %%F in (%*) do set /a TOTAL+=1
set /a IDX=0

:porcada
if "%~1"=="" goto final
set /a IDX+=1
set "SRC=%~f1"
call :procesar
shift
goto porcada

:run_setup_cmd
if "%MODE%"=="wsl" (
  wsl.exe -d %WSLD% -- /usr/bin/python3 "!SETUP_WSL!" %*
) else (
  %WIN_PY% "!SETUP_WIN!" %*
)
exit /b 0

:procesar
set /a FALTAN=TOTAL-IDX
echo.
echo ------------------------------------------------------------
if %TOTAL% GTR 1 (
  echo  Cola   : [!IDX!/!TOTAL! - faltan !FALTAN!]  (ง •̀_•́^)ง
)
echo  Archivo: %SRC%
echo  Salida : %~dp0salidas\
echo ------------------------------------------------------------

if "%MODE%"=="wsl" (
  wsl.exe -d %WSLD% -- /usr/bin/python3 "!SCRIPT_WSL!" --src "!SRC!" --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE% !EXTRA_FLAGS! --queue-idx !IDX! --queue-total !TOTAL!
) else (
  set "PY_BIN=%~dp0.venv_win\Scripts\python.exe"
  if exist "!PY_BIN!" (
    "!PY_BIN!" "!SCRIPT_WIN!" --src "!SRC!" --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE% !EXTRA_FLAGS! --queue-idx !IDX! --queue-total !TOTAL!
  ) else (
    %WIN_PY% "!SCRIPT_WIN!" --src "!SRC!" --backend %TRANSCRIPTOR_BACKEND% --device %TRANSCRIPTOR_DEVICE% !EXTRA_FLAGS! --queue-idx !IDX! --queue-total !TOTAL!
  )
)
exit /b 0

:final
echo.
echo Proceso finalizado. Presiona cualquier tecla para cerrar esta ventana...
pause >nul
