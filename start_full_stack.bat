@echo off
echo ==================================================
echo Starting Full PlotChoice Real Estate AI Stack...
echo 1. Local AI Service (llama-server :8080)
echo 2. Web Application (FastAPI :8000)
echo ==================================================
start "Qwen 2.5 7B AI Service" cmd /k "C:\Github\OCR-LEGAL-APP\start_llama_server.bat"
timeout /t 3
start "PlotChoice Web App" cmd /k "C:\Github\OCR-LEGAL-APP\start_app.bat"
echo Both services launched in separate windows.
