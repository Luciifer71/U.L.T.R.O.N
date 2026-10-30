@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0run_ultron.py" report %*
exit /b %errorlevel%
