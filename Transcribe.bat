@echo off
rem Double-click to transcribe. It asks you to drag in a folder or file.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setup hasn't been run yet. Right-click setup_windows.ps1 and choose "Run with PowerShell".
  pause
  exit /b 1
)
chcp 65001 >nul
".venv\Scripts\python.exe" transcribe.py %*
echo.
pause
