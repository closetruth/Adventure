@echo off
REM ===== Adventure installer (Windows) =====
REM Prefer Python 3.12/3.13 (pygame-ce wheels). Python 3.14 needs pygame-ce, not pygame.
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

set "PYEXE="

REM 1) py launcher: try 3.12, 3.13, then default
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V -c "import sys" >nul 2>nul
        if !errorlevel!==0 (
            for /f "delims=" %%F in ('py -%%V -c "import sys; print(sys.executable)"') do set "PYEXE=%%F"
        )
    )
)

REM 2) pyenv real python.exe (skip python.bat shims)
if not defined PYEXE if exist "%USERPROFILE%\.pyenv\pyenv-win\versions" (
    for %%V in (3.12.7 3.12.6 3.12.5 3.12.4 3.12.3 3.12.2 3.12.1 3.12.0 3.13.2 3.13.1 3.13.0) do (
        if not defined PYEXE if exist "%USERPROFILE%\.pyenv\pyenv-win\versions\%%V\python.exe" (
            set "PYEXE=%USERPROFILE%\.pyenv\pyenv-win\versions\%%V\python.exe"
        )
    )
)

REM 3) Standard install paths
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

REM 4) Last resort: py -3 (may be 3.14)
if not defined PYEXE (
    py -3 -c "import sys" >nul 2>nul
    if !errorlevel!==0 (
        for /f "delims=" %%F in ('py -3 -c "import sys; print(sys.executable)"') do set "PYEXE=%%F"
    )
)

if not defined PYEXE (
    echo [ERROR] Python 3.10+ not found.
    echo Install Python 3.12 from https://www.python.org/downloads/windows/
    echo Check "Add python.exe to PATH"
    pause
    popd
    endlocal
    exit /b 1
)

echo === Using: %PYEXE% ===
"%PYEXE%" --version

echo === Creating virtual environment (.venv) ===
if exist ".venv" rmdir /s /q ".venv" 2>nul
"%PYEXE%" -m venv .venv
if errorlevel 1 (
    echo [ERROR] venv failed. If you use pyenv, try: py -3.12 -m venv .venv
    pause
    popd
    endlocal
    exit /b 1
)

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo [ERROR] .venv\Scripts\python.exe missing
    pause
    popd
    endlocal
    exit /b 1
)

echo === Upgrading pip ===
"%VPY%" -m pip install --upgrade pip setuptools wheel

echo === Installing requirements (pygame-ce for Python 3.14) ===
"%VPY%" -m pip uninstall pygame -y >nul 2>nul
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Install failed.
    echo Try manually: .venv\Scripts\python.exe -m pip install pygame-ce
    pause
    popd
    endlocal
    exit /b 1
)

echo === Verifying pygame ===
"%VPY%" -c "import pygame; print('pygame OK', pygame.version.ver)"
if errorlevel 1 (
    echo [ERROR] pygame import failed
    pause
    popd
    endlocal
    exit /b 1
)

echo.
echo === Install finished ===
echo Double-click run.bat to start Adventure.
pause
popd
endlocal
exit /b 0
