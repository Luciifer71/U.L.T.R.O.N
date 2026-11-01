@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: U.L.T.R.O.N. Python environment not found.
    exit /b 1
)

if /I "%~1"=="--qwen25" goto qwen25
if /I "%~1"=="--qwen3" goto qwen3
if /I "%~1"=="--menu" goto menu
if /I "%~1"=="--help" goto help
if not "%~1"=="" goto passthrough

:qwen3
if /I "%~1"=="--qwen3" shift
set "LLM_MODEL=qwen3:8b"
set "LLM_THINKING=off"
set "LLM_CONTEXT=4096"
set "LLM_TEMPERATURE=0"
set "LLM_SEED=42"
echo Starting U.L.T.R.O.N. with Qwen3:8b...
goto launch

:qwen25
if /I "%~1"=="--qwen25" shift
set "LLM_MODEL=qwen2.5:7b"
set "LLM_THINKING=default"
set "LLM_CONTEXT="
set "LLM_TEMPERATURE="
set "LLM_SEED="
echo Starting U.L.T.R.O.N. with Qwen2.5:7b...
goto launch

:menu
echo.
echo =========================================
echo            U.L.T.R.O.N. / START
echo =========================================
echo.
echo [1] Start Qwen3:8b  [Preferred]
echo [2] Start Qwen2.5:7b
echo [3] Exit
echo.
choice /c 123 /n /m "Select an option: "
if errorlevel 3 exit /b 0
if errorlevel 2 goto qwen25
goto qwen3

:help
echo.
echo start-ultron.cmd            Start with Qwen3:8b
echo start-ultron.cmd --menu     Select a model
echo start-ultron.cmd --qwen3    Start with Qwen3:8b
echo start-ultron.cmd --qwen25   Start with Qwen2.5:7b
echo start-ultron.cmd --help     Show this help
exit /b 0

:passthrough
echo Forwarding arguments to standard U.L.T.R.O.N. startup.
"%PYTHON%" "%~dp0run_ultron.py" start %*
exit /b %errorlevel%

:launch
"%PYTHON%" "%~dp0run_ultron.py" start %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%
