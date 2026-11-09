# AV Transcriber - update to the latest version on Windows.
# Double-click update_windows.bat (it runs this script for you).
#
# Downloads the newest code from GitHub, copies it over this folder, then runs
# the setup again (which only installs what's new). Your glossary.txt,
# config.toml, app settings, transcripts and the .venv folder are kept.

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$url = "https://github.com/DabRig/AVTool_CMOS/archive/refs/heads/claude/optimistic-thompson-as38s7.zip"

Write-Host ""
Write-Host "Updating AV Transcriber..." -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP ("av-transcriber-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile (Join-Path $tmp "update.zip") -UseBasicParsing
    Expand-Archive -LiteralPath (Join-Path $tmp "update.zip") -DestinationPath $tmp
    $new = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
    if (-not $new -or -not (Test-Path -LiteralPath (Join-Path $new.FullName "transcribe.py"))) {
        throw "The download looks wrong; nothing was changed."
    }
    # Personal files are only copied if they don't exist here yet.
    foreach ($keep in @("glossary.txt", "config.toml")) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $keep))) {
            Copy-Item -LiteralPath (Join-Path $new.FullName $keep) -Destination $PSScriptRoot
        }
    }
    robocopy $new.FullName $PSScriptRoot /E /NFL /NDL /NJH /NJS /NP `
        /XD (Join-Path $new.FullName ".venv") (Join-Path $new.FullName "samples\clips") `
        /XF glossary.txt config.toml gui_settings.json | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the new files failed." }
    Write-Host "  OK  Code updated" -ForegroundColor Green
}
catch {
    Write-Host "  X   $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

& (Join-Path $PSScriptRoot "setup_windows.ps1")
