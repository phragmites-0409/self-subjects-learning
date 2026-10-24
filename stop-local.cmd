@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0subjects-learning-2\scripts\stop.ps1"
if errorlevel 1 pause
