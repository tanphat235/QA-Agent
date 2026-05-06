@echo off
title Drawing Analyzer - Frontend (port 5173)
echo Starting frontend on http://localhost:5173 ...
cd /d "%~dp0web"
npm run dev
pause
