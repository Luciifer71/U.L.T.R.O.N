@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0collect_ultron_report.py" %*
exit /b %errorlevel%
