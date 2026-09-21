@echo off
echo ========================================
echo   AI Agents Platform (Prototype)
echo ========================================
echo.

set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo [ERROR] .venv not found - run setup.bat first.
    pause
    exit /b 1
)

echo Starting Backend Server (port 8000)...
cd /d "%~dp0server"
start "Backend - FastAPI" cmd /k ""%VPY%" api.py"

echo Starting Frontend Dev Server...
cd /d "%~dp0frontend"
start "Frontend - Vite" cmd /k "npm run dev"

echo.
echo ========================================
echo   Both servers are starting!
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5000
echo   Admin:    admin / admin123
echo ========================================
pause
