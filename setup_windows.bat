@echo off
REM One-time setup on a new Windows PC: creates .venv in this folder and installs Litmus.
REM Needs Python 3.10-3.12 (python.org, tick "Add python.exe to PATH") and internet.
cd /d "%~dp0"
set "PY="
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.11 --version >nul 2>nul && set "PY=py -3.11"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
echo Using: %PY%
%PY% --version
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :fail
".venv\Scripts\python.exe" -m pip install -e .[dev] || goto :fail
echo.
echo Setup complete. Now double-click run_demo.bat
pause
exit /b 0
:fail
echo.
echo Setup failed. If pip says the Python version is not supported, install Python 3.12
echo (versions 3.13+ are not supported yet), delete the .venv folder and run this again.
pause
exit /b 1
