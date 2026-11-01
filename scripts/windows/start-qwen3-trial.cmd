@echo off
rem Compatibility wrapper. Use start-ultron.cmd for normal startup.
call "%~dp0..\..\start-ultron.cmd" --qwen3 %*
exit /b %errorlevel%
