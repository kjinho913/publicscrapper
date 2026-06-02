@echo off
REM run_dashboard.bat - Start Flask dashboard server and open browser
REM ASCII-only: safe for both UTF-8 and CP949 (Windows default)

REM Change to project root (one level up from scripts\)
cd /d "%~dp0.."

REM Select Python: prefer root .venv, then scraper\.venv, then system python
set PYTHON=python
if exist ".venv\Scripts\python.exe" set PYTHON=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "scraper\.venv\Scripts\python.exe" set PYTHON=scraper\.venv\Scripts\python.exe

REM Launch server in a new window that stays open even if python exits (cmd /k)
start "Dashboard Server" cmd /k ""%PYTHON%" dashboard\app.py"

REM Wait for server to start
timeout /t 4 /nobreak >nul

REM Open browser
start "" "http://127.0.0.1:5050"

echo Dashboard server started in a separate window.
echo Open http://127.0.0.1:5050 in your browser.
echo To stop the server, close the "Dashboard Server" window.
