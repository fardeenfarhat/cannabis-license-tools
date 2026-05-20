@echo off
echo Starting License Watch...

REM Kill anything already on our ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7700 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5175 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM Start API
echo [1/2] Starting API on port 7700...
start "License Watch API" /MIN c:\python312\python.exe "%~dp0api.py"
timeout /t 3 /nobreak >nul

REM Start Vite
echo [2/2] Starting UI on port 5175...
start "License Watch UI" /MIN cmd /c "cd /d "%~dp0" && npm run dev -- --host 127.0.0.1 --port 5175"
timeout /t 5 /nobreak >nul

echo.
echo License Watch running:
echo   API  ^> http://127.0.0.1:7700
echo   UI   ^> http://127.0.0.1:5175
echo.
start http://127.0.0.1:5175
