@echo off
chcp 65001 >nul
REM run_scraper.bat - Run scraper with optional additional keywords
REM Saved as UTF-8 (no BOM); chcp 65001 enforced above for Korean prompts/input

REM Change to project root (one level up from scripts\)
cd /d "%~dp0.."

REM Select Python: prefer root .venv, then scraper\.venv, then system python
set PYTHON=python
if exist ".venv\Scripts\python.exe" set PYTHON=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "scraper\.venv\Scripts\python.exe" set PYTHON=scraper\.venv\Scripts\python.exe

REM Prompt for extra keywords (Korean input OK on UTF-8 console)
set ADD_KW=
set /p ADD_KW="추가 검색어 입력 (쉼표 구분, 없으면 Enter): "

if "%ADD_KW%"=="" (
    "%PYTHON%" scraper\main.py --once
) else (
    "%PYTHON%" scraper\main.py --once --add-keywords "%ADD_KW%"
)

pause
