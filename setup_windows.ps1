# AVTool CMOS — one-time setup for Windows 10/11.
# Right-click this file > "Run with PowerShell", or in PowerShell:
#     powershell -ExecutionPolicy Bypass -File setup_windows.ps1
# Uses winget (built into Windows 11 and recent Windows 10).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step($t) { Write-Host "`n$t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  OK  $t" -ForegroundColor Green }
function Fail($t) { Write-Host "`n  X  $t`n" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }

Step "AVTool CMOS setup - about 10-15 minutes, needs internet this once."

Step "Step 1/5 - ffmpeg and Python 3.12"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Fail "winget not found. Install 'App Installer' from the Microsoft Store." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
}
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) {
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
}
# Refresh PATH for this window so the new tools are found.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Fail "ffmpeg installed but not found yet. Close this window and run setup again." }
Ok "ffmpeg and Python ready"

Step "Step 2/5 - Which engine?"
$reqs = "requirements-cpu.txt"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $reqs = "requirements-nvidia.txt"
    Ok "NVIDIA GPU found - using faster-whisper on CUDA"
} else {
    Ok "No NVIDIA GPU - using faster-whisper on the CPU (works, slower)"
}

Step "Step 3/5 - Private Python environment (.venv) and Whisper"
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -r $reqs --quiet
if ($LASTEXITCODE -ne 0) { Fail "Package install failed (see above). Re-run setup." }
Ok "Python packages installed ($reqs)"

Step "Step 4/5 - Downloading the Whisper model (one time, about 1.6 GB)"
& .venv\Scripts\python.exe transcribe.py --download-model
if ($LASTEXITCODE -ne 0) { Fail "Model download failed. Check the internet connection and re-run." }

Step "Step 5/5 - Test clips and check"
& .venv\Scripts\python.exe samples\make_samples.py | Out-Null
& .venv\Scripts\python.exe transcribe.py --check

Step "Setup complete! Double-click Transcribe.bat to start."
Read-Host "Press Enter to close"
