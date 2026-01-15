@echo off
title Omni-Visual - ADK Web UI
echo ========================================
echo   Omni-Visual Accessibility Navigator
echo          ADK Web UI Mode
echo ========================================
echo.

cd /d C:\Users\daars\.gemini\antigravity\scratch\omni-visual\src

echo Starting ADK Web UI...
echo.
echo Press Ctrl+C to stop the server.
echo ========================================
echo.

:: Open browser after a short delay (ADK typically runs on port 8000)
start "" cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8000/"

uv run adk web

pause
