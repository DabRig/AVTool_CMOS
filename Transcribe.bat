@echo off
rem Terminal-style transcriber: drag a folder or file in when asked.
rem (Most people use the "AV Transcriber" shortcut instead.)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setup hasn't been run yet. Double-click setup_windows.bat first.
  pause
  exit /b 1
)
chcp 65001 >nul
set PYTHONUTF8=1
".venv\Scripts\python.exe" transcribe.py %*
echo.
pause
