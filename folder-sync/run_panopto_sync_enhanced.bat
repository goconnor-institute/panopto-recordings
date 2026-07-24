
@echo off
REM Enhanced Panopto Synchronization Scheduled Task
REM Includes comprehensive logging and error handling

setlocal enabledelayedexpansion

REM === DEBUG: Confirm script is running ===
echo [DEBUG] Batch file started

REM === Path Setup ===
REM Repo root is one level up from this script (folder-sync\..), since
REM panopto_windows_safe.py loads pt_class_groups.xlsx and .env relative to the repo root.
set "SCRIPT_DIR=%~dp0.."
set "LOG_DIR=%SCRIPT_DIR%\scheduled_logs"

REM === Safe timestamp (no colons or spaces) ===
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set mydate=%%c-%%a-%%b
for /f "tokens=1-3 delims=:., " %%a in ("%time%") do set mytime=%%a-%%b-%%c
set "TIMESTAMP=%mydate%_%mytime%"

REM Fallback log file name if timestamp fails
if "%TIMESTAMP%"=="_--" set "TIMESTAMP=fallback"
set "LOG_FILE=%LOG_DIR%\scheduled_run_%TIMESTAMP%.log"

REM Create logs directory if it doesn't exist
echo Checking/creating log directory: "%LOG_DIR%" >> "%LOG_FILE%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%LOG_DIR%" (
    echo ERROR: Could not create log directory "%LOG_DIR%" >> "%LOG_FILE%"
    exit /b 1
)

REM Start logging
echo ================================================= >> "%LOG_FILE%"
echo Panopto Sync Scheduled Task Started >> "%LOG_FILE%"
echo Date/Time: %date% %time% >> "%LOG_FILE%"
echo ================================================= >> "%LOG_FILE%"


REM Change to script directory using pushd for robust path handling
echo Changing to script directory: "%SCRIPT_DIR%" >> "%LOG_FILE%"
pushd "%SCRIPT_DIR%" 2>>"%LOG_FILE%"
if !errorlevel! neq 0 (
    echo ERROR: Failed to change to script directory "%SCRIPT_DIR%" >> "%LOG_FILE%"
    goto :error
)

REM Activate virtual environment

echo Activating virtual environment: "prod-venv\Scripts\activate.bat" >> "%LOG_FILE%"
if exist "prod-venv\Scripts\activate.bat" (
    call "prod-venv\Scripts\activate.bat" 2>>"%LOG_FILE%"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to activate virtual environment >> "%LOG_FILE%"
        goto :error
    )
) else (
    echo ERROR: activate.bat not found at "prod-venv\Scripts\activate.bat" >> "%LOG_FILE%"
    goto :error
)

REM Run the script

echo Running Panopto synchronization script: python folder-sync\panopto_windows_safe.py >> "%LOG_FILE%"
if exist "folder-sync\panopto_windows_safe.py" (
    python folder-sync\panopto_windows_safe.py >> "%LOG_FILE%" 2>&1
    set SCRIPT_EXIT_CODE=!errorlevel!
) else (
    echo ERROR: panopto_windows_safe.py not found in "%SCRIPT_DIR%\folder-sync" >> "%LOG_FILE%"
    set SCRIPT_EXIT_CODE=1
    goto :error
)

REM Log completion
echo ================================================= >> "%LOG_FILE%"
if !SCRIPT_EXIT_CODE! equ 0 (
    echo Script completed successfully >> "%LOG_FILE%"
    echo Exit code: !SCRIPT_EXIT_CODE! >> "%LOG_FILE%"
) else (
    echo Script completed with errors >> "%LOG_FILE%"
    echo Exit code: !SCRIPT_EXIT_CODE! >> "%LOG_FILE%"
)
echo End time: %date% %time% >> "%LOG_FILE%"
echo ================================================= >> "%LOG_FILE%"

REM Clean up old log files (keep last 10)
echo Cleaning up old log files in "%LOG_DIR%" >> "%LOG_FILE%"
for /f "skip=10 delims=" %%F in ('dir /b /o-d "%LOG_DIR%\scheduled_run_*.log" 2^>nul') do (
    del "%LOG_DIR%\%%F" 2>nul
)

popd
goto :end

:error
echo FATAL ERROR occurred during script execution >> "%LOG_FILE%"
echo End time: %date% %time% >> "%LOG_FILE%"
exit /b 1

:end
echo [DEBUG] Script finished
echo Script finished >> "%LOG_FILE%"
exit /b %SCRIPT_EXIT_CODE%