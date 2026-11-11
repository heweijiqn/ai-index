@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers"
"%~dp0.venv\Scripts\python.exe" -X utf8 crawler.py --login
set "RUN_EXIT=%ERRORLEVEL%"
pause
exit /b %RUN_EXIT%
