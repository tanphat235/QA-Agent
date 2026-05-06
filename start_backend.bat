@echo off
title Drawing Analyzer - Backend (port 8000)
echo Starting backend on http://localhost:8000 ...
"C:\Users\phat.phamt\AppData\Roaming\Python\Python313\Scripts\poetry.exe" run uvicorn qa_agent.server:app --host 0.0.0.0 --port 8000 --reload
pause
