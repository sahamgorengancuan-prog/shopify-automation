@echo off
setlocal EnableDelayedExpansion
REM ===================================================================
REM  ARCHIVIST — headless pipeline on Windows.
REM
REM    run_pipeline.bat --auto                  discover AND design (the whole bot)
REM    run_pipeline.bat --house                 V9 house system end to end
REM    run_pipeline.bat --house --topic harbor  house system on a chosen signal
REM    run_pipeline.bat --volume                rank roots by relative search volume
REM    run_pipeline.bat --discover              research only
REM    run_pipeline.bat "deep sea salvage"      design one named topic
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

if "%~1"=="" goto :usage

REM --- subcommands; everything after the first argument is passed through ---
set "MODE="
if /i "%~1"=="--check"    set "MODE=check"
if /i "%~1"=="--auto"     set "MODE=autopilot"
if /i "%~1"=="--house"    set "MODE=house"
if /i "%~1"=="--volume"   set "MODE=volume"
if /i "%~1"=="--discover" set "MODE=discover"
if /i "%~1"=="--plan"     set "MODE=plan"
if defined MODE shift
if defined MODE goto :collect

set "MODE=run"
set "TOPIC=%~1"
shift

:collect
if "%~1"=="" goto :run
set "REST=!REST! %1"
shift
goto :collect

:run
if defined TOPIC (
    "!ARCHIVIST_PY!" -m archivist run "!TOPIC!" !REST!
) else (
    "!ARCHIVIST_PY!" -m archivist !MODE! !REST!
)
goto :done

:usage
echo.
echo   usage: run_pipeline.bat --auto                the whole bot
echo          run_pipeline.bat --house [options]     V9 house system
echo          run_pipeline.bat --volume              rank roots by search volume
echo          run_pipeline.bat --discover [options]  research only
echo          run_pipeline.bat "topic" [options]     design one named topic
echo          run_pipeline.bat --check
echo          run_pipeline.bat --plan "theme"
echo.
endlocal
exit /b 2

:done
set "CODE=!errorlevel!"
if !CODE! neq 0 pause
endlocal
exit /b %CODE%
