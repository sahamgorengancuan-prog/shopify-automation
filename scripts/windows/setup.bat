@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM  ARCHIVIST — Windows setup (targets Python 3.14)
REM
REM  Order of preference:
REM    1. py -3.14                    (official launcher, best case)
REM    2. python on PATH, 3.10+       (works fine, prints a note)
REM    3. embeddable Python 3.14      (downloaded into %LOCALAPPDATA%)
REM
REM  Writes env.cmd next to this script so the launchers skip detection.
REM ===================================================================

REM --- resolve layout: zip bundle (flat) or repo checkout (scripts\windows) ---
set "HERE=%~dp0"
set "ROOT=%HERE%"
if not exist "!ROOT!requirements.txt" (
    for %%i in ("%HERE%..\..") do set "ROOT=%%~fi\"
)
cd /d "!ROOT!"
set "PYVER=3.14.0"
set "EMBED_DIR=%LOCALAPPDATA%\archivist\python%PYVER%"
set "EMBED_EXE=%EMBED_DIR%\python.exe"
set "VENV_DIR=!ROOT!.venv"
set "LIBS_DIR=!ROOT!libs"

echo.
echo   ARCHIVIST — setup
echo   -----------------------------------------------------------
echo.

REM --- 1. py launcher, 3.14 -------------------------------------------
set "BASE_PY="
py -3.14 -c "import sys" >nul 2>&1
if !errorlevel! equ 0 (
    set "BASE_PY=py -3.14"
    echo   [ok] found Python 3.14 via the py launcher
)

REM --- 2. python on PATH ----------------------------------------------
if not defined BASE_PY (
    python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2" %%v in ('python -V 2^>^&1') do set "FOUND=%%v"
        set "BASE_PY=python"
        echo   [ok] using python !FOUND! from PATH ^(3.14 preferred, this works too^)
    )
)

REM --- 3. embeddable Python 3.14 --------------------------------------
if not defined BASE_PY (
    if exist "%EMBED_EXE%" (
        set "BASE_PY=%EMBED_EXE%"
        echo   [ok] using the embeddable Python already in %EMBED_DIR%
    ) else (
        echo   [..] no Python found — downloading the embeddable Python %PYVER%
        mkdir "%EMBED_DIR%" 2>nul
        set "ZIP=%TEMP%\python-%PYVER%-embed-amd64.zip"
        curl -L --fail --silent --show-error -o "!ZIP!" ^
            "https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"
        if !errorlevel! neq 0 (
            echo   [!!] download failed. Install Python 3.14 from https://www.python.org/downloads/
            echo        then run this script again.
            exit /b 1
        )
        tar -xf "!ZIP!" -C "%EMBED_DIR%" 2>nul
        if !errorlevel! neq 0 (
            powershell -NoProfile -Command "Expand-Archive -Force '!ZIP!' '%EMBED_DIR%'" || (
                echo   [!!] could not unpack the archive & exit /b 1
            )
        )
        REM the embeddable build ships with site-packages disabled
        for %%f in ("%EMBED_DIR%\python*._pth") do (
            powershell -NoProfile -Command ^
              "(Get-Content '%%f') -replace '^#\s*import site','import site' | Set-Content '%%f'"
        )
        curl -L --fail --silent --show-error -o "%TEMP%\get-pip.py" https://bootstrap.pypa.io/get-pip.py
        "%EMBED_EXE%" "%TEMP%\get-pip.py" --no-warn-script-location
        set "BASE_PY=%EMBED_EXE%"
        echo   [ok] embeddable Python %PYVER% installed in %EMBED_DIR%
    )
)

REM --- environment ------------------------------------------------------
REM A real install gets a venv; the embeddable build cannot make one, so its
REM packages go into .\libs and PYTHONPATH points at them.
set "MODE=venv"
echo %BASE_PY% | findstr /i "archivist\\python" >nul && set "MODE=embed"

if "%MODE%"=="venv" (
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        echo   [..] creating the virtual environment
        %BASE_PY% -m venv "%VENV_DIR%" || (echo   [!!] venv creation failed & exit /b 1)
    )
    set "RUN_PY=%VENV_DIR%\Scripts\python.exe"
) else (
    mkdir "%LIBS_DIR%" 2>nul
    set "RUN_PY=%EMBED_EXE%"
)

echo   [..] installing dependencies ^(this takes a few minutes the first time^)
if "%MODE%"=="venv" (
    "!RUN_PY!" -m pip install --upgrade pip --quiet
    "!RUN_PY!" -m pip install -r "!ROOT!requirements.txt" --quiet || (
        echo   [!!] dependency install failed & exit /b 1
    )
) else (
    "!RUN_PY!" -m pip install --target "%LIBS_DIR%" -r "!ROOT!requirements.txt" --quiet ^
        --no-warn-script-location || (echo   [!!] dependency install failed & exit /b 1)
)

REM --- remember what we resolved ---------------------------------------
> "!ROOT!env.cmd" (
    echo @echo off
    echo set "ARCHIVIST_PY=!RUN_PY!"
    echo set "ARCHIVIST_MODE=%MODE%"
    if "%MODE%"=="embed" echo set "PYTHONPATH=%LIBS_DIR%"
)

if not exist "!ROOT!.env" (
    if exist "!ROOT!.env.example" copy /y "!ROOT!.env.example" "!ROOT!.env" >nul
    echo   [ok] created .env — add your API keys there, or in the Setup tab of the app
)

echo.
echo   [ok] setup complete
echo        run_archivist.bat        launch the app
echo        run_pipeline.bat "topic" one headless run
echo.
endlocal
exit /b 0
