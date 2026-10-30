@echo off
cd /d "%~dp0..\..\"
".venv\Scripts\python.exe" run_ultron.py send "stop speaking" --timeout 5
