@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM  ARCHIVIST — launch the Gradio control room on Windows.
REM  Any arguments are passed through, e.g.:
REM     run_archivist.bat --port 8000 --scheduler
REM ===================================================================

REM --- resolve layout: zip bundle (flat) or repo checkout (scripts\windows) ---
set "HERE=%~dp0"
set "ROOT=%HERE%"
if not exist "%ROOT%requirements.txt" (
    for %%i in ("%HERE%..\..") do set "ROOT=%%~fi\"
)
cd /d "!ROOT!"

if not exist "!ROOT!env.cmd" (
    echo   first run — setting up
    call "%HERE%setup.bat" || exit /b 1
)
call "!ROOT!env.cmd"

if not exist "!ARCHIVIST_PY!" (
    echo   environment looks broken — re-running setup
    call "%HERE%setup.bat" || exit /b 1
    call "!ROOT!env.cmd"
)

set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--port 7860 --open"

echo.
echo   ARCHIVIST — starting the control room
echo   the browser opens at http://127.0.0.1:7860  (ctrl-c here to stop)
echo.

"!ARCHIVIST_PY!" -m archivist.app %ARGS%
set "CODE=!errorlevel!"
if !CODE! neq 0 (
    echo.
    echo   the app exited with code !CODE!
    echo   check the Connection tab, or run:  run_pipeline.bat --check
    pause
)
endlocal
exit /b %CODE%
