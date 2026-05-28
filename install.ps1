# Adventure installer (PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-PyVersion($exe) {
    try {
        $out = & $exe -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
        return $out
    } catch { return $null }
}

function Find-Python {
    $preferred = @()

    # py launcher versions (best first)
    foreach ($ver in @("3.12", "3.13", "3.11", "3.10")) {
        $py = Get-Command "py" -ErrorAction SilentlyContinue
        if ($py) {
            try {
                $exe = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
                if ($exe -and (Test-Path $exe) -and $exe -notmatch "\.bat$") {
                    $preferred += $exe.Trim()
                }
            } catch { }
        }
    }

    # pyenv real executables (not shims)
    $pyenvRoot = Join-Path $env:USERPROFILE ".pyenv\pyenv-win\versions"
    if (Test-Path $pyenvRoot) {
        Get-ChildItem $pyenvRoot -Directory | Sort-Object Name -Descending | ForEach-Object {
            $exe = Join-Path $_.FullName "python.exe"
            if (Test-Path $exe) { $preferred += $exe }
        }
    }

    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "${env:ProgramFiles}\Python"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem $root -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path $exe) { $preferred += $exe }
            }
    }

    foreach ($exe in ($preferred | Select-Object -Unique)) {
        if ($exe -match "\.bat$|shims") { continue }
        $v = Get-PyVersion $exe
        if ($v) {
            $major, $minor = $v.Split(" ")
            if ([int]$major -eq 3 -and [int]$minor -ge 10) {
                # Prefer 3.12/3.13 over 3.14 when multiple exist
                return $exe
            }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "[ERROR] Python 3.10+ not found." -ForegroundColor Red
    Write-Host "Install Python 3.12: https://www.python.org/downloads/windows/"
    Read-Host "Press Enter"
    exit 1
}

Write-Host "=== Using: $python ===" -ForegroundColor Cyan
& $python --version

if (Test-Path ".venv") {
    Write-Host "=== Removing old .venv ===" -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".venv"
}

Write-Host "=== Creating .venv ===" -ForegroundColor Cyan
& $python -m venv .venv

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip setuptools wheel

Write-Host "=== Installing requirements (pygame-ce) ===" -ForegroundColor Cyan
& $venvPy -m pip uninstall pygame -y 2>$null
& $venvPy -m pip install -r requirements.txt

Write-Host "=== Verify pygame ===" -ForegroundColor Cyan
& $venvPy -c "import pygame; print('pygame OK', pygame.version.ver)"

Write-Host ""
Write-Host "=== Install finished ===" -ForegroundColor Green
Read-Host "Press Enter"
