# AV Transcriber - one-time setup for Windows 10 / 11 (64-bit).
# Double-click setup_windows.bat (it runs this script for you).
# Safe to run again: anything already installed is skipped.
#
# Installs: ffmpeg and Python 3.12 (via winget, Windows' own installer), a
# private Python folder (.venv) with the Whisper engine - the NVIDIA CUDA
# version when an NVIDIA card is found - downloads the speech model once, and
# adds "AV Transcriber" shortcuts to the Desktop and the Start menu.

$ErrorActionPreference = "Continue"   # native tools report problems via exit codes
Set-Location -LiteralPath $PSScriptRoot
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

function Step($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  OK  $t" -ForegroundColor Green }
function Note($t) { Write-Host "  !   $t" -ForegroundColor Yellow }
function Fail($t) {
    Write-Host ""
    Write-Host "  X   $t" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

Step "AV Transcriber setup - about 15-20 minutes. Needs internet this one time."
Write-Host "  After this, transcription works fully offline."

if (-not [Environment]::Is64BitOperatingSystem) { Fail "AV Transcriber needs 64-bit Windows 10 or 11." }

# Files from a downloaded ZIP carry a 'from the internet' mark; clear it so
# Windows doesn't warn about each script again.
Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File -ErrorAction SilentlyContinue |
    Unblock-File -ErrorAction SilentlyContinue

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail "winget isn't available. Open the Microsoft Store, install or update 'App Installer', then run setup again."
}

# --- 1. ffmpeg ----------------------------------------------------------------
Step "Step 1/6 - ffmpeg (reads video files)"
function Find-FFmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $link = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ffmpeg.exe"
    if (Test-Path -LiteralPath $link) { return $link }
    $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packages) {
        $found = Get-ChildItem -LiteralPath $packages -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}
$ffmpeg = Find-FFmpeg
if (-not $ffmpeg) {
    winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $ffmpeg = Find-FFmpeg
}
if (-not $ffmpeg) { Fail "ffmpeg didn't install. Close this window and run setup again." }
Ok "ffmpeg: $ffmpeg"

# --- 2. Python ----------------------------------------------------------------
Step "Step 2/6 - Python 3.12"
function Find-Python {
    $candidates = @("py", (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe"), (Join-Path $env:WINDIR "py.exe"))
    foreach ($c in $candidates) {
        if (Get-Command $c -ErrorAction SilentlyContinue) {
            & $c -3.12 -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return $c }
        }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $py = Find-Python
}
if (-not $py) { Fail "Python 3.12 didn't install. Restart the computer and run setup again." }
Ok ("Python " + (& $py -3.12 -c "import platform; print(platform.python_version())"))

# --- 3. Graphics card ---------------------------------------------------------
Step "Step 3/6 - Graphics card"
$reqs = "requirements-cpu.txt"
$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if (-not $smi -and (Test-Path -LiteralPath (Join-Path $env:WINDIR "System32\nvidia-smi.exe"))) {
    $smi = Get-Item -LiteralPath (Join-Path $env:WINDIR "System32\nvidia-smi.exe")
}
if ($smi) {
    $smiPath = if ($smi.Source) { $smi.Source } else { $smi.FullName }
    $info = (& $smiPath --query-gpu=name,driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    $reqs = "requirements-nvidia.txt"
    Ok "NVIDIA graphics found: $info - using the fast CUDA engine"
    $driver = ($info -split ",")[-1].Trim()
    $major = 0
    [void][int]::TryParse(($driver -split "\.")[0], [ref]$major)
    if ($major -gt 0 -and $major -lt 528) {
        Note "Your NVIDIA driver ($driver) is older than the engine needs (528 or newer)."
        Note "Update it with the NVIDIA app / GeForce Experience or nvidia.com/drivers, then restart."
    }
} else {
    Note "No NVIDIA graphics found - using the CPU engine (works, but slower)."
}

# --- 4. Private Python folder ------------------------------------------------
Step "Step 4/6 - Whisper engine and friends (into a private folder called .venv)"
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPy) {
    $ver = (& $venvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
    if ($ver -ne "3.12") {
        Note "Rebuilding .venv (it was made with a different Python)"
        Remove-Item -LiteralPath (Join-Path $PSScriptRoot ".venv") -Recurse -Force
    }
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    & $py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the .venv folder." }
}
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
if ($reqs -eq "requirements-nvidia.txt") {
    Write-Host "  Downloading the NVIDIA libraries (about 1.5 GB) - this is the slow part."
}
& $venvPy -m pip install -r $reqs --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Installing packages failed (see above). Check the internet connection and run setup again." }
Ok "Python packages installed ($reqs)"

# --- 5. The model -------------------------------------------------------------
Step "Step 5/6 - Downloading the Whisper model (one time, about 1.6 GB)"
& $venvPy transcribe.py --download-model
if ($LASTEXITCODE -ne 0) { Fail "Model download failed. Check the internet connection and run setup again." }

# --- 6. Shortcuts + check ---------------------------------------------------
Step "Step 6/6 - Shortcuts, test clips and a final check"
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$icon = Join-Path $PSScriptRoot "avtool\gui\static\img\icon.ico"
$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs"),   # Start menu
    $PSScriptRoot
)
foreach ($dir in $places) {
    if (-not $dir) { continue }
    $lnk = $shell.CreateShortcut((Join-Path $dir "AV Transcriber.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m avtool.gui"
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "AV Transcriber - offline transcripts and subtitles"
    $lnk.Save()
}
Ok "Shortcuts added: Desktop, Start menu and this folder"

& $venvPy samples\make_samples.py | Out-Null
if ($LASTEXITCODE -eq 0) { Ok "Test clips made in samples\clips" }
& $venvPy transcribe.py --check

Step "Setup complete!"
Write-Host "  Open AV Transcriber from the Start menu or the Desktop shortcut."
Write-Host "  Tip: right-click its taskbar icon > Pin to taskbar."
Read-Host "Press Enter to close"
