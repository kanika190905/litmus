@echo off
REM Runs the automated tests (expect: "16 passed").
cd /d "%~dp0"
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\.venvs\prism\Scripts\python.exe" set "PYEXE=%USERPROFILE%\.venvs\prism\Scripts\python.exe"
if not defined PYEXE (
  echo Litmus is not installed on this PC yet. Double-click setup_windows.bat first.
  pause
  exit /b 1
)
"%PYEXE%" -m pytest -q tests
pause
