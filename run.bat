@echo off
title MEP Floor Requisition Portal
echo =======================================================
echo   MEP GROUP - Daily Floor Requisition Portal
echo   Automated ERP Scraper & Spare Parts Tracker
echo =======================================================
echo.
echo Starting application server at http://localhost:8000 ...
echo Press Ctrl+C to stop the server.
echo.

start "" http://localhost:8000
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause
