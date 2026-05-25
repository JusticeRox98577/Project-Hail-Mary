@echo off
echo Starting Project Hail Mary Auto Deploy...
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install it from https://python.org
    pause
    exit /b 1
)

python "%~dp0auto_deploy.py" %*
pause
