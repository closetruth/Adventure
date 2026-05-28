@echo off
REM Fix mini-game deps only (pygame-ce) in existing .venv
setlocal
pushd "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

echo === Uninstall old pygame, install pygame-ce ===
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
".venv\Scripts\python.exe" -m pip uninstall pygame -y
".venv\Scripts\python.exe" -m pip install "pygame-ce>=2.5.2"
".venv\Scripts\python.exe" -c "import pygame; print('OK', pygame.version.ver)"

echo.
echo Done. Restart Adventure and try the game again.
pause
popd
endlocal
