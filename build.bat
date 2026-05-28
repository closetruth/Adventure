@echo off
REM ===== Bundle Adventure into a standalone Windows executable =====
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

echo === Building Adventure.exe ===
".venv\Scripts\python.exe" -m pip install pygame-ce -q
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean Adventure.spec

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    popd
    endlocal
    exit /b 1
)

echo.
echo === Build finished ===
echo Executable: dist\Adventure\Adventure.exe
pause
popd
endlocal
