@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM  ARCHIVIST — headless pipeline on Windows.
REM
REM    run_pipeline.bat "deep sea salvage"
REM    run_pipeline.bat "deep sea salvage" --garment light --no-generate
REM    run_pipeline.bat --check                 connection self-test
REM    run_pipeline.bat --plan "north sea oil"  auto-plan a collection
REM ===================================================================

REM --- resolve layout: zip bundle (flat) or repo checkout (scripts\windows) ---
set "HERE=%~dp0"
set "ROOT=%HERE%"
if not exist "%ROOT%requirements.txt" (
    for %%i in ("%HERE%..\..") do set "ROOT=%%~fi\"
)
cd /d "!ROOT!"

if not exist "!ROOT!env.cmd" (
    call "%HERE%setup.bat" || exit /b 1
)
call "!ROOT!env.cmd"

if "%~1"=="" (
    echo.
    echo   usage: run_pipeline.bat "topic" [options]
    echo          run_pipeline.bat --check
    echo          run_pipeline.bat --plan "theme"
    echo.
    exit /b 2
)

if /i "%~1"=="--check" (
    "!ARCHIVIST_PY!" -m archivist check
    goto :done
)

if /i "%~1"=="--plan" (
    "!ARCHIVIST_PY!" -m archivist plan %2 %3 %4 %5 %6 %7 %8 %9
    goto :done
)

set "TOPIC=%~1"
shift
set "REST="
:collect
if "%~1"=="" goto :run
set "REST=!REST! %1"
shift
goto :collect

:run
"!ARCHIVIST_PY!" -m archivist run "%TOPIC%" !REST!

:done
set "CODE=!errorlevel!"
if !CODE! neq 0 pause
endlocal
exit /b %CODE%
