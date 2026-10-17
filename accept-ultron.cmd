@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0ultron_acceptance.py" %*
exit /b %errorlevel%
