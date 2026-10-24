@echo off
setlocal
set "SUBJECTS_PROJECT=subjects-learning-2"
if exist "%~dp0subjects-learning-3\version.json" set "SUBJECTS_PROJECT=subjects-learning-3"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0%SUBJECTS_PROJECT%\scripts\stop.ps1"
if errorlevel 1 pause
