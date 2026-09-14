@echo off
echo ==================================================
echo Starting Qwen 2.5 7B LLM Service on Port 8080...
echo ==================================================
"%~dp0\bin\llama-cpp\llama-server.exe" -m "%~dp0\models\Qwen2.5-7B-Instruct-Q4_K_M.gguf" --port 8080 -c 16384 -t 8
pause
