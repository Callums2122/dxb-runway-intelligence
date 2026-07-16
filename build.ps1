$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt --progress-bar off
$env:QT_QPA_PLATFORM = "offscreen"
& ".\.venv\Scripts\python.exe" -m pytest
Remove-Item Env:QT_QPA_PLATFORM
& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "DXB_RUNWAY.spec"

Write-Host "Built: $Root\dist\DXB RUNWAY.exe"

