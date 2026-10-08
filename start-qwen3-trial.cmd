@echo off
setlocal
rem Stop existing ULTRON components before using this separate trial profile.
set "LLM_MODEL=qwen3:8b"
set "LLM_THINKING=off"
set "LLM_CONTEXT=4096"
set "LLM_TEMPERATURE=0"
set "LLM_SEED=42"
echo Starting Qwen3 trial: thinking off, context 4096, temperature 0, seed 42.
echo This does not edit .env. Stop all components before returning to the normal launcher.
call "%~dp0start-ultron.cmd" %*
exit /b %errorlevel%
