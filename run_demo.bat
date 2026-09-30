@echo off
REM Starts the Litmus web demo. Works on any PC after setup_windows.bat (or an existing install).
cd /d "%~dp0"
set "EXE="
if exist ".venv\Scripts\litmus.exe" set "EXE=.venv\Scripts\litmus.exe"
if not defined EXE if exist "%USERPROFILE%\.venvs\prism\Scripts\litmus.exe" set "EXE=%USERPROFILE%\.venvs\prism\Scripts\litmus.exe"
if not defined EXE (
  echo Litmus is not installed on this PC yet. Double-click setup_windows.bat first.
  pause
  exit /b 1
)
echo.
echo  Starting Litmus...  the browser opens http://127.0.0.1:8000 in 45 seconds
echo  (the AI model needs time to load). Keep this window open. Ctrl+C stops it.
echo.
if not defined LITMUS_NO_BROWSER start "" /b cmd /c "timeout /t 45 /nobreak >nul & start "" http://127.0.0.1:8000"
"%EXE%" serve
pause
