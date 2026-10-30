@echo off
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0..\..\run_ultron.py" report %*
exit /b %errorlevel%
