@echo off
title Drawing Analyzer - Backend (port 8001)
echo Starting backend on http://localhost:8001 ...
"C:\Users\phat.phamt\AppData\Roaming\Python\Python313\Scripts\poetry.exe" run uvicorn qa_agent.server:app --host 0.0.0.0 --port 8001 --reload
pause
