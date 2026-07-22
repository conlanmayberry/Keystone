@echo off
setlocal

cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Could not find %PYTHON%
    echo Set up the virtual environment first:
    echo   py -3.12 -m venv .venv
    echo   .venv\Scripts\pip install -e ".[dev]"
    echo   .venv\Scripts\python scripts\init_db.py
    pause
    exit /b 1
)

echo Starting the MegaChud backend...
start "MegaChud Server" "%PYTHON%" -m uvicorn megachud.api.app:create_app --factory --host 127.0.0.1 --port 8000

echo Waiting for it to come up...
:waitloop
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('127.0.0.1', 8000) } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)

echo Opening the dashboard in your browser...
start "" "http://127.0.0.1:8000"

echo.
echo MegaChud is running at http://127.0.0.1:8000
echo Close the "MegaChud Server" window to stop the backend.
