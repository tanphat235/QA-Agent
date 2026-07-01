@echo off
title LangGraph API Server (port 2024)
echo Starting LangGraph API Server on http://127.0.0.1:2024 ...
echo Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
echo.
echo [!] Start this BEFORE start_backend.bat
echo.
poetry run langgraph dev
pause
    