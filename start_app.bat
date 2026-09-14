@echo off
echo ==================================================
echo Starting PlotChoice OCR & Verification Web Server...
echo URL: http://localhost:8000
echo ==================================================
set PYTHONPATH=%~dp0
py -m uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
pause
