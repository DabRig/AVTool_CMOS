@echo off
rem Double-click to update AV Transcriber to the newest version.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_windows.ps1"
