@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers"
"%~dp0.venv\Scripts\python.exe" -X utf8 run_daily.py %*
set "RUN_EXIT=%ERRORLEVEL%"
echo.
echo Exit code: %RUN_EXIT%
echo Output folder: %~dp0output
pause
exit /b %RUN_EXIT%
