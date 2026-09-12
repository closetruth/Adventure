@echo off
REM ===== Bundle AimLoot into a standalone Windows executable =====
setlocal
pushd "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run install.bat first.
    pause
    popd
    endlocal
    exit /b 1
)

echo === Installing PyInstaller ===
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    popd
    endlocal
    exit /b 1
)

echo === Building AimLoot.exe ===
".venv\Scripts\python.exe" -m pip install pygame-ce -q
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean AimLoot.spec

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    popd
    endlocal
    exit /b 1
)

echo.
echo === Build finished ===
echo Executable: dist\AimLoot\AimLoot.exe
pause
popd
endlocal
