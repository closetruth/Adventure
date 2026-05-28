@echo off
REM Test mini-game standalone (needs session file from main app normally)
setlocal
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install pygame -q
    echo Run Adventure first, then use Inventory - Start Game.
    echo Or: python games\pet_arena.py ^<session_in.json^>
) else (
    echo Run install.bat first.
)
pause
popd
endlocal
