@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0start_ultron.py" %*
exit /b %errorlevel%
