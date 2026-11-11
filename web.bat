@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers"
"%~dp0.venv\Scripts\python.exe" -X utf8 web_app.py --open %*
set "WEB_EXIT=%ERRORLEVEL%"
if not "%WEB_EXIT%"=="0" pause
exit /b %WEB_EXIT%
