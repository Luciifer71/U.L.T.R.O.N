@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" send_intent.py "stop speaking" --timeout 5
