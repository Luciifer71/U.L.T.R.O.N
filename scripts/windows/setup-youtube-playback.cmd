@echo off
cd /d "%~dp0..\..\"
if not exist ".venv\Scripts\python.exe" (
  echo Project virtual environment missing. Complete the normal setup first.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements/browser.txt
if errorlevel 1 exit /b 1
echo Playback support installed. Restart Ultron. Microsoft Edge must be installed.
echo Ultron uses its own browser profile; it does not reuse your personal browser cookies.
