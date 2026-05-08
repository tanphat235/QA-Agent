@echo off
title Drawing Analyzer - Backend (port 8001)
echo Starting backend on http://localhost:8001 ...
echo.
echo [!] Requires LangGraph API Server (start_studio.bat) to be running on port 2024 first.
echo.
"C:\Users\phat.phamt\AppData\Roaming\Python\Python313\Scripts\poetry.exe" run uvicorn qa_agent.server:app --host 0.0.0.0 --port 8001 --reload
pause
