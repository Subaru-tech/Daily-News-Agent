@echo off
title Daily News Agent
echo ===================================
echo   Daily News Agent - Auto Restart
echo ===================================
echo.

cd /d "%~dp0"

:start
echo [%date% %time%] Starting agent...
call venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000

echo.
echo [%date% %time%] Agent crashed or stopped. Restarting in 10 seconds...
echo Press Ctrl+C to stop completely.
timeout /t 10 /nobreak >nul
goto start
