# Adventure installer (PowerShell) - use if install.bat cannot find Python
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $candidates = @()
    foreach ($name in @("py", "python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "${env:ProgramFiles}\Python",
        "${env:ProgramFiles(x86)}\Python"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem $root -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path $exe) { $candidates += $exe }
            }
    }
    foreach ($exe in ($candidates | Select-Object -Unique)) {
        try {
            $ver = & $exe -c "import sys; print(sys.version_info[0:2])" 2>$null
            if ($ver -match "3,\s*1[0-9]") { return $exe }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host ""
    Write-Host "[ERROR] Python 3.10+ not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install from: https://www.python.org/downloads/windows/"
    Write-Host "Check: Add python.exe to PATH"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "=== Using: $python ===" -ForegroundColor Cyan
& $python --version

Write-Host "=== Creating .venv ===" -ForegroundColor Cyan
& $python -m venv .venv

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "=== Upgrading pip ===" -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip

Write-Host "=== Installing requirements ===" -ForegroundColor Cyan
& $venvPy -m pip install -r requirements.txt

Write-Host ""
Write-Host "=== Install finished ===" -ForegroundColor Green
Write-Host "Double-click run.bat to start."
Read-Host "Press Enter to exit"
