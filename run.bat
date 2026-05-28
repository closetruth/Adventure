@echo off
REM ===== Launch Adventure (uses the .venv created by install.bat) =====
setlocal
pushd "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" run.py
    popd
    endlocal
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" run.py
    popd
    endlocal
    exit /b 0
)

echo [ERROR] Virtual environment not found. Please run install.bat first.
pause
popd
endlocal
