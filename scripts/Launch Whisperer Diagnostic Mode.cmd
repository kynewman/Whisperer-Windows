@echo off
setlocal

set "LOGDIR=%LOCALAPPDATA%\Whisperer\logs"
if "%LOCALAPPDATA%"=="" set "LOGDIR=%TEMP%\Whisperer\logs"
if "%LOGDIR%"=="\Whisperer\logs" set "LOGDIR=%TMP%\Whisperer\logs"
if "%LOGDIR%"=="\Whisperer\logs" set "LOGDIR=%SystemRoot%\Temp\Whisperer\logs"
if not "%WHISPERER_LOG_DIR%"=="" set "LOGDIR=%WHISPERER_LOG_DIR%"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>nul

set "LOGFILE=%LOGDIR%\diagnostic-launch.log"
>>"%LOGFILE%" echo.
>>"%LOGFILE%" echo --- Diagnostic launch %DATE% %TIME% ---
>>"%LOGFILE%" echo app_dir=%~dp0
>>"%LOGFILE%" echo exe=%~dp0Whisperer.exe
>>"%LOGFILE%" echo args=%*
ver >>"%LOGFILE%" 2>&1

set "WHISPERER_DIAGNOSTIC_LAUNCH=1"
set "WHISPERER_LOG_DIR=%LOGDIR%"
set "WHISPERER_VERBOSE_CHROMIUM_LOGS=1"

echo Launching Whisperer in diagnostic mode...
echo Logs will be written to: %LOGDIR%
echo Diagnostic wrapper log: %LOGFILE%
echo.

start "" "%~dp0Whisperer.exe" %*
set "LAUNCH_RESULT=%ERRORLEVEL%"
>>"%LOGFILE%" echo start_result=%LAUNCH_RESULT%

if not "%LAUNCH_RESULT%"=="0" (
    echo Whisperer could not be started. Result: %LAUNCH_RESULT%
    >>"%LOGFILE%" echo Whisperer could not be started. Result: %LAUNCH_RESULT%
    pause
)
