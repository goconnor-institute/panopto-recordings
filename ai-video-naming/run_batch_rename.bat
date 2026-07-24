@echo off
REM Batch Panopto Session Renamer - Scheduled Task
REM Renames all IOE folder sessions with AI topics and week numbers

setlocal enabledelayedexpansion

REM === Path Setup ===
REM Repo root is one level up from this script (ai-video-naming\..), since
REM rename_all_ioe_folders.py loads pt_class_groups.xlsx and .env relative to the repo root.
set "SCRIPT_DIR=%~dp0.."
set "LOG_DIR=%SCRIPT_DIR%\scheduled_logs"
set "VENV_DIR=%SCRIPT_DIR%\prod-venv"

REM === Safe timestamp ===
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set mydate=%%c-%%a-%%b
for /f "tokens=1-3 delims=:., " %%a in ("%time%") do set mytime=%%a-%%b-%%c
set "TIMESTAMP=%mydate%_%mytime%"
if "%TIMESTAMP%"=="_--" set "TIMESTAMP=fallback"
set "LOG_FILE=%LOG_DIR%\batch_rename_scheduled_%TIMESTAMP%.log"

REM === Create log directory ===
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM === Start logging ===
echo ================================================= >> "%LOG_FILE%"
echo Batch Panopto Rename - Scheduled Task >> "%LOG_FILE%"
echo Date/Time: %date% %time% >> "%LOG_FILE%"
echo ================================================= >> "%LOG_FILE%"

REM === Change to script directory ===
pushd "%SCRIPT_DIR%" 2>>"%LOG_FILE%"
if !errorlevel! neq 0 (
    echo ERROR: Failed to change to script directory >> "%LOG_FILE%"
    goto :error
)

REM === Activate virtual environment ===
echo Activating virtual environment... >> "%LOG_FILE%"
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat" 2>>"%LOG_FILE%"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to activate virtual environment >> "%LOG_FILE%"
        goto :error
    )
) else (
    echo ERROR: venv not found at "%VENV_DIR%\Scripts\activate.bat" >> "%LOG_FILE%"
    goto :error
)

REM === Run the batch rename script ===
echo Running batch rename... >> "%LOG_FILE%"
echo ------------------------------------------------- >> "%LOG_FILE%"

set "PYTHONIOENCODING=utf-8"
python ai-video-naming\rename_all_ioe_folders.py >> "%LOG_FILE%" 2>&1
set RENAME_EXIT=!errorlevel!

echo ------------------------------------------------- >> "%LOG_FILE%"
echo Rename script exited with code: %RENAME_EXIT% >> "%LOG_FILE%"

if %RENAME_EXIT% neq 0 (
    echo WARNING: Some folders may have failed. Check logs for details. >> "%LOG_FILE%"
)

REM === Cleanup ===
popd
echo ================================================= >> "%LOG_FILE%"
echo Completed: %date% %time% >> "%LOG_FILE%"
echo Exit code: %RENAME_EXIT% >> "%LOG_FILE%"
echo ================================================= >> "%LOG_FILE%"

endlocal
exit /b %RENAME_EXIT%

:error
echo ================================================= >> "%LOG_FILE%"
echo FATAL ERROR - Task aborted: %date% %time% >> "%LOG_FILE%"
echo ================================================= >> "%LOG_FILE%"
popd 2>nul
endlocal
exit /b 1
