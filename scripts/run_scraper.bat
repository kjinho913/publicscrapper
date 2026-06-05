@echo off
setlocal enabledelayedexpansion

REM run_scraper.bat - Web scraper launcher
REM
REM Usage:
REM   run_scraper.bat                          Interactive prompts for keyword and days
REM   run_scraper.bat --days 30               Pass args directly, no prompts
REM   run_scraper.bat --keyword AI --days 90  Pass args directly, no prompts
REM
REM NOTE: This file is 100% ASCII. Do not add non-ASCII characters.

REM Change to project root (one level up from scripts\)
cd /d "%~dp0.."

REM Select Python: prefer root .venv, then scraper\.venv, then system python
set PYTHON=python
if exist ".venv\Scripts\python.exe" set PYTHON=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "scraper\.venv\Scripts\python.exe" set PYTHON=scraper\.venv\Scripts\python.exe

REM Branch: if no args given, run interactive; otherwise pass args through
if "%~1"=="" goto INTERACTIVE
goto ARGS

:INTERACTIVE
set EXTRA=
set USER_KEYWORD=
set USER_DAYS=
set /p USER_KEYWORD=Search keyword [Enter=default]:
set /p USER_DAYS=Lookback days [Enter=default]:
if not "!USER_KEYWORD!"=="" set EXTRA=!EXTRA! --keyword "!USER_KEYWORD!"
if not "!USER_DAYS!"=="" set EXTRA=!EXTRA! --days !USER_DAYS!
goto RUN

:ARGS
set EXTRA= %*
goto RUN

:RUN
"%PYTHON%" scraper\main.py --once!EXTRA!

pause
